#!/usr/bin/env python3
import signal
import time
import sys
import threading
import random  # [추가] 자연풍 랜덤 제어용
from config import Config
from hardware import FanHardware
from mqtt_client import FanMQTTClient

class FanService:
    def __init__(self, config):
        self.config = config
        self.running = True
        self.tracked_positions = {}
        
        self.current_mode = "manual_control"
        
        # 타이머 관리
        self.shutdown_timer = None
        
        self.hw = FanHardware(config, self.on_arduino_status)
        self.mqtt = FanMQTTClient(config, self.handle_mqtt_message)

        # [추가] 효과(자연풍 등) 처리를 위한 백그라운드 스레드 시작
        self.effect_running = True
        self.effect_thread = threading.Thread(target=self._effect_loop, daemon=True)
        self.effect_thread.start()
    
    def handle_mqtt_message(self, topic: str, payload: dict):
        print(f"[MQTT] {topic}: {payload}")
        
        if topic == "ambient/command/mode":
            new_mode = payload.get("mode")
            
            if self.current_mode != new_mode:
                print(f"[FAN] 모드 바뀌기 전 모든 동작 정지")
                # 회전/방향 모터 정지 (좌, 우, 상, 하, 센터 모두 0)
                # 하드웨어 구현에 따라 'A c 0' 하나로 다 멈추는게 가장 좋음
                self.hw.send_command("A l 0")
                self.hw.send_command("A r 0")
                self.hw.send_command("A u 0")
                self.hw.send_command("A d 0")
                
                # AI 트래킹 정지
                self.hw.send_command("P X")

            print(f"[FAN] Mode switched: {self.current_mode} -> {new_mode}")
            self.current_mode = new_mode            
            
            # 모드 전환 시 초기화 작업
            if new_mode == "manual_control":
                # 트래킹/회전 멈춤 (필요 시 하드웨어 정지 명령 전송)
                self.hw.send_command("P X")
            elif new_mode == "ai_tracking":
                pass
            elif new_mode == "natural_wind":
                pass
            elif new_mode == "rotation":
                # 하드웨어에 자동 회전 기능이 있다면 여기서 명령 전송
                # 예: self.hw.send_command("A AUTO 1")
                pass

        # 2. 속도 제어
        elif topic == "ambient/command/speed":
            level = int(payload.get("speed", 0))
            if self.current_mode == "natural_wind":
                print("[FAN] Speed changed manually. Switching to manual_control.")
                self.current_mode = "manual_control"
            
            self.hw.send_command(f"S {level}")
            
        # 3. 방향 제어 (수동 조작)
        elif topic == "ambient/command/direction":
            # [중요] 수동으로 방향을 조작하면 무조건 Manual 모드로 전환
            if self.current_mode != "manual_control":
                print("[FAN] Manual override detected. Switching to manual_control.")
                self.current_mode = "manual_control"
            
            direction = payload.get("direction", "center") 
            toggleOn = payload.get("toggleOn", 0)
            self.hw.send_command(f"A {direction} {toggleOn}")
        
        # 4. 타이머 설정
        elif topic == "ambient/command/timer":
            try:
                duration_sec = float(payload.get("duration_sec", 0))
                print(f"[FAN] Timer request received: {duration_sec} seconds")

                if self.shutdown_timer:
                    self.shutdown_timer.cancel()
                    self.shutdown_timer = None
                    print("[FAN] Previous timer cancelled")

                if duration_sec > 0:
                    self.shutdown_timer = threading.Timer(duration_sec, self._execute_timer_shutdown)
                    self.shutdown_timer.start()
                    print(f"[FAN] Timer started. Fan will turn off in {duration_sec}s")
                else:
                    print("[FAN] Timer cancelled (duration is 0)")

            except Exception as e:
                print(f"[FAN] Timer error: {e}")
            
        # 5. AI 얼굴 좌표 수신
        elif topic == "ambient/ai/face-position":
            # AI Tracking 모드일 때만 좌표 처리
            if self.current_mode == "ai_tracking":
                user_id = payload.get("user_id")
                x = payload.get("x")
                y = payload.get("y")
                if user_id is not None and x is not None and y is not None:
                    self.tracked_positions[user_id] = (x, y)
                    self._send_positions()

        # 6. AI 얼굴 소실
        elif topic == "ambient/ai/face-lost":
            # 얼굴 소실 처리는 모드와 상관없이 DB를 위해 실행
            user_id = payload.get("user_id")
            if user_id in self.tracked_positions:
                del self.tracked_positions[user_id]
                print(f"[FAN] User lost: {user_id}")
                
                # 트래킹 모드일 때만 멈춤 명령 전송
                if self.current_mode == "ai_tracking":
                    self._send_positions()

    def _effect_loop(self):
        while self.effect_running:
            try:
                # 자연풍 3~6초마다 바람 세기 랜덤 변경
                if self.current_mode == "natural_wind":
                    new_speed = 1.5
                    self.hw.send_command(f"S {new_speed}")
                    time.sleep(0.5)
                
                # 써큘레이터 역할. 360도 도는
                elif self.current_mode == "rotation":
                    self.hw.send_command(f"R")
                    time.sleep(0.5)
                    
            except Exception as e:
                print(f"[FAN] Effect loop error: {e}")
                time.sleep(1)

    def _execute_timer_shutdown(self):
        print("[FAN] Timer finished! Sending S 0 (Turn Off)")
        self.hw.send_command("S 0")
        self.shutdown_timer = None

    def _send_positions(self):
        if not self.tracked_positions:
            self.hw.send_command("P X") 
            return
        
        positions = list(self.tracked_positions.values())
        if len(positions) == 1:
            x, y = positions[0]
            self.hw.send_command(f"P ({x},{y})")
        elif len(positions) == 2:
            x1, y1 = positions[0]
            x2, y2 = positions[1]
            self.hw.send_command(f"P ({x1},{y1}) ({x2},{y2})")
    
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
        print("[FAN] Service stopping...")
        self.running = False
        self.effect_running = False
        
        if self.shutdown_timer:
            self.shutdown_timer.cancel()
            
        self.hw.cleanup()
        self.mqtt.disconnect()
        
        if self.effect_thread.is_alive():
            self.effect_thread.join(timeout=1.0)

service = None

def signal_handler(sig, frame):
    global service
    print("\n[FAN] Shutting down...")
    if service:
        service.stop()
    sys.exit(0)

def main():
    global service
    print("="*60)
    print("Fan Service Starting...")
    print("="*60)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    config = Config()
    service = FanService(config)
    print("[INFO] Running fan service...")
    try:
        while service.running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted")
    finally:
        service.stop()
        print("[INFO] Stopped")

if __name__=="__main__":
    main()