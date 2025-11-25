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
        
        self.movement_mode = "manual_control" # motor: ai_tracking, rotation, manual_control
        self.is_natural_wind = False          # wind: True(natural), False(normal)
        
        # 타이머 관리
        self.shutdown_timer = None
        self.hw = FanHardware(config, self.on_arduino_status)
        self.mqtt = FanMQTTClient(config, self.handle_mqtt_message)

        # [추가] 효과(자연풍 등) 처리를 위한 백그라운드 스레드 시작
        self.effect_running = True
        self.effect_thread = threading.Thread(target=self._effect_loop, daemon=True)
        self.effect_thread.start()
    
    def handle_mqtt_message(self, topic: str, payload: dict):
        print(f"[MQTT] 📥 {topic}: {payload}")
        
        # 1. 모드 변경 (여기서 type을 확인합니다!)
        if topic == "ambient/command/mode":
            cmd_type = payload.get("type") # 'motor' or 'wind'
            mode = payload.get("mode")
            
            # [Case A] 모터(움직임) 관련 명령
            if cmd_type == "motor":
                if self.movement_mode != mode:
                    print(f"[FAN] 🔄 Movement Change: {self.movement_mode} -> {mode}")
                    
                    # 1) 기존 움직임 정리 (Safety)
                    self.hw.send_command("A l 0") 
                    self.hw.send_command("A r 0")
                    self.hw.send_command("P X") # 트래킹 정지
                    
                    # 2) 상태 업데이트
                    self.movement_mode = mode
            
            # [Case B] 바람(풍질) 관련 명령
            elif cmd_type == "wind":
                if mode == "natural_wind":
                    self.is_natural_wind = True
                    print("[FAN] 🍃 Natural Wind ON")
                else:
                    self.is_natural_wind = False
                    print("[FAN] 🍃 Natural Wind OFF")

        # 2. 속도 제어
        elif topic == "ambient/command/speed":
            level = int(payload.get("speed", 0))
            
            # 속도를 수동으로 바꾸면 자연풍은 끄는 게 좋음
            if self.is_natural_wind:
                self.is_natural_wind = False
                print("[FAN] Speed set manually. Natural wind OFF.")
            
            self.hw.send_command(f"S {level}")
            
        # 3. 방향 제어 (수동 조작)
        elif topic == "ambient/command/direction":
            # 수동 조작 시 '움직임'은 Manual로 변경
            if self.movement_mode != "manual_control":
                print("[FAN] Manual override. Switching movement to manual.")
                self.movement_mode = "manual_control"
                
                # 기존 자동 동작 정지
                self.hw.send_command("P X")
                self.hw.send_command("A l 0")
                self.hw.send_command("A r 0")
            
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
            # 움직임 모드가 AI일 때만 작동
            if self.movement_mode == "ai_tracking":
                user_id = payload.get("user_id")
                x = payload.get("x")
                y = payload.get("y")
                if user_id and x is not None and y is not None:
                    self.tracked_positions[user_id] = (x, y)
                    self._send_positions()

        # 6. AI 얼굴 소실
        elif topic == "ambient/ai/face-lost":
            user_id = payload.get("user_id")
            if user_id in self.tracked_positions:
                del self.tracked_positions[user_id]
                if self.movement_mode == "ai_tracking":
                    self._send_positions()

    def _effect_loop(self):
        """자연풍과 자동회전을 동시에 처리하는 루프"""
        
        # 타이머 변수들
        last_wind_time = 0
        last_rotate_time = 0
        
        # 회전 상태
        rotation_dir = 'r' # r 또는 l
        
        while self.effect_running:
            try:
                now = time.time()
                
                # 1. 자연풍 처리 (is_natural_wind가 True일 때만)
                if self.is_natural_wind:
                    if now - last_wind_time > 5.0: # 5초 간격
                        new_speed = random.randint(1, 3)
                        self.hw.send_command(f"S {new_speed}")
                        last_wind_time = now
                
                # 2. 자동 회전 처리 (movement_mode가 rotation일 때만)
                if self.movement_mode == "rotation":
                    if now - last_rotate_time > 3.0: # 3초 간격
                        # 정지 -> 방향전환 -> 가동
                        self.hw.send_command(f"A {rotation_dir} 0")
                        rotation_dir = 'l' if rotation_dir == 'r' else 'r'
                        self.hw.send_command(f"A {rotation_dir} 1")
                        last_rotate_time = now
                
                time.sleep(0.1)
                    
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