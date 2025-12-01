"""이벤트 핸들러 (Payload 구조 반영 업데이트)"""

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

    def handle_user_select(self, payload):
        user_list = payload.get('user_list', [])
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        if self.current_session_id:
            query = """
            UPDATE user_sessions
            SET session_end = %s, is_active = FALSE
            WHERE session_id = %s
            """
            self.db.execute(query, (timestamp, self.current_session_id))
            print(f"[Handler] Session ended: {self.current_session_id}")

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
                self.current_session_id = session_id

            self.mqtt.publish("ambient/session/active", resp, qos=1, retain=True)
        except Exception as e:
            print(f"[Handler] Failed to handle session request: {e}")

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

    def handle_speed_change(self, payload):
        speed = payload.get('speed')
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        query = """
        UPDATE current_status
        SET fan_speed = %s, last_updated = %s
        WHERE id = 1
        """
        self.db.execute(query, (speed, timestamp))

        log_query = """
        INSERT INTO device_events
        (session_id, user_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.db.execute(log_query, (
            self.current_session_id,
            user_id,
            'speed_change',
            json.dumps({"speed": speed}),
            timestamp
        ))
        print(f"[Handler] Speed changed: {speed} (user: {user_id})")

    def handle_direction_change(self, payload):
        """각도 변경"""
        direction = payload.get('direction')
        toggle_on = payload.get('toggleOn', 0)
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        log_query = """
        INSERT INTO device_events
        (session_id, user_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.db.execute(log_query, (
            self.current_session_id,
            user_id,
            'direction_change',
            json.dumps({"direction": direction, "toggleOn": toggle_on}),
            timestamp
        ))
        print(f"[Handler] Direction: {direction} (user: {user_id})")

    def handle_mode_change(self, payload):
        """모드 변경 (Type 구분 처리: motor vs wind)"""
        mode = payload.get('mode')
        cmd_type = payload.get('type', 'motor') 
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        if cmd_type == 'motor':
            query = """
            UPDATE current_status
            SET rotation_mode = %s, last_updated = %s
            WHERE id = 1
            """
            self.db.execute(query, (mode, timestamp))

        event_data = {
            "type": cmd_type,
            "mode": mode
        }
        
        log_query = """
        INSERT INTO device_events
        (session_id, user_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.db.execute(log_query, (
            self.current_session_id,
            user_id,
            'mode_change',
            json.dumps(event_data),
            timestamp
        ))
        print(f"[Handler] Mode changed: {mode} (Type: {cmd_type}, user: {user_id})")
        
    def handle_timer_set(self, payload):
        duration_sec = payload.get('duration_sec')
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        log_query = """
        INSERT INTO device_events
        (session_id, user_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.db.execute(log_query, (
            self.current_session_id,
            user_id,
            'timer',
            json.dumps({"duration_sec": duration_sec}),
            timestamp
        ))
        print(f"[Handler] Timer set: {duration_sec}s (user: {user_id})")

    def handle_face_detected(self, payload):
        """얼굴 인식"""
        session_id = payload.get('session_id')
        user_id = payload.get('user_id')
        confidence = payload.get('confidence')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        if not session_id:
            session_id = self.current_session_id

        query = """
        INSERT INTO device_events
        (session_id, user_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.db.execute(query, (
            session_id,
            user_id,
            'face_detected',
            json.dumps({"confidence": confidence}),
            timestamp
        ))

    def handle_face_lost(self, payload):
        """얼굴 추적 종료"""
        session_id = payload.get('session_id')
        user_id = payload.get('user_id')
        duration = payload.get('duration_seconds')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        if not session_id:
            session_id = self.current_session_id

        query = """
        INSERT INTO device_events
        (session_id, user_id, event_type, event_data, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.db.execute(query, (
            session_id,
            user_id,
            'face_lost',
            json.dumps({"duration_seconds": duration}),
            timestamp
        ))
        print(f"[Handler] Face lost: {user_id} (duration: {duration}s)")

    def handle_stats_request(self, payload):
        """통계 요청 처리"""
        request_id = payload.get('request_id')
        stat_type = payload.get('type', 'usage')
        period = payload.get('period', 'day')
        user_id = payload.get('user_id')
        
        try:
            if stat_type == 'usage':
                data = self._get_usage_stats(period)
            elif stat_type == 'speed_dist':
                data = self._get_speed_distribution(period)
            elif stat_type == 'mode_ratio':
                data = self._get_mode_ratio(period)
            elif stat_type == 'pattern':
                data = self._get_usage_pattern(period, user_id)
            elif stat_type == 'timer_count': 
                data = self._get_timer_stats(period)
            else:
                data = {"error": "Unknown stat type"}
            
            self.mqtt.publish("ambient/stats/response", {
                "request_id": request_id,
                "type": stat_type,
                "period": period,
                "data": data,
                "timestamp": datetime.now().isoformat()
            })
            print(f"[Handler] Stats sent: {stat_type}/{period}")
            
        except Exception as e:
            print(f"[Handler] Stats request failed: {e}")
            self.mqtt.publish("ambient/stats/response", {
                "request_id": request_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })

    # --- 통계 집계 함수들 ---

    def _get_usage_stats(self, period):
        if period == 'day':
            query = """
            SELECT date_trunc('hour', session_start) AS hour,
                   SUM(EXTRACT(EPOCH FROM COALESCE(session_end, CURRENT_TIMESTAMP) - session_start) / 60)
            FROM user_sessions WHERE DATE(session_start) = CURRENT_DATE
            GROUP BY hour ORDER BY hour
            """
        else:
            query = """
            SELECT DATE(session_start) AS date,
                   SUM(EXTRACT(EPOCH FROM COALESCE(session_end, CURRENT_TIMESTAMP) - session_start) / 60)
            FROM user_sessions WHERE session_start >= date_trunc('week', CURRENT_DATE)
            GROUP BY date ORDER BY date
            """
        self.db.execute(query)
        return [{"time": str(row[0]), "minutes": float(row[1])} for row in self.db.fetchall()]

    def _get_speed_distribution(self, period):
        date_filter = "DATE(timestamp) = CURRENT_DATE" if period == 'day' else "timestamp >= date_trunc('week', CURRENT_DATE)"
        query = f"""
        WITH speed_changes AS (
            SELECT timestamp, (event_data->>'speed')::INT AS speed,
                   LEAD(timestamp) OVER (ORDER BY timestamp) AS next_timestamp
            FROM device_events WHERE event_type = 'speed_change' AND {date_filter}
        )
        SELECT speed, SUM(EXTRACT(EPOCH FROM COALESCE(next_timestamp, CURRENT_TIMESTAMP) - timestamp) / 60)
        FROM speed_changes WHERE speed IS NOT NULL
        GROUP BY speed ORDER BY speed
        """
        self.db.execute(query)
        return [{"speed": row[0], "minutes": float(row[1])} for row in self.db.fetchall()]

    def _get_mode_ratio(self, period):
        date_filter = "DATE(timestamp) = CURRENT_DATE" if period == 'day' else "timestamp >= date_trunc('week', CURRENT_DATE)"
        query = f"""
        WITH mode_changes AS (
            SELECT timestamp, event_data->>'mode' AS mode,
                   LEAD(timestamp) OVER (ORDER BY timestamp) AS next_timestamp
            FROM device_events WHERE event_type = 'mode_change' AND {date_filter}
        )
        SELECT mode,
               SUM(EXTRACT(EPOCH FROM COALESCE(next_timestamp, CURRENT_TIMESTAMP) - timestamp) / 3600),
               ROUND(100.0 * SUM(EXTRACT(EPOCH FROM COALESCE(next_timestamp, CURRENT_TIMESTAMP) - timestamp)) / 
                     SUM(SUM(EXTRACT(EPOCH FROM COALESCE(next_timestamp, CURRENT_TIMESTAMP) - timestamp))) OVER (), 1)
        FROM mode_changes WHERE mode IS NOT NULL GROUP BY mode
        """
        self.db.execute(query)
        return [{"mode": row[0], "hours": float(row[1]), "percentage": float(row[2])} for row in self.db.fetchall()]

    def _get_usage_pattern(self, period, user_id):
        query = """
        SELECT EXTRACT(HOUR FROM session_start) AS hour_of_day, COUNT(*),
               AVG(EXTRACT(EPOCH FROM COALESCE(session_end, session_start + INTERVAL '2 hours') - session_start) / 60)
        FROM user_sessions WHERE session_start >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY hour_of_day ORDER BY 2 DESC LIMIT 3
        """
        self.db.execute(query)
        return [{"hour": int(row[0]), "count": row[1], "avg_minutes": float(row[2])} for row in self.db.fetchall()]

    def _get_timer_stats(self, period):
        date_filter = "DATE(timestamp) = CURRENT_DATE" if period == 'day' else "timestamp >= date_trunc('week', CURRENT_DATE)"
        query = f"""
        SELECT COUNT(*), SUM((event_data->>'duration_sec')::float) / 60
        FROM device_events
        WHERE event_type = 'timer' AND {date_filter}
        """
        self.db.execute(query)
        row = self.db.fetchone()
        return {"count": row[0], "total_minutes": float(row[1]) if row[1] else 0.0}