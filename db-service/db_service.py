import json
import time
import psycopg2
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt

# ============================================
# DB Service - MQTT 구독 및 이벤트 처리
# ============================================

class DBService:
    def __init__(self, mqtt_broker, db_config):
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        
        # PostgreSQL 연결
        self.conn = psycopg2.connect(**db_config)
        self.cursor = self.conn.cursor()
        
        # MQTT 연결
        self.mqtt_client.connect(mqtt_broker, 1883, 60)
        self.mqtt_client.loop_start()
        
        # 현재 활성 세션 추적
        self.active_sessions = {}
    
    def on_connect(self, client, userdata, flags, rc):
        """MQTT 연결 시 토픽 구독"""
        print(f"[DB Service] Connected with result code {rc}")
        
        # 구독할 토픽들
        topics = [
            "ambient/db/log-event",
            "ambient/db/stats-request",
            "ambient/user/select",
            "ambient/user/deselect",
            "ambient/status/speed"
        ]
        
        for topic in topics:
            client.subscribe(topic)
            print(f"[DB Service] Subscribed to {topic}")
    
    def on_message(self, client, userdata, msg):
        """MQTT 메시지 수신 처리"""
        topic = msg.topic
        payload = json.loads(msg.payload.decode())
        
        print(f"[DB Service] Received: {topic} -> {payload}")
        
        # 토픽별 라우팅
        if topic == "ambient/user/select":
            self.handle_session_start(payload)
        
        elif topic == "ambient/user/deselect":
            self.handle_session_end(payload)
        
        elif topic == "ambient/status/speed":
            self.handle_speed_change(payload)
        
        elif topic == "ambient/db/log-event":
            self.handle_log_event(payload)
        
        elif topic == "ambient/db/stats-request":
            self.handle_stats_request(payload)
    
    # ========================================
    # 세션 관리
    # ========================================
    
    def handle_session_start(self, payload):
        """사용자 선택 시 세션 시작"""
        user_list = payload.get('users', [])
        device_id = payload.get('device_id', 'device_001')
        timestamp = payload.get('timestamp')
        
        if len(user_list) == 0:
            print("[WARN] Empty user list")
            return
        
        primary_user = user_list[0] if len(user_list) > 0 else None
        secondary_user = user_list[1] if len(user_list) > 1 else None
        
        # 세션 생성
        query = """
        INSERT INTO user_sessions 
            (device_id, primary_user_id, secondary_user_id, session_start, is_active)
        VALUES (%s, %s, %s, %s, TRUE)
        RETURNING session_id
        """
        
        self.cursor.execute(query, (device_id, primary_user, secondary_user, timestamp))
        session_id = self.cursor.fetchone()[0]
        self.conn.commit()
        
        self.active_sessions[device_id] = session_id
        print(f"[DB] Session started: {session_id}")
    
    def handle_session_end(self, payload):
        """사용자 선택 해제 시 세션 종료"""
        device_id = payload.get('device_id', 'device_001')
        timestamp = payload.get('timestamp')
        
        session_id = self.active_sessions.get(device_id)
        if not session_id:
            print("[WARN] No active session")
            return
        
        # 세션 종료
        query = """
        UPDATE user_sessions 
        SET session_end = %s, is_active = FALSE
        WHERE session_id = %s
        """
        
        self.cursor.execute(query, (timestamp, session_id))
        self.conn.commit()
        
        # 통계 집계
        self.aggregate_session_stats(session_id)
        
        del self.active_sessions[device_id]
        print(f"[DB] Session ended: {session_id}")
    
    # ========================================
    # 제어 이벤트 처리
    # ========================================
    
    def handle_speed_change(self, payload):
        """풍속 변경 이벤트"""
        session_id = self.get_active_session(payload.get('device_id'))
        if not session_id:
            return
        
        speed_level = payload.get('speed', 1)
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp')
        
        # control_events에 INSERT
        query = """
        INSERT INTO control_events 
            (session_id, user_id, event_type, speed_level, timestamp)
        VALUES (%s, %s, 'speed_change', %s, %s)
        """
        
        self.cursor.execute(query, (session_id, user_id, speed_level, timestamp))
        self.conn.commit()
        
        # usage_statistics 증분 업데이트
        self.update_usage_stats_speed(session_id, user_id, speed_level, timestamp)
        
        print(f"[DB] Speed changed to {speed_level}")
    
    def handle_log_event(self, payload):
        """범용 로그 이벤트 처리"""
        event_type = payload.get('event_type')
        
        if event_type == 'manual_override_start':
            self.handle_manual_override_start(payload)
        
        elif event_type == 'manual_override_end':
            self.handle_manual_override_end(payload)
        
        elif event_type == 'face_tracking_start':
            self.handle_face_tracking_start(payload)
        
        elif event_type == 'face_tracking_end':
            self.handle_face_tracking_end(payload)
        
        elif event_type == 'face_tracking_resume':
            self.handle_face_tracking_resume(payload)
        
        elif event_type == 'face_lost':
            self.handle_face_lost(payload)
    
    # ========================================
    # 수동 조작 우선순위
    # ========================================
    
    def handle_manual_override_start(self, payload):
        """수동 조작 시작 (얼굴 추적 중단)"""
        session_id = payload.get('session_id')
        user_id = payload.get('user_id')
        interrupted_event_id = payload.get('interrupted_tracking_event_id')
        rotation_angle = payload.get('rotation_angle')
        timestamp = payload.get('timestamp')
        
        # manual_override_events에 INSERT
        query = """
        INSERT INTO manual_override_events 
            (session_id, user_id, interrupted_tracking_event_id, 
             override_start, rotation_angle)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING override_id
        """
        
        self.cursor.execute(query, (session_id, user_id, interrupted_event_id, 
                                    timestamp, rotation_angle))
        override_id = self.cursor.fetchone()[0]
        self.conn.commit()
        
        # face_tracking_events pause_count 증가
        if interrupted_event_id:
            self.cursor.execute("""
                UPDATE face_tracking_events 
                SET pause_count = pause_count + 1
                WHERE event_id = %s
            """, (interrupted_event_id,))
            self.conn.commit()
        
        print(f"[DB] Manual override started: {override_id}")
    
    def handle_manual_override_end(self, payload):
        """수동 조작 종료 (얼굴 추적 재개)"""
        override_id = payload.get('override_id')
        duration = payload.get('duration_seconds')
        timestamp = payload.get('timestamp')
        
        # manual_override_events 업데이트
        query = """
        UPDATE manual_override_events 
        SET override_end = %s, duration_seconds = %s
        WHERE override_id = %s
        RETURNING interrupted_tracking_event_id
        """
        
        self.cursor.execute(query, (timestamp, duration, override_id))
        result = self.cursor.fetchone()
        self.conn.commit()
        
        # face_tracking_events paused_duration 누적
        if result:
            interrupted_event_id = result[0]
            self.cursor.execute("""
                UPDATE face_tracking_events 
                SET paused_duration_seconds = paused_duration_seconds + %s
                WHERE event_id = %s
            """, (duration, interrupted_event_id))
            self.conn.commit()
        
        print(f"[DB] Manual override ended: {override_id}")
    
    # ========================================
    # 얼굴 추적 이벤트
    # ========================================
    
    def handle_face_tracking_start(self, payload):
        """얼굴 추적 시작"""
        session_id = payload.get('session_id')
        user_id = payload.get('user_id')
        position_x = payload.get('face_position_x')
        position_y = payload.get('face_position_y')
        timestamp = payload.get('timestamp')
        
        query = """
        INSERT INTO face_tracking_events 
            (session_id, user_id, tracking_start, face_position_x, face_position_y)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING event_id
        """
        
        self.cursor.execute(query, (session_id, user_id, timestamp, 
                                    position_x, position_y))
        event_id = self.cursor.fetchone()[0]
        self.conn.commit()
        
        print(f"[DB] Face tracking started: {event_id} for user {user_id}")
    
    def handle_face_tracking_end(self, payload):
        """얼굴 추적 종료"""
        event_id = payload.get('event_id')
        end_reason = payload.get('end_reason', 'switched_user')
        timestamp = payload.get('timestamp')
        
        query = """
        UPDATE face_tracking_events 
        SET tracking_end = %s,
            duration_seconds = EXTRACT(EPOCH FROM (%s - tracking_start)),
            end_reason = %s
        WHERE event_id = %s
        """
        
        self.cursor.execute(query, (timestamp, timestamp, end_reason, event_id))
        self.conn.commit()
        
        print(f"[DB] Face tracking ended: {event_id}")
    
    def handle_face_tracking_resume(self, payload):
        """얼굴 추적 재개 (로그만 남김)"""
        event_id = payload.get('event_id')
        print(f"[DB] Face tracking resumed: {event_id}")
    
    def handle_face_lost(self, payload):
        """얼굴 인식 실패"""
        event_id = payload.get('event_id')
        timestamp = payload.get('timestamp')
        
        query = """
        UPDATE face_tracking_events 
        SET tracking_end = %s,
            duration_seconds = EXTRACT(EPOCH FROM (%s - tracking_start)),
            end_reason = 'face_lost'
        WHERE event_id = %s
        """
        
        self.cursor.execute(query, (timestamp, timestamp, event_id))
        self.conn.commit()
        
        print(f"[DB] Face lost: {event_id}")
    
    # ========================================
    # 통계 집계
    # ========================================
    
    def update_usage_stats_speed(self, session_id, user_id, speed_level, timestamp):
        """풍속별 사용 횟수 증분 업데이트"""
        date = datetime.fromisoformat(timestamp).date()
        
        query = f"""
        INSERT INTO usage_statistics 
            (session_id, user_id, date, speed_{speed_level}_count, last_updated)
        VALUES (%s, %s, %s, 1, NOW())
        ON CONFLICT (session_id, user_id, date)
        DO UPDATE SET
            speed_{speed_level}_count = usage_statistics.speed_{speed_level}_count + 1,
            last_updated = NOW()
        """
        
        self.cursor.execute(query, (session_id, user_id, date))
        self.conn.commit()
    
    def aggregate_session_stats(self, session_id):
        """세션 종료 시 전체 통계 집계"""
        # 세션 정보 조회
        self.cursor.execute("""
            SELECT session_start, session_end, primary_user_id, secondary_user_id
            FROM user_sessions WHERE session_id = %s
        """, (session_id,))
        
        session = self.cursor.fetchone()
        if not session:
            return
        
        start, end, primary_user, secondary_user = session
        runtime_minutes = int((end - start).total_seconds() / 60)
        date = start.date()
        
        # 각 사용자별로 통계 집계
        for user_id in [primary_user, secondary_user]:
            if not user_id:
                continue
            
            # 얼굴 추적 통계
            self.cursor.execute("""
                SELECT 
                    COUNT(*) as visit_count,
                    SUM(duration_seconds - COALESCE(paused_duration_seconds, 0)) as active_time,
                    SUM(COALESCE(paused_duration_seconds, 0)) as paused_time,
                    SUM(pause_count) as pause_count
                FROM face_tracking_events
                WHERE session_id = %s AND user_id = %s
            """, (session_id, user_id))
            
            tracking_stats = self.cursor.fetchone()
            
            # 수동 조작 통계
            self.cursor.execute("""
                SELECT 
                    COUNT(*) as override_count,
                    SUM(duration_seconds) as override_duration
                FROM manual_override_events
                WHERE session_id = %s AND user_id = %s
            """, (session_id, user_id))
            
            override_stats = self.cursor.fetchone()
            
            # usage_statistics 업데이트
            query = """
            INSERT INTO usage_statistics 
                (session_id, user_id, date, total_runtime_minutes,
                 face_tracking_visit_count, face_tracking_active_seconds,
                 face_tracking_paused_seconds, face_tracking_pause_count,
                 manual_override_count, manual_control_duration_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id, user_id, date)
            DO UPDATE SET
                total_runtime_minutes = %s,
                face_tracking_visit_count = %s,
                face_tracking_active_seconds = %s,
                face_tracking_paused_seconds = %s,
                face_tracking_pause_count = %s,
                manual_override_count = %s,
                manual_control_duration_seconds = %s,
                last_updated = NOW()
            """
            
            visit_count = tracking_stats[0] or 0
            active_time = int(tracking_stats[1] or 0)
            paused_time = int(tracking_stats[2] or 0)
            pause_count = tracking_stats[3] or 0
            override_count = override_stats[0] or 0
            override_duration = int(override_stats[1] or 0)
            
            self.cursor.execute(query, (
                session_id, user_id, date, runtime_minutes,
                visit_count, active_time, paused_time, pause_count,
                override_count, override_duration,
                # ON CONFLICT 업데이트용
                runtime_minutes, visit_count, active_time, paused_time,
                pause_count, override_count, override_duration
            ))
            
            self.conn.commit()
        
        print(f"[DB] Session statistics aggregated: {session_id}")
    
    # ========================================
    # 통계 조회
    # ========================================
    
    def handle_stats_request(self, payload):
        """차트용 통계 데이터 조회"""
        user_id = payload.get('user_id')
        start_date = payload.get('start_date')
        end_date = payload.get('end_date')
        
        # 일일 통계 조회
        query = """
        SELECT 
            date,
            SUM(total_runtime_minutes) as daily_runtime,
            SUM(speed_1_count) as speed_1_total,
            SUM(speed_2_count) as speed_2_total,
            SUM(speed_3_count) as speed_3_total,
            SUM(face_tracking_active_seconds) as tracking_time,
            SUM(manual_control_duration_seconds) as manual_time,
            SUM(manual_override_count) as manual_count,
            SUM(face_tracking_visit_count) as tracking_visits
        FROM usage_statistics
        WHERE user_id = %s AND date BETWEEN %s AND %s
        GROUP BY date
        ORDER BY date
        """
        
        self.cursor.execute(query, (user_id, start_date, end_date))
        results = self.cursor.fetchall()
        
        # JSON 변환
        stats = []
        for row in results:
            stats.append({
                'date': row[0].isoformat(),
                'daily_runtime': row[1],
                'speed_1_count': row[2],
                'speed_2_count': row[3],
                'speed_3_count': row[4],
                'tracking_time': row[5],
                'manual_time': row[6],
                'manual_count': row[7],
                'tracking_visits': row[8]
            })
        
        # MQTT로 응답
        self.mqtt_client.publish("ambient/db/stats-response", json.dumps(stats))
        print(f"[DB] Stats sent for user {user_id}")
    
    def get_active_session(self, device_id):
        """활성 세션 ID 조회"""
        return self.active_sessions.get(device_id)
    
    def run(self):
        """서비스 실행"""
        print("[DB Service] Running...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[DB Service] Shutting down...")
            self.cursor.close()
            self.conn.close()
            self.mqtt_client.loop_stop()


# ============================================
# 실행
# ============================================
if __name__ == "__main__":
    db_config = {
        'host': 'localhost',
        'database': 'ambient_node',
        'user': 'postgres',
        'password': 'your_password'
    }
    
    service = DBService(mqtt_broker='localhost', db_config=db_config)
    service.run()
