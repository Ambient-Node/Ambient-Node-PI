"""이벤트 핸들러 (최종 수정: 자연풍 사용 시간 집계 및 타이머 통계 포함)"""

import json
import uuid
from datetime import datetime

class EventHandlers:
    def __init__(self, db, mqtt_client):
        self.db = db
        self.mqtt = mqtt_client
        self.current_session_id = None
        
        self._load_active_session()

    def _load_active_session(self):
        """DB에서 현재 활성 세션 복구"""
        try:
            query = """
            SELECT session_id
            FROM user_sessions
            WHERE is_active = TRUE
            ORDER BY session_start DESC
            LIMIT 1
            """
            self.db.execute(query)
            row = self.db.fetchone()
            if row and row.get('session_id'):
                self.current_session_id = row['session_id']
                print(f"[Handler] Restored active session: {self.current_session_id}")
            else:
                print("[Handler] No active session to restore")
        except Exception as e:
            print(f"[Handler] Failed to load active session: {e}")

    # -------------------------
    # 사용자 관리 핸들러
    # -------------------------
    def handle_user_register(self, payload):
        user_id = payload.get('user_id')
        username = payload.get('username')
        image_path = payload.get('image_path')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        query = """
        INSERT INTO users (user_id, username, image_path, created_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE
        SET username = EXCLUDED.username, image_path = EXCLUDED.image_path, updated_at = CURRENT_TIMESTAMP
        """
        self.db.execute(query, (user_id, username, image_path, timestamp))
        print(f"[Handler] User registered: {username} ({user_id})")

        self.mqtt.publish("ambient/user/register-ack", {
            "user_id": user_id,
            "success": True,
            "timestamp": datetime.now().isoformat()
        })

    def handle_user_update(self, payload):
        user_id = payload.get('user_id')
        username = payload.get('username')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        query = """
        UPDATE users
        SET username = %s, updated_at = %s
        WHERE user_id = %s
        """
        self.db.execute(query, (username, timestamp, user_id))
        print(f"[Handler] User updated: {user_id} -> {username}")

    def handle_user_delete(self, payload):
        user_id = payload.get('user_id')
        try:
            self.db.execute("DELETE FROM device_events WHERE user_id = %s", (user_id,))
            self.db.execute("""
                UPDATE user_sessions 
                SET selected_user_ids = array_remove(selected_user_ids, %s)
                WHERE %s = ANY(selected_user_ids)
            """, (user_id, user_id))
            self.db.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            print(f"[Handler] User deleted from DB: {user_id}")
        except Exception as e:
            print(f"[Handler] Failed to delete user {user_id}: {e}")

    # -------------------------
    # 세션 관리 핸들러
    # -------------------------
    def handle_user_select(self, payload):
        user_list = payload.get('user_list', [])
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        if self.current_session_id:
            query = "UPDATE user_sessions SET session_end = %s, is_active = FALSE WHERE session_id = %s"
            self.db.execute(query, (timestamp, self.current_session_id))
            print(f"[Handler] Session ended: {self.current_session_id}")

        if len(user_list) > 0:
            session_id = f"sess-{uuid.uuid4().hex[:12]}"
            user_ids = [u['user_id'] for u in user_list]
            query = """
            INSERT INTO user_sessions (session_id, selected_user_ids, session_start, is_active)
            VALUES (%s, %s, %s, TRUE)
            """
            self.db.execute(query, (session_id, user_ids, timestamp))
            self.current_session_id = session_id
            print(f"[Handler] Session created: {session_id} Users: {user_ids}")
            
            self.mqtt.publish("ambient/session/active", {
                "session_id": session_id,
                "user_list": user_list,
                "timestamp": timestamp
            }, qos=1, retain=True)
        else:
            self.current_session_id = None
            print("[Handler] All users deselected")
            self.mqtt.publish("ambient/session/active", {
                "session_id": None,
                "user_list": [],
                "timestamp": timestamp
            }, qos=1, retain=True)

    def handle_session_request(self, payload):
        try:
            query = """
            SELECT session_id, selected_user_ids FROM user_sessions
            WHERE is_active = TRUE ORDER BY session_start DESC LIMIT 1
            """
            self.db.execute(query)
            row = self.db.fetchone()
            
            if row:
                session_id = row['session_id']
                user_ids = row.get('selected_user_ids') or []
                user_list = [{"user_id": uid} for uid in user_ids]
                resp = {"session_id": session_id, "user_list": user_list}
                self.current_session_id = session_id
            else:
                resp = {"session_id": None, "user_list": []}
            
            resp["timestamp"] = datetime.now().isoformat()
            self.mqtt.publish("ambient/session/active", resp, qos=1, retain=True)
        except Exception as e:
            print(f"[Handler] Failed to handle session request: {e}")

    # -------------------------
    # 장치 제어 핸들러 (로그 저장)
    # -------------------------
    def handle_speed_change(self, payload):
        speed = payload.get('speed')
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        self.db.execute("UPDATE current_status SET fan_speed = %s, last_updated = %s WHERE id = 1", (speed, timestamp))
        self._log_event(user_id, 'speed_change', {"speed": speed}, timestamp)
        print(f"[Handler] Speed: {speed}")

    def handle_direction_change(self, payload):
        direction = payload.get('direction')
        toggle_on = payload.get('toggleOn', 0)
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        self._log_event(user_id, 'direction_change', {"direction": direction, "toggleOn": toggle_on}, timestamp)
        print(f"[Handler] Direction: {direction}")

    def handle_mode_change(self, payload):
        """
        모드 변경 저장
        Payload 예시: {"type": "wind", "mode": "natural_wind"}
        """
        mode = payload.get('mode')
        cmd_type = payload.get('type', 'motor') # default: motor
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        # 회전 모드(motor)인 경우에만 상태 테이블 업데이트 (자연풍은 상태 테이블 스키마에 없으면 생략 or 추가 필요)
        if cmd_type == 'motor':
            self.db.execute("UPDATE current_status SET rotation_mode = %s, last_updated = %s WHERE id = 1", (mode, timestamp))

        # 로그는 type 포함해서 통으로 저장 (통계용)
        event_data = {"type": cmd_type, "mode": mode}
        self._log_event(user_id, 'mode_change', event_data, timestamp)
        print(f"[Handler] Mode: {mode} (Type: {cmd_type})")

    def handle_timer_set(self, payload):
        duration_sec = payload.get('duration_sec')
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        self._log_event(user_id, 'timer', {"duration_sec": duration_sec}, timestamp)
        print(f"[Handler] Timer set: {duration_sec}s")

    def handle_face_detected(self, payload):
        user_id = payload.get('user_id')
        confidence = payload.get('confidence')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()
        # 세션 ID 자동 매핑
        self._log_event(user_id, 'face_detected', {"confidence": confidence}, timestamp)

    def handle_face_lost(self, payload):
        user_id = payload.get('user_id')
        duration = payload.get('duration_seconds')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()
        self._log_event(user_id, 'face_lost', {"duration_seconds": duration}, timestamp)
        print(f"[Handler] Face lost: {user_id}")

    # 공통 로그 저장 함수
    def _log_event(self, user_id, event_type, event_data, timestamp):
        query = """
        INSERT INTO device_events (session_id, user_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.db.execute(query, (self.current_session_id, user_id, event_type, json.dumps(event_data), timestamp))

    # -------------------------
    # 통계 요청 핸들러 (핵심 변경)
    # -------------------------
    def handle_stats_request(self, payload):
        request_id = payload.get('request_id')
        stat_type = payload.get('type', 'usage') # usage, mode_usage, timer_count
        period = payload.get('period', 'day') # day, week
        
        try:
            data = {}
            if stat_type == 'usage':
                data = self._get_total_usage_stats(period)
            elif stat_type == 'mode_usage': # [변경] 모드별 사용 시간 (자연풍 포함)
                data = self._get_mode_duration_stats(period)
            elif stat_type == 'timer_count':
                data = self._get_timer_stats(period)
            elif stat_type == 'speed_dist':
                data = self._get_speed_distribution(period)
            else:
                data = {"error": "Unknown stat type"}
            
            self.mqtt.publish("ambient/stats/response", {
                "request_id": request_id,
                "type": stat_type,
                "period": period,
                "data": data,
                "timestamp": datetime.now().isoformat()
            })
            print(f"[Handler] Stats sent: {stat_type}")
            
        except Exception as e:
            print(f"[Handler] Stats error: {e}")
            self.mqtt.publish("ambient/stats/response", {"request_id": request_id, "error": str(e)})

    # --- 통계 집계 로직 (SQL) ---

    def _get_total_usage_stats(self, period):
        """전체 세션 사용 시간 (로그인 기준)"""
        # ... (기존 로직 유지)
        if period == 'day':
            query = """
            SELECT date_trunc('hour', session_start) as hour, 
                   SUM(EXTRACT(EPOCH FROM COALESCE(session_end, CURRENT_TIMESTAMP) - session_start) / 60)
            FROM user_sessions WHERE DATE(session_start) = CURRENT_DATE
            GROUP BY hour ORDER BY hour
            """
        else:
            query = """
            SELECT DATE(session_start) as date,
                   SUM(EXTRACT(EPOCH FROM COALESCE(session_end, CURRENT_TIMESTAMP) - session_start) / 60)
            FROM user_sessions WHERE session_start >= date_trunc('week', CURRENT_DATE)
            GROUP BY date ORDER BY date
            """
        self.db.execute(query)
        return [{"label": str(row[0]), "minutes": float(row[1])} for row in self.db.fetchall()]

    def _get_mode_duration_stats(self, period):
        """
        [수정됨] 모드별 사용 시간 계산 (현재 진행 중인 시간 포함)
        """
        # 1. 기간 내의 모든 모드 변경 로그를 시간순으로 가져옴
        date_filter = "DATE(timestamp) = CURRENT_DATE" if period == 'day' else "timestamp >= date_trunc('week', CURRENT_DATE)"
        
        query = f"""
        SELECT event_data->>'mode' as mode_name, timestamp
        FROM device_events
        WHERE event_type = 'mode_change' AND {date_filter}
        ORDER BY timestamp ASC
        """
        self.db.execute(query)
        events = self.db.fetchall()

        if not events:
            return []

        mode_durations = {} # { "natural_wind": 120.5, ... }
        now = datetime.now()

        for i in range(len(events)):
            current_event = events[i]
            mode = current_event['mode_name']
            start_time = current_event['timestamp']
            
            if i < len(events) - 1:
                end_time = events[i+1]['timestamp']
            else:
                end_time = now # 현재 진행중인 시간 반영

            # 시간 차이 계산 (분 단위)
            duration_minutes = (end_time - start_time).total_seconds() / 60.0
            
            if mode:
                mode_durations[mode] = mode_durations.get(mode, 0.0) + duration_minutes

        # 리스트 형태로 변환 반환
        return [{"mode": k, "minutes": round(v, 1)} for k, v in mode_durations.items()]

    def _get_timer_stats(self, period):
        """타이머 설정 횟수 및 총 시간"""
        date_filter = "DATE(timestamp) = CURRENT_DATE" if period == 'day' else "timestamp >= date_trunc('week', CURRENT_DATE)"
        query = f"""
        SELECT COUNT(*), SUM((event_data->>'duration_sec')::float) / 60
        FROM device_events
        WHERE event_type = 'timer' AND {date_filter}
        """
        self.db.execute(query)
        row = self.db.fetchone()
        return {"count": row[0], "total_minutes": round(float(row[1]), 1) if row[1] else 0}

    def _get_speed_distribution(self, period):
        """선호 풍속 분포"""
        date_filter = "DATE(timestamp) = CURRENT_DATE" if period == 'day' else "timestamp >= date_trunc('week', CURRENT_DATE)"
        query = f"""
        WITH speed_changes AS (
            SELECT timestamp, (event_data->>'speed')::INT as speed,
                   LEAD(timestamp, 1, CURRENT_TIMESTAMP) OVER (ORDER BY timestamp) as next_ts
            FROM device_events WHERE event_type = 'speed_change' AND {date_filter}
        )
        SELECT speed, SUM(EXTRACT(EPOCH FROM (next_ts - timestamp))/60)
        FROM speed_changes WHERE speed > 0 GROUP BY speed ORDER BY speed
        """
        self.db.execute(query)
        return [{"speed": row[0], "minutes": round(float(row[1]), 1)} for row in self.db.fetchall()]
    
    def _get_usage_pattern(self, period, user_id):
        # (기존 패턴 분석 코드 유지 - 필요시 사용)
        pass