#!/usr/bin/env python3
import signal
import time
import sys
import threading
from config import Config
from hardware import FanHardware
from mqtt_client import FanMQTTClient

class FanService:
    def __init__(self, config):
        self.config = config
        self.running = True
        self.tracked_positions = {}
        self.last_sent_positions = {}
        
        # 상태 변수 (서로 독립적)
        self.movement_mode = "manual_control" # 오직 motor type에 의해서만 변경됨
        self.is_natural_wind = False          # 오직 wind type에 의해서만 변경됨
        
        self.shutdown_timer = None
        self.hw = FanHardware(config, self.on_arduino_status)
        self.mqtt = FanMQTTClient(config, self.handle_mqtt_message)
    
    def handle_mqtt_message(self, topic: str, payload: dict):
        print(f"[MQTT] 📥 {topic}: {payload}")
        
        if topic == "ambient/command/mode":
            cmd_type = payload.get("type", "motor") 
            mode = payload.get("mode")
            
            # [CASE 1] 모터 움직임 제어 (회전, 트래킹)
            if cmd_type == "motor":
                # 모터 모드가 실제로 바뀔 때만 동작
                if self.movement_mode != mode:
                    print(f"[FAN] 🔄 Movement Change: {self.movement_mode} -> {mode}")
                    self.movement_mode = mode # 상태 업데이트
                    
                    if mode == "rotation":
                        self.hw.send_command("P X") # 트래킹 끄고
                        self.hw.send_command("R 1") # 회전 켜기
                    elif mode == "ai_tracking":
                        self.hw.send_command("R 0") # 회전 끄고
                        self.last_sent_positions.clear() # 트래킹 준비
                    elif mode == "manual_control":
                        self.hw.send_command("R 0")
                        self.hw.send_command("P X")
            
            # [CASE 2] 바람 제어 (자연풍) -> 모터 상태(self.movement_mode)는 건드리지 않음!
            elif cmd_type == "wind":
                if mode == "natural_wind":
                    self.hw.send_command("N 1")
                    self.is_natural_wind = True
                    print("[FAN] 🍃 Natural Wind ON")
                    
                    # [하드웨어 보정] 자연풍 켤 때 모터가 멈추는 하드웨어 이슈 방지용 (상태 재전송)
                    if self.movement_mode == "ai_tracking":
                        self.hw.send_command("R 0") # 트래킹 모드 유지 신호
                    elif self.movement_mode == "rotation":
                        self.hw.send_command("R 1") # 회전 모드 유지 신호

                elif mode == "normal_wind":
                    self.hw.send_command("N 0")
                    self.is_natural_wind = False
                    print("[FAN] 🍃 Natural Wind OFF")
                    # 속도 복구는 앱에서 별도로 speed_change를 보내주므로 여기선 신경 안 씀

        elif topic == "ambient/command/speed":
            level = int(payload.get("speed", 0))
            self.hw.send_command(f"S {level}")
            
        elif topic == "ambient/command/direction":
            # 방향 조작 시에는 매뉴얼 모드로 변경하는 것이 안전함
            if self.movement_mode != "manual_control":
                self.movement_mode = "manual_control"
                self.hw.send_command("R 0")
                self.hw.send_command("P X")
            
            direction = payload.get("direction", "center")
            toggleOn = payload.get("toggleOn", 0)
            self.hw.send_command(f"A {direction} {toggleOn}")
        
        elif topic == "ambient/command/timer":
            self._handle_timer(payload)
            
        elif topic == "ambient/ai/face-position":
            # [중요] AI 트래킹 모드일 때만 좌표 명령 수행
            if self.movement_mode == "ai_tracking":
                user_id = payload.get("user_id")
                x = payload.get("x")
                y = payload.get("y")
                if user_id and x is not None and y is not None:
                    if (
                        user_id not in self.last_sent_positions or
                        self.last_sent_positions[user_id] != (x, y)
                    ):
                        self.hw.send_command(f"P ({x},{y})")
                        self.last_sent_positions[user_id] = (x, y)

        elif topic == "ambient/ai/face-lost":
            user_id = payload.get("user_id")
            if user_id in self.last_sent_positions:
                del self.last_sent_positions[user_id]

    def _handle_timer(self, payload):
        try:
            duration_sec = float(payload.get("duration_sec", 0))
            if self.shutdown_timer:
                self.shutdown_timer.cancel()
                self.shutdown_timer = None
            if duration_sec > 0:
                self.shutdown_timer = threading.Timer(duration_sec, self._execute_timer_shutdown)
                self.shutdown_timer.start()
                print(f"[FAN] Timer started: {duration_sec}s")
            else:
                print("[FAN] Timer cancelled")
        except Exception as e:
            print(f"[FAN] Timer error: {e}")

    def _execute_timer_shutdown(self):
        print("[FAN] ⏰ Timer finished!")
        self.hw.send_command("S 0")
        self.hw.send_command("N 0")
        self.hw.send_command("R 0")
        self.hw.send_command("P X")
        self.hw.send_command("A l 0")
        self.hw.send_command("A r 0")

        self.is_natural_wind = False
        self.movement_mode = "manual_control"
        self.shutdown_timer = None

    def on_arduino_status(self, line: str):
        if line.startswith("STATUS"):
            parts = line.split()
            for part in parts[1:]:
                if part.startswith("speed="):
                    try:
                        speed = int(part.split('=')[1])
                        self.mqtt.publish_status(speed)
                    except:
                        pass
    
    def stop(self):
        self.running = False
        if self.shutdown_timer:
            self.shutdown_timer.cancel()
        self.hw.cleanup()
        self.mqtt.disconnect()

def signal_handler(sig, frame):
    if service: service.stop()
    sys.exit(0)

service = None
def main():
    global service
    print("Fan Service Starting...")
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    config = Config()
    service = FanService(config)
    try:
        while service.running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()

if __name__=="__main__":
    main()