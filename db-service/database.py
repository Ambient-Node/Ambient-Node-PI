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
                    password=self.config.DB_PASSWORD
                )
                self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                print(f"[DB] Connected to {self.config.DB_HOST}:{self.config.DB_PORT}")
                break
            except Exception as e:
                print(f"[DB] Connection failed: {e}")
                print(f"[DB] Retrying in {self.config.RECONNECT_DELAY}s...")
                time.sleep(self.config.RECONNECT_DELAY)
    
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
