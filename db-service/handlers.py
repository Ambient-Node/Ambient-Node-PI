"""이벤트 핸들러"""

import json
import uuid
from datetime import datetime

class EventHandlers:
    def __init__(self, db, mqtt_client):
        self.db = db
        self.mqtt = mqtt_client
        self.current_session_id = None

        # 서비스 재시작 시 활성 세션 복구
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

    def handle_user_register(self, payload):
        """사용자 등록"""
        user_id = payload.get('user_id')
        username = payload.get('username')
        image_path = payload.get('image_path')
        timestamp = payload.get('timestamp')

        query = """
        INSERT INTO users (user_id, username, image_path, created_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE
        SET username = EXCLUDED.username, updated_at = CURRENT_TIMESTAMP
        """
        self.db.execute(query, (user_id, username, image_path, timestamp))
        print(f"[Handler] User registered: {username} ({user_id})")

        # ACK 전송
        self.mqtt.publish("ambient/user/register-ack", {
            "user_id": user_id,
            "success": True,
            "timestamp": datetime.now().isoformat()
        })

    def handle_user_select(self, payload):
        """사용자 선택 - 세션 생성"""
        user_list = payload.get('user_list', [])
        timestamp = payload.get('timestamp')

        # 1. 기존 세션 종료
        if self.current_session_id:
            query = """
            UPDATE user_sessions
            SET session_end = %s, is_active = FALSE
            WHERE session_id = %s
            """
            self.db.execute(query, (timestamp, self.current_session_id))
            print(f"[Handler] Session ended: {self.current_session_id}")

        # 2. 새 세션 생성
        if len(user_list) > 0:
            session_id = f"sess-{uuid.uuid4().hex[:12]}"
            user_ids = [u['user_id'] for u in user_list]

            query = """
            INSERT INTO user_sessions
            (session_id, selected_user_ids, session_start, is_active)
            VALUES (%s, %s, %s, TRUE)
            """
            self.db.execute(query, (session_id, user_ids, timestamp))

            self.current_session_id = session_id
            print(f"[Handler] Session created: {session_id}")
            print(f"[Handler] Users: {user_ids}")

            # AI / BLE Gateway에 브로드캐스트 (Retain)
            self.mqtt.publish("ambient/session/active", {
                "session_id": session_id,
                "user_list": user_list,
                "timestamp": timestamp
            }, qos=1, retain=True)

        else:
            # 전체 해제
            self.current_session_id = None
            print("[Handler] All users deselected")

            self.mqtt.publish("ambient/session/active", {
                "session_id": None,
                "user_list": [],
                "timestamp": timestamp
            }, qos=1, retain=True)

    def handle_session_request(self, payload):
        """현재 활성 세션 정보 요청 처리 (AI가 재시작했을 때 등)"""
        try:
            query = """
            SELECT session_id, selected_user_ids, session_start
            FROM user_sessions
            WHERE is_active = TRUE
            ORDER BY session_start DESC
            LIMIT 1
            """
            self.db.execute(query)
            row = self.db.fetchone()

            if not row:
                resp = {
                    "session_id": None,
                    "user_list": [],
                    "timestamp": datetime.now().isoformat()
                }
            else:
                session_id = row['session_id']
                user_ids = row.get('selected_user_ids') or []
                user_list = [{"user_id": uid} for uid in user_ids]
                resp = {
                    "session_id": session_id,
                    "user_list": user_list,
                    "timestamp": datetime.now().isoformat()
                }
                # 내부 current_session_id도 동기화
                self.current_session_id = session_id

            # 기존과 동일한 형식으로 응답
            self.mqtt.publish("ambient/session/active", resp, qos=1, retain=True)
            print(f"[Handler] Session request handled: {resp['session_id']}")
        except Exception as e:
            print(f"[Handler] Failed to handle session request: {e}")

    def handle_user_update(self, payload):
        """사용자 정보 수정"""
        user_id = payload.get('user_id')
        username = payload.get('username')
        timestamp = payload.get('timestamp')

        query = """
        UPDATE users
        SET username = %s, updated_at = %s
        WHERE user_id = %s
        """
        self.db.execute(query, (username, timestamp, user_id))
        print(f"[Handler] User updated: {user_id} -> {username}")

    def handle_speed_change(self, payload):
        """풍속 변경"""
        speed = payload.get('speed')
        timestamp = payload.get('timestamp')

        # 1. current_status 업데이트
        query = """
        UPDATE current_status
        SET fan_speed = %s, last_updated = %s
        WHERE id = 1
        """
        self.db.execute(query, (speed, timestamp))

        # 2. device_events 로그
        log_query = """
        INSERT INTO device_events
        (session_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s)
        """
        self.db.execute(log_query, (
            self.current_session_id,
            'speed_change',
            json.dumps({"speed": speed}),
            timestamp
        ))
        print(f"[Handler] Speed changed: {speed}")

    def handle_angle_change(self, payload):
        """각도 변경"""
        direction = payload.get('direction')
        timestamp = payload.get('timestamp')

        log_query = """
        INSERT INTO device_events
        (session_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s)
        """
        self.db.execute(log_query, (
            self.current_session_id,
            'angle_change',
            json.dumps({"direction": direction}),
            timestamp
        ))
        print(f"[Handler] Angle changed: {direction}")

    def handle_mode_change(self, payload):
        """모드 변경"""
        mode = payload.get('mode')
        timestamp = payload.get('timestamp')

        # current_status 업데이트
        query = """
        UPDATE current_status
        SET rotation_mode = %s, last_updated = %s
        WHERE id = 1
        """
        self.db.execute(query, (mode, timestamp))

        # 로그
        log_query = """
        INSERT INTO device_events
        (session_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s)
        """
        self.db.execute(log_query, (
            self.current_session_id,
            'mode_change',
            json.dumps({"mode": mode}),
            timestamp
        ))
        print(f"[Handler] Mode changed: {mode}")

    def handle_face_detected(self, payload):
        """얼굴 인식"""
        session_id = payload.get('session_id')
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp')

        query = """
        INSERT INTO device_events
        (session_id, user_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.db.execute(query, (
            session_id,
            user_id,
            'face_detected',
            json.dumps(payload),
            timestamp
        ))
        print(f"[Handler] Face detected: {user_id}")

    def handle_face_position(self, payload):
        """얼굴 좌표 추적 (현재는 저장 안 함)"""
        # 10Hz로 너무 많으므로 저장 안 함 (또는 후에 샘플링 저장 구현)
        pass

    def handle_face_lost(self, payload):
        """얼굴 추적 종료"""
        session_id = payload.get('session_id')
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp')

        query = """
        INSERT INTO device_events
        (session_id, user_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.db.execute(query, (
            session_id,
            user_id,
            'face_lost',
            json.dumps(payload),
            timestamp
        ))
        print(f"[Handler] Face lost: {user_id}")

    def handle_stats_request(self, payload):
        """통계 요청"""
        stat_type = payload.get('type', 'usage')
        period = payload.get('period', 'day')

        if stat_type == 'usage' and period == 'day':
            query = """
            SELECT
                date_trunc('hour', session_start) AS hour,
                SUM(
                    EXTRACT(EPOCH FROM
                        COALESCE(session_end, CURRENT_TIMESTAMP) - session_start
                    ) / 60
                ) AS usage_minutes
            FROM user_sessions
            WHERE DATE(session_start) = CURRENT_DATE
            GROUP BY hour
            ORDER BY hour
            """
            self.db.execute(query)
            results = self.db.fetchall()

            data = []
            for row in results:
                minutes = row['usage_minutes']
                if minutes is not None:
                    minutes = float(minutes)
                data.append({
                    "hour": str(row['hour']),
                    "minutes": minutes,
                })

            self.mqtt.publish("ambient/stats/response", {
                "type": "usage",
                "period": "day",
                "data": data,
                "timestamp": datetime.now().isoformat()
            })
            print(f"[Handler] Stats sent: {len(data)} records")
