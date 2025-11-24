#!/usr/bin/env python3

"""DB Service - 메인 실행 파일"""

import signal
import sys

from config import Config
from database import Database
from mqtt_client import MQTTClient
from handlers import EventHandlers

class DBService:
    def __init__(self):
        self.config = Config()
        self.db = Database(self.config)
        # 테이블 초기화
        self.db.init_tables()

        self.mqtt = MQTTClient(self.config.MQTT_BROKER, self.config.MQTT_PORT)
        self.handlers = EventHandlers(self.db, self.mqtt)

        # MQTT 메시지 핸들러 연결
        self.mqtt.message_handler = self.route_message

        print("[DB Service] Started")

    def route_message(self, topic, payload):
        """토픽별 핸들러 라우팅"""
        try:
            if topic == "ambient/user/register":
                self.handlers.handle_user_register(payload)
            elif topic == "ambient/user/select":
                self.handlers.handle_user_select(payload)
            elif topic == "ambient/user/update":
                self.handlers.handle_user_update(payload)
            elif topic == "ambient/command/speed":
                self.handlers.handle_speed_change(payload)
            elif topic == "ambient/command/angle":
                self.handlers.handle_angle_change(payload)
            elif topic == "ambient/command/mode":
                self.handlers.handle_mode_change(payload)
            elif topic == "ambient/ai/face-detected":
                self.handlers.handle_face_detected(payload)
            elif topic == "ambient/ai/face-lost":
                self.handlers.handle_face_lost(payload)
            elif topic == "ambient/stats/request":
                self.handlers.handle_stats_request(payload)
            elif topic == "ambient/session/request":
                self.handlers.handle_session_request(payload)
            else:
                print(f"[Warning] Unknown topic: {topic}")
        except Exception as e:
            print(f"[Error] Handler failed for {topic}: {e}")

    def stop(self):
        """서비스 종료"""
        print("\n[DB Service] Stopping...")
        self.mqtt.stop()
        self.db.close()
        print("[DB Service] Stopped")

def signal_handler(sig, frame):
    """Ctrl+C 처리"""
    service.stop()
    sys.exit(0)

if __name__ == '__main__':
    service = DBService()
    signal.signal(signal.SIGINT, signal_handler)
    # 메인 루프 (MQTT는 별도 스레드)
    signal.pause()
