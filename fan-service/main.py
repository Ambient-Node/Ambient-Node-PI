#!/usr/bin/env python3
import signal
import time
import sys
import threading  # [추가] 타이머를 위해 필요
from config import Config
from hardware import FanHardware
from mqtt_client import FanMQTTClient

class FanService:
    def __init__(self, config):
        self.config = config
        self.running = True
        self.tracked_positions = {}
        
        self.shutdown_timer = None
        
        self.hw = FanHardware(config, self.on_arduino_status)
        self.mqtt = FanMQTTClient(config, self.handle_mqtt_message)
    
    def handle_mqtt_message(self, topic: str, payload: dict):
        print(f"[MQTT] 📥 {topic}: {payload}")
        
        if topic == "ambient/command/speed":
            level = int(payload.get("speed", 0))
            self.hw.send_command(f"S {level}")
            
        elif topic == "ambient/command/direction":
            direction = payload.get("direction", "center") 
            toggleOn = payload.get("toggleOn", 0)
            self.hw.send_command(f"A {direction} {toggleOn}")
        
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
            
        elif topic == "ambient/ai/face-position":
            user_id = payload.get("user_id")
            x = payload.get("x")
            y = payload.get("y")
            if user_id is not None and x is not None and y is not None:
                self.tracked_positions[user_id] = (x, y)
                self._send_positions()

        elif topic == "ambient/ai/face-lost":
            user_id = payload.get("user_id")
            if user_id in self.tracked_positions:
                del self.tracked_positions[user_id]
                print(f"[FAN] User lost: {user_id}")
                self._send_positions()
    
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
        self.running = False
        if self.shutdown_timer:
            self.shutdown_timer.cancel()
            
        self.hw.cleanup()
        self.mqtt.disconnect()

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