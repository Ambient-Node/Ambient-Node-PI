
"""이벤트 핸들러 (Updated: speed column)"""

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
            SELECT session_id FROM user_sessions
            WHERE is_active = TRUE ORDER BY session_start DESC LIMIT 1
            """
            self.db.execute(query)
            row = self.db.fetchone()
            if row and row.get('session_id'):
                self.current_session_id = row['session_id']
                print(f"[Handler] Restored active session: {self.current_session_id}")
            else:
                print("[Handler] No active session")
        except Exception as e:
            print(f"[Handler] Failed to load session: {e}")

    # --- 사용자/세션 핸들러 ---
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
        print(f"[Handler] User registered: {username}")
        self.mqtt.publish("ambient/user/register-ack", {"user_id": user_id, "success": True})

    def handle_user_update(self, payload):
        user_id = payload.get('user_id')
        username = payload.get('username')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()
        self.db.execute("UPDATE users SET username = %s, updated_at = %s WHERE user_id = %s", (username, timestamp, user_id))

    def handle_user_delete(self, payload):
        user_id = payload.get('user_id')
        try:
            self.db.execute("DELETE FROM device_events WHERE user_id = %s", (user_id,))
            self.db.execute("UPDATE user_sessions SET selected_user_ids = array_remove(selected_user_ids, %s) WHERE %s = ANY(selected_user_ids)", (user_id, user_id))
            self.db.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            print(f"[Handler] User deleted: {user_id}")
        except Exception as e:
            print(f"[Handler] Delete error: {e}")

    def handle_user_select(self, payload):
        user_list = payload.get('user_list', [])
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        if self.current_session_id:
            self.db.execute("UPDATE user_sessions SET session_end = %s, is_active = FALSE WHERE session_id = %s", (timestamp, self.current_session_id))

        if len(user_list) > 0:
            session_id = f"sess-{uuid.uuid4().hex[:12]}"
            user_ids = [u['user_id'] for u in user_list]
            self.db.execute("INSERT INTO user_sessions (session_id, selected_user_ids, session_start, is_active) VALUES (%s, %s, %s, TRUE)", (session_id, user_ids, timestamp))
            self.current_session_id = session_id
            print(f"[Handler] New Session: {session_id}")
            self.mqtt.publish("ambient/session/active", {"session_id": session_id, "user_list": user_list}, qos=1, retain=True)
        else:
            self.current_session_id = None
            print("[Handler] Session Ended (No users)")
            self.mqtt.publish("ambient/session/active", {"session_id": None, "user_list": []}, qos=1, retain=True)

    def handle_session_request(self, payload):
        try:
            self.db.execute("SELECT session_id, selected_user_ids FROM user_sessions WHERE is_active = TRUE ORDER BY session_start DESC LIMIT 1")
            row = self.db.fetchone()
            if row:
                user_list = [{"user_id": uid} for uid in (row.get('selected_user_ids') or [])]
                self.current_session_id = row['session_id']
                self.mqtt.publish("ambient/session/active", {"session_id": row['session_id'], "user_list": user_list}, qos=1, retain=True)
            else:
                self.mqtt.publish("ambient/session/active", {"session_id": None, "user_list": []}, qos=1, retain=True)
        except Exception: pass

    # 장치 제어 및 상태 업데이트
    def handle_speed_change(self, payload):
        speed = payload.get('speed')
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        self.db.execute("UPDATE current_status SET speed = %s, last_updated = %s WHERE id = 1", (speed, timestamp))
        self._log_event(user_id, 'speed_change', {"speed": speed}, timestamp)
        print(f"[Handler] Speed: {speed}")

    def handle_direction_change(self, payload):
        direction = payload.get('direction')
        toggle_on = payload.get('toggleOn', 0)
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()
        
        if toggle_on:
             self.db.execute("UPDATE current_status SET mode = 'manual_control', last_updated = %s WHERE id = 1", (timestamp,))

        self._log_event(user_id, 'direction_change', {"direction": direction, "toggleOn": toggle_on}, timestamp)

    def handle_mode_change(self, payload):
        mode = payload.get('mode')
        cmd_type = payload.get('type', 'motor')
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()

        self.db.execute("UPDATE current_status SET mode = %s, last_updated = %s WHERE id = 1", (mode, timestamp))

        self._log_event(user_id, 'mode_change', {"type": cmd_type, "mode": mode}, timestamp)
        print(f"[Handler] Mode Change: {mode} (Type: {cmd_type})")

    def handle_timer_set(self, payload):
        duration_sec = payload.get('duration_sec')
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()
        self._log_event(user_id, 'timer', {"duration_sec": duration_sec}, timestamp)

    def handle_face_detected(self, payload):
        user_id = payload.get('user_id')
        confidence = payload.get('confidence')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()
        self._log_event(user_id, 'face_detected', {"confidence": confidence}, timestamp)

    def handle_face_lost(self, payload):
        user_id = payload.get('user_id')
        duration = payload.get('duration_seconds')
        timestamp = payload.get('timestamp') or datetime.now().isoformat()
        self._log_event(user_id, 'face_lost', {"duration_seconds": duration}, timestamp)

    def _log_event(self, user_id, event_type, event_data, timestamp):
        query = "INSERT INTO device_events (session_id, user_id, event_type, event_data, timestamp) VALUES (%s, %s, %s, %s, %s)"
        self.db.execute(query, (self.current_session_id, user_id, event_type, json.dumps(event_data), timestamp))

    # 통계
    def handle_stats_request(self, payload):
        request_id = payload.get('request_id')
        stat_type = payload.get('type', 'usage')
        period = payload.get('period', 'day')
        
        try:
            data = {}
            if stat_type == 'usage': data = self._get_total_usage_stats(period)
            elif stat_type == 'mode_usage': data = self._get_mode_duration_stats(period)
            elif stat_type == 'timer_count': data = self._get_timer_stats(period)
            elif stat_type == 'speed_dist': data = self._get_speed_distribution(period)
            
            self.mqtt.publish("ambient/stats/response", {
                "request_id": request_id, "type": stat_type, "period": period, "data": data
            })
        except Exception as e:
            print(f"[Handler] Stats Error: {e}")
            self.mqtt.publish("ambient/stats/response", {"request_id": request_id, "error": str(e)})

    def _get_total_usage_stats(self, period):
        if period == 'day':
            query = "SELECT date_trunc('hour', session_start) as hour, SUM(EXTRACT(EPOCH FROM COALESCE(session_end, CURRENT_TIMESTAMP) - session_start) / 60) FROM user_sessions WHERE DATE(session_start) = CURRENT_DATE GROUP BY hour ORDER BY hour"
        else:
            query = "SELECT DATE(session_start) as date, SUM(EXTRACT(EPOCH FROM COALESCE(session_end, CURRENT_TIMESTAMP) - session_start) / 60) FROM user_sessions WHERE session_start >= date_trunc('week', CURRENT_DATE) GROUP BY date ORDER BY date"
        self.db.execute(query)
        return [{"label": str(row[0]), "minutes": float(row[1])} for row in self.db.fetchall()]

    def _get_mode_duration_stats(self, period):
        date_filter = "DATE(timestamp) = CURRENT_DATE" if period == 'day' else "timestamp >= date_trunc('week', CURRENT_DATE)"
        query = f"SELECT event_data->>'mode' as mode_name, timestamp FROM device_events WHERE event_type = 'mode_change' AND {date_filter} ORDER BY timestamp ASC"
        self.db.execute(query)
        events = self.db.fetchall()
        
        mode_durations = {}
        now = datetime.now()
        for i in range(len(events)):
            mode = events[i]['mode_name']
            start = events[i]['timestamp']
            end = events[i+1]['timestamp'] if i < len(events) - 1 else now
            duration = (end - start).total_seconds() / 60.0
            if mode: mode_durations[mode] = mode_durations.get(mode, 0.0) + duration
            
        return [{"mode": k, "minutes": round(v, 1)} for k, v in mode_durations.items()]

    def _get_timer_stats(self, period):
        date_filter = "DATE(timestamp) = CURRENT_DATE" if period == 'day' else "timestamp >= date_trunc('week', CURRENT_DATE)"
        query = f"SELECT COUNT(*), SUM((event_data->>'duration_sec')::float) / 60 FROM device_events WHERE event_type = 'timer' AND {date_filter}"
        self.db.execute(query)
        row = self.db.fetchone()
        return {"count": row[0], "total_minutes": round(float(row[1]), 1) if row[1] else 0}

    def _get_speed_distribution(self, period):
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