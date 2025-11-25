"""PostgreSQL 데이터베이스 관리"""

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
        
        # 1. 기존의 엄격한 제약조건(CHECK) 삭제 (이미 테이블이 생성된 경우 에러 해결용)
        try:
            self.execute("ALTER TABLE current_status DROP CONSTRAINT IF EXISTS current_status_rotation_mode_check")
            # self.conn.commit() # execute 내부에서 commit 함
            print("[DB] Removed legacy constraint 'current_status_rotation_mode_check'")
        except Exception as e:
            print(f"[DB] Note: Could not drop constraint (might not exist): {e}")

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
            # [수정] CHECK 제약조건 삭제 (모든 문자열 허용)
            """
            CREATE TABLE IF NOT EXISTS current_status (
                id INT PRIMARY KEY DEFAULT 1,
                fan_speed INT DEFAULT 0 CHECK (fan_speed BETWEEN 0 AND 5),
                rotation_mode VARCHAR(50) DEFAULT 'manual',
                last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT single_row CHECK (id = 1)
            )
            """,
            # current_status 초기 레코드
            """
            INSERT INTO current_status (id)
            VALUES (1)
            ON CONFLICT (id) DO NOTHING
            """,
            # 인덱스들
            "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON device_events(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_events_session ON device_events(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_events_user ON device_events(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_active ON user_sessions(is_active) WHERE is_active = TRUE",
            "CREATE INDEX IF NOT EXISTS idx_events_type_time ON device_events(event_type, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_events_user_time ON device_events(user_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_start ON user_sessions(session_start DESC)",
        ]

        for q in queries:
            try:
                self.execute(q)
            except Exception as e:
                print(f"[DB] Init error: {e}")

        print("[DB] ✅ Tables initialized")

    def execute(self, query, params=None):
        """쿼리 실행"""
        try:
            self.cursor.execute(query, params)
            self.conn.commit()
        except Exception as e:
            print(f"[DB] Execute error: {e}")
            self.conn.rollback()
            raise

    def fetchone(self):
        """단일 행 조회"""
        return self.cursor.fetchone()

    def fetchall(self):
        """전체 행 조회"""
        return self.cursor.fetchall()

    def close(self):
        """연결 종료"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        print("[DB] Connection closed")