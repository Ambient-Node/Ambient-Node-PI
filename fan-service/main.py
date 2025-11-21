#!/usr/bin/env python3
# main.py
import signal
import time
import sys
from config import Config
from hardware import FanHardware
from mqtt_client import FanMQTTClient


class FanService:
    def __init__(self, config):
        self.config = config
        self.running = True
        self.tracked_positions = {}  # {user_id: (x, y)}
        
        # Hardware 초기화 (RX 콜백 전달)
        self.hw = FanHardware(config, self.on_arduino_status)
        
        # MQTT 초기화 (메시지 핸들러 전달)
        self.mqtt = FanMQTTClient(config, self.handle_mqtt_message)
    
    def handle_mqtt_message(self, topic: str, payload: dict):
        """MQTT 메시지 처리"""
        
        if topic == "ambient/command/speed":
            # 속도 변경: UART로 전송
            speed = payload.get("speed", 0)
            self.hw.send_command(f"SPEED {speed}")
        
        elif topic == "ambient/command/angle":
            # 각도 변경: UART로 방향 전송
            direction = payload.get("direction", "center")
            self.hw.send_command(f"ANGLE {direction}")
        
        elif topic == "ambient/ai/face-position":
            # 얼굴 좌표 업데이트
            user_id = payload.get("user_id")
            x = payload.get("x")
            y = payload.get("y")
            
            if user_id and x is not None and y is not None:
                self.tracked_positions[user_id] = (x, y)
                self._send_positions()
        
        elif topic == "ambient/ai/face-lost":
            # 사용자 추적 종료
            user_id = payload.get("user_id")
            if user_id in self.tracked_positions:
                del self.tracked_positions[user_id]
                print(f"[FAN] 👋 User lost: {user_id}")
                self._send_positions()
    
    def _send_positions(self):
        """현재 추적 중인 사용자 좌표를 UART로 전송"""
        if not self.tracked_positions:
            self.hw.send_command("POSITION none")
            return
        
        positions = list(self.tracked_positions.values())
        
        if len(positions) == 1:
            # 1명: (x, y)
            x, y = positions[0]
            self.hw.send_command(f"POSITION ({x},{y})")
        
        else:
            # 2명: (x, y):(x, y)
            x1, y1 = positions[0]
            x2, y2 = positions[1]
            self.hw.send_command(f"POSITION ({x1},{y1}):({x2},{y2})")
        
    
    def on_arduino_status(self, line: str):
        """Arduino로부터 상태 수신 (RX)"""
        # 예: "STATUS speed=3"
        try:
            if line.startswith("STATUS"):
                parts = line.split()
                for part in parts[1:]:
                    if part.startswith("speed="):
                        speed = int(part.split("=")[1])
                        self.mqtt.publish_status(speed)
        except Exception as e:
            print(f"[FAN] ❌ Status parse error: {e}")
    
    def stop(self):
        """서비스 종료"""
        self.running = False
        self.hw.cleanup()
        self.mqtt.disconnect()


# 전역 변수
service = None


def signal_handler(sig, frame):
    """시그널 핸들러"""
    global service
    print("\n[FAN] Shutting down...")
    if service:
        service.stop()
    sys.exit(0)


def main():
    global service
    
    print("=" * 60)
    print("Fan Service Starting...")
    print("=" * 60)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    config = Config()
    service = FanService(config)
    
    print("[INFO] 🚀 Fan Service running...")
    try:
        while service.running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] 👋 Interrupted")
    finally:
        service.stop()
        print("[INFO] 🏁 Stopped")


if __name__ == "__main__":
    main()
