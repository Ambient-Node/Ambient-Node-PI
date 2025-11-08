#!/usr/bin/env python3
"""
DB Service Container
- SQLite 데이터베이스 관리
- MQTT 구독하여 이벤트 로깅
- 통계 데이터 제공
"""

import json
import sqlite3
import threading
import paho.mqtt.client as mqtt
from datetime import datetime
from pathlib import Path
import os
import signal
import sys

# Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt_broker")  # Docker service name (use underscore)
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = "db-service"
DB_PATH = "/var/lib/ambient-node/db.sqlite"
DATA_DIR = "/var/lib/ambient-node"

# MQTT Topics to subscribe
TOPICS = [
    "ambient/db/log-event",
    "ambient/user/register",
    "ambient/user/select",
    "ambient/user/session-start",
    "ambient/user/session-end",
    "ambient/ai/face-detected",
    "ambient/status/+",  # 모든 상태 토픽
]

class DatabaseService:
    def __init__(self):
        self.db_path = DB_PATH
        self.data_dir = Path(DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # DB 초기화
        self.init_database()
        
        # MQTT 클라이언트 설정
        self.mqtt_client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        
    def init_database(self):
        """데이터베이스 및 테이블 초기화"""
        print(f"[DB] Initializing database at {self.db_path}")
        
        # DB 디렉토리 생성
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # users 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                photo_path TEXT,
                embedding_path TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # device_events 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                user_id TEXT,
                data TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # user_sessions 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_start TIMESTAMP NOT NULL,
                session_end TIMESTAMP,
                duration_seconds INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # fan_status_history 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fan_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                speed INTEGER,
                power BOOLEAN,
                face_tracking BOOLEAN,
                angle INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
        print("[DB] Database initialized successfully")
    
    def on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT 연결 성공 시 호출"""
        if rc == 0:
            print(f"[MQTT] Connected to broker at {MQTT_BROKER}:{MQTT_PORT}")
            # 모든 토픽 구독
            for topic in TOPICS:
                client.subscribe(topic)
                print(f"[MQTT] Subscribed to {topic}")
        else:
            print(f"[MQTT] Connection failed with code {rc}")
    
    def on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT 연결 해제 시 호출"""
        print(f"[MQTT] Disconnected (rc={rc})")
        if rc != 0:
            print("[MQTT] Unexpected disconnection, attempting to reconnect...")
    
    def on_mqtt_message(self, client, userdata, msg):
        """MQTT 메시지 수신 시 호출"""
        try:
            topic = msg.topic
            payload_str = msg.payload.decode('utf-8')
            payload = json.loads(payload_str)
            
            print(f"[MQTT] Received on {topic}: {payload}")
            
            # 토픽별 처리
            if topic == "ambient/db/log-event":
                self.handle_log_event(payload)
            elif topic == "ambient/user/register":
                self.handle_user_register(payload)
            elif topic == "ambient/user/select":
                self.handle_user_select(payload)
            elif topic == "ambient/user/session-start":
                self.handle_session_start(payload)
            elif topic == "ambient/user/session-end":
                self.handle_session_end(payload)
            elif topic.startswith("ambient/status/"):
                self.handle_status_update(topic, payload)
            elif topic == "ambient/ai/face-detected":
                self.handle_face_detected(payload)
            
        except json.JSONDecodeError as e:
            print(f"[ERROR] Failed to parse JSON: {e}")
        except Exception as e:
            print(f"[ERROR] Error processing message: {e}")
    
    def handle_log_event(self, payload):
        """이벤트 로깅 처리"""
        event_type = payload.get('event_type', 'unknown')
        user_id = payload.get('user_id')
        data = payload.get('data', {})
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO device_events (event_type, user_id, data)
            VALUES (?, ?, ?)
        """, (event_type, user_id, json.dumps(data)))
        
        conn.commit()
        conn.close()
        print(f"[DB] Logged event: {event_type}")
    
    def handle_user_register(self, payload):
        """사용자 등록 처리"""
        user_id = payload.get('user_id', '').lower().replace(' ', '_')
        name = payload.get('name', '')
        photo_path = payload.get('photo_path')
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 기존 사용자가 있으면 업데이트, 없으면 삽입
        cursor.execute("""
            INSERT OR REPLACE INTO users (user_id, name, photo_path, updated_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, name, photo_path, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        print(f"[DB] User registered: {user_id} ({name})")
    
    def handle_user_select(self, payload):
        """사용자 선택 처리 (선택 사항)"""
        user_id = payload.get('user_id')
        if user_id:
            self.handle_log_event({
                'event_type': 'user_selected',
                'user_id': user_id,
                'data': payload
            })
    
    def handle_session_start(self, payload):
        """사용자 세션 시작 처리"""
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO user_sessions (user_id, session_start)
            VALUES (?, ?)
        """, (user_id, timestamp))
        
        conn.commit()
        conn.close()
        print(f"[DB] Session started: {user_id}")
    
    def handle_session_end(self, payload):
        """사용자 세션 종료 처리"""
        user_id = payload.get('user_id')
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        duration = payload.get('duration', 0)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 가장 최근 세션 찾아서 종료 시간 업데이트
        cursor.execute("""
            UPDATE user_sessions
            SET session_end = ?, duration_seconds = ?
            WHERE user_id = ? AND session_end IS NULL
            ORDER BY session_start DESC
            LIMIT 1
        """, (timestamp, duration, user_id))
        
        conn.commit()
        conn.close()
        print(f"[DB] Session ended: {user_id} (duration: {duration}s)")
    
    def handle_status_update(self, topic, payload):
        """상태 업데이트 처리"""
        status_type = topic.split('/')[-1]  # power, speed, angle, face-tracking
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if status_type == "speed":
            speed = payload.get('speed', 0)
            power = speed > 0
            cursor.execute("""
                INSERT INTO fan_status_history (speed, power)
                VALUES (?, ?)
            """, (speed, power))
        elif status_type == "power":
            power = payload.get('power', False)
            cursor.execute("""
                INSERT INTO fan_status_history (power)
                VALUES (?)
            """, (power,))
        elif status_type == "angle":
            angle = payload.get('angle', 0)
            cursor.execute("""
                INSERT INTO fan_status_history (angle)
                VALUES (?)
            """, (angle,))
        elif status_type == "face-tracking":
            face_tracking = payload.get('enabled', False)
            cursor.execute("""
                INSERT INTO fan_status_history (face_tracking)
                VALUES (?)
            """, (face_tracking,))
        
        conn.commit()
        conn.close()
    
    def handle_face_detected(self, payload):
        """얼굴 감지 이벤트 처리"""
        user_id = payload.get('user_id')
        angle = payload.get('angle', 0)
        confidence = payload.get('confidence', 0.0)
        
        self.handle_log_event({
            'event_type': 'face_detected',
            'user_id': user_id,
            'data': {
                'angle': angle,
                'confidence': confidence
            }
        })
    
    def get_stats(self, request_id=None):
        """통계 데이터 조회"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 사용자 수
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        # 총 이벤트 수
        cursor.execute("SELECT COUNT(*) FROM device_events")
        event_count = cursor.fetchone()[0]
        
        # 활성 세션 수
        cursor.execute("SELECT COUNT(*) FROM user_sessions WHERE session_end IS NULL")
        active_sessions = cursor.fetchone()[0]
        
        # 최근 24시간 이벤트 수
        cursor.execute("""
            SELECT COUNT(*) FROM device_events
            WHERE timestamp > datetime('now', '-1 day')
        """)
        events_24h = cursor.fetchone()[0]
        
        stats = {
            'user_count': user_count,
            'event_count': event_count,
            'active_sessions': active_sessions,
            'events_24h': events_24h
        }
        
        conn.close()
        
        # MQTT로 응답 발행
        if request_id:
            self.mqtt_client.publish(
                "ambient/db/stats-response",
                json.dumps({
                    'request_id': request_id,
                    'stats': stats
                })
            )
        
        return stats
    
    def start(self):
        """서비스 시작"""
        print("[DB] Starting DB Service...")
        
        # 재시도 로직: MQTT 브로커가 준비될 때까지 대기
        max_retries = 10
        retry_delay = 3  # seconds
        
        for attempt in range(max_retries):
            try:
                print(f"[DB] Attempting to connect to MQTT broker (attempt {attempt + 1}/{max_retries})...")
                self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
                self.mqtt_client.loop_start()
                print(f"[DB] Successfully connected to MQTT broker!")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[DB] Connection failed: {e}. Retrying in {retry_delay} seconds...")
                    import time
                    time.sleep(retry_delay)
                else:
                    print(f"[ERROR] Failed to connect to MQTT broker after {max_retries} attempts: {e}")
                    sys.exit(1)
        
        print("[DB] DB Service started successfully")
        
        # 메인 루프
        try:
            while True:
                threading.Event().wait(1)
        except KeyboardInterrupt:
            print("\n[DB] Shutting down...")
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            print("[DB] DB Service stopped")

def main():
    service = DatabaseService()
    service.start()

if __name__ == "__main__":
    main()

