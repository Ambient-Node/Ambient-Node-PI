
"""PostgreSQL 데이터베이스 관리 (Schema Update: fan_speed -> speed)"""

import psycopg2
import psycopg2.extras
import time
from datetime import datetime

class Database:
    def __init__(self, config):
        self.config = config
        self.conn = None
        self.cursor = None
        self.connect()

    def connect(self):
        """데이터베이스 연결"""
        while True:
            try:
                self.conn = psycopg2.connect(
                    host=self.config.DB_HOST,
                    port=self.config.DB_PORT,
                    dbname=self.config.DB_NAME,
                    user=self.config.DB_USER,
                    password=self.config.DB_PASSWORD,
                )
                self.cursor = self.conn.cursor(
                    cursor_factory=psycopg2.extras.RealDictCursor
                )
                print(f"[DB] Connected to {self.config.DB_HOST}:{self.config.DB_PORT}")
                break
            except Exception as e:
                print(f"[DB] Connection failed: {e}")
                print(f"[DB] Retrying in {self.config.RECONNECT_DELAY}s...")
                time.sleep(self.config.RECONNECT_DELAY)

    def init_tables(self):
        """필요한 테이블/인덱스 초기화"""
        
        try:
            self.execute("ALTER TABLE current_status RENAME COLUMN fan_speed TO speed")
            print("[DB] Renamed column 'fan_speed' to 'speed'")
        except Exception: pass

        try:
            self.execute("ALTER TABLE current_status RENAME COLUMN rotation_mode TO mode")
            print("[DB] Renamed column 'rotation_mode' to 'mode'")
        except Exception: pass

        try:
            self.execute("ALTER TABLE current_status DROP CONSTRAINT IF EXISTS current_status_rotation_mode_check")
        except Exception: pass

        queries = [
            # users
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(50) PRIMARY KEY,
                username VARCHAR(100) NOT NULL,
                image_path TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
            # user_sessions
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id VARCHAR(50) PRIMARY KEY,
                selected_user_ids VARCHAR(50)[],
                session_start TIMESTAMPTZ NOT NULL,
                session_end TIMESTAMPTZ,
                is_active BOOLEAN DEFAULT TRUE
            )
            """,
            # device_events
            """
            CREATE TABLE IF NOT EXISTS device_events (
                event_id BIGSERIAL PRIMARY KEY,
                session_id VARCHAR(50) REFERENCES user_sessions(session_id),
                user_id VARCHAR(50) REFERENCES users(user_id),
                event_type VARCHAR(50) NOT NULL,
                event_data JSONB NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL
            )
            """,
            # current_status (싱글톤)
            """
            CREATE TABLE IF NOT EXISTS current_status (
                id INT PRIMARY KEY DEFAULT 1,
                speed INT DEFAULT 0 CHECK (speed BETWEEN 0 AND 5),
                mode VARCHAR(50) DEFAULT 'manual_control',
                last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT single_row CHECK (id = 1)
            )
            """,
            # 초기 레코드 삽입
            """
            INSERT INTO current_status (id)
            VALUES (1)
            ON CONFLICT (id) DO NOTHING
            """,
            # 인덱스
            "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON device_events(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_events_session ON device_events(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_events_user ON device_events(user_id)",
        ]

        for q in queries:
            try:
                self.execute(q)
            except Exception as e:
                print(f"[DB] Init error: {e}")
        
        print("[DB] Tables initialized")

    def execute(self, query, params=None):
        try:
            self.cursor.execute(query, params)
            self.conn.commit()
        except Exception as e:
            print(f"[DB] Execute error: {e}")
            self.conn.rollback()
            raise

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def close(self):
        if self.cursor: self.cursor.close()
        if self.conn: self.conn.close()
        print("[DB] Connection closed")