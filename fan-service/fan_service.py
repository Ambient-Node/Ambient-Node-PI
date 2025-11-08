#!/usr/bin/env python3
"""
Hardware Container (Fan Service) - FIXED VERSION
- MQTT 메시지 수신
- 2축 GPIO 제어
- 명령 처리
"""

import json
import base64
import threading
import queue
import time
import os
import sys
import signal
from datetime import datetime
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[ERROR] paho-mqtt not installed: pip3 install paho-mqtt")
    sys.exit(1)

# GPIO 관련
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    print(f"[WARN] GPIO not available: {e}")
    GPIO_AVAILABLE = False
    GPIO = None

# Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt_broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "fan-service")

# GPIO Pin Configuration
FAN_PWM_PIN = 18
MOTOR_STEP_PIN_H = 21
MOTOR_DIR_PIN_H = 20
MOTOR_STEP_PIN_V = 23
MOTOR_DIR_PIN_V = 24

# Data paths
DATA_DIR = Path("/var/lib/ambient-node")
USERS_DIR = DATA_DIR / "users"
DATA_DIR.mkdir(parents=True, exist_ok=True)
USERS_DIR.mkdir(parents=True, exist_ok=True)

# Global state
_current_speed = 0
_current_tracking = False
_current_angle_h = 90
_current_angle_v = 90
_pwm = None
_running = True  # 🔥 추가


class FanService:
    def __init__(self):
        print("[FAN] ⚙️ Initializing Fan Service...")
        
        self.mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=MQTT_CLIENT_ID
        )
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect  # 🔥 추가
        print("[MQTT] ✅ Client initialized")
        
        # GPIO 초기화
        if GPIO_AVAILABLE:
            try:
                self.init_gpio()
            except Exception as e:
                print(f"[ERROR] GPIO init failed: {e}")
        else:
            print("[GPIO] ⚠️ Running in simulation mode")
        
        # MQTT 연결
        self.connect_mqtt()
        
        print("[FAN] 🎉 Fan Service initialization complete!")

    def init_gpio(self):
        """GPIO 핀 초기화"""
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        
        try:
            GPIO.cleanup()
        except:
            pass
        
        GPIO.setup(FAN_PWM_PIN, GPIO.OUT)
        GPIO.setup(MOTOR_STEP_PIN_H, GPIO.OUT)
        GPIO.setup(MOTOR_DIR_PIN_H, GPIO.OUT)
        GPIO.setup(MOTOR_STEP_PIN_V, GPIO.OUT)
        GPIO.setup(MOTOR_DIR_PIN_V, GPIO.OUT)
        
        global _pwm
        _pwm = GPIO.PWM(FAN_PWM_PIN, 1000)
        _pwm.start(0)
        
        print("[GPIO] ✅ Initialized")

    def connect_mqtt(self):
        """MQTT 브로커 연결"""
        max_retries = 10
        retry_delay = 3
        
        for attempt in range(max_retries):
            try:
                print(f"[MQTT] 🔄 Connecting to {MQTT_BROKER}:{MQTT_PORT} (attempt {attempt + 1}/{max_retries})...")
                self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
                self.mqtt_client.loop_start()  # 🔥 백그라운드 루프 시작
                print(f"[MQTT] ✅ Loop started")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[MQTT] ⚠️ Connection failed: {e}. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print(f"[ERROR] ❌ Failed to connect after {max_retries} attempts: {e}")
                    raise

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT 연결 성공"""
        if reason_code == 0:
            print("[MQTT] 📡 Connected successfully")
            
            # 🔥 수정: 올바른 토픽 구독
            topics = [
                "ambient/command/#",           # 모든 명령 토픽
                "ambient/ai/face-detected",
                "ambient/user/register"
            ]
            
            for topic in topics:
                result = client.subscribe(topic)
                print(f"[MQTT] 📬 Subscribed to {topic} (result: {result})")
        else:
            print(f"[MQTT] ❌ Connection failed with code: {reason_code}")

    def on_mqtt_disconnect(self, client, userdata, rc, properties=None):
        """MQTT 연결 끊김"""
        print(f"[MQTT] ⚠️ Disconnected with code: {rc}")
        if rc != 0:
            print("[MQTT] 🔄 Unexpected disconnection. Reconnecting...")

    def on_mqtt_message(self, client, userdata, msg):
        """MQTT 메시지 수신"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode('utf-8'))
            
            print(f"[MQTT] 📥 Received on {topic}: {payload}")
            
            if topic == "ambient/ai/face-detected":
                self.handle_face_detected(payload)
            elif topic.startswith("ambient/command/"):
                self.handle_mqtt_command(topic, payload)
            elif topic == "ambient/user/register":
                self.handle_user_register(payload)
        except Exception as e:
            print(f"[ERROR] MQTT message error: {e}")
            import traceback
            traceback.print_exc()

    def handle_mqtt_command(self, topic, payload):
        """MQTT 명령 처리"""
        cmd = topic.split('/')[-1]
        
        print(f"[CMD] 🎯 Processing command: {cmd}")
        
        if cmd == "speed":
            self.set_fan_speed(payload.get('level', 0))
        elif cmd == "power":
            power = payload.get('state') == 'on'
            self.set_fan_speed(100 if power else 0)
        elif cmd == "face-tracking":
            self.set_face_tracking(payload.get('enabled', False))
        elif cmd == "angle":
            direction = payload.get('direction')
            step_angle = 5
            
            global _current_angle_h, _current_angle_v
            
            if direction == 'left':
                target_h = max(0, _current_angle_h - step_angle)
                self.rotate_motor_2axis('horizontal', target_h)
            elif direction == 'right':
                target_h = min(180, _current_angle_h + step_angle)
                self.rotate_motor_2axis('horizontal', target_h)
            elif direction == 'up':
                target_v = max(0, _current_angle_v - step_angle)
                self.rotate_motor_2axis('vertical', target_v)
            elif direction == 'down':
                target_v = min(180, _current_angle_v + step_angle)
                self.rotate_motor_2axis('vertical', target_v)

    def handle_face_detected(self, payload):
        """얼굴 감지 처리"""
        angle_h = payload.get('angle_h', _current_angle_h)
        angle_v = payload.get('angle_v', _current_angle_v)
        user_id = payload.get('user_id')
        
        print(f"[FACE] 👤 User {user_id}: H={angle_h}°, V={angle_v}°")
        
        self.rotate_motor_2axis('horizontal', angle_h)
        self.rotate_motor_2axis('vertical', angle_v)

    def rotate_motor_2axis(self, axis, target_angle):
        """2축 모터 제어"""
        global _current_angle_h, _current_angle_v
        
        if not GPIO_AVAILABLE:
            print(f"[MOTOR] 🔧 Simulated {axis} → {target_angle}°")
            if axis == 'horizontal':
                _current_angle_h = target_angle
            else:
                _current_angle_v = target_angle
            return
        
        # 실제 GPIO 제어 로직 (기존과 동일)
        if axis == 'horizontal':
            current = _current_angle_h
            step_pin = MOTOR_STEP_PIN_H
            dir_pin = MOTOR_DIR_PIN_H
        elif axis == 'vertical':
            current = _current_angle_v
            step_pin = MOTOR_STEP_PIN_V
            dir_pin = MOTOR_DIR_PIN_V
        else:
            return
        
        target_angle = max(0, min(180, target_angle))
        direction = 1 if target_angle > current else 0
        GPIO.output(dir_pin, direction)
        
        steps = abs(int((target_angle - current) * 10))
        for i in range(steps):
            GPIO.output(step_pin, GPIO.HIGH)
            time.sleep(0.001)
            GPIO.output(step_pin, GPIO.LOW)
            time.sleep(0.001)
        
        if axis == 'horizontal':
            _current_angle_h = target_angle
        else:
            _current_angle_v = target_angle
        
        print(f"[MOTOR] ✅ {axis.capitalize()} → {target_angle}°")

    def set_fan_speed(self, speed):
        """팬 속도 설정"""
        global _current_speed
        
        if GPIO_AVAILABLE and _pwm:
            _pwm.ChangeDutyCycle(speed)
        
        _current_speed = speed
        power = speed > 0
        print(f"[FAN] 🌀 Speed: {speed}%, Power: {'ON' if power else 'OFF'}")
        
        self.mqtt_client.publish("ambient/fan001/status/power", json.dumps({
            "state": "on" if power else "off",
            "timestamp": datetime.now().isoformat()
        }))
        
        self.mqtt_client.publish("ambient/fan001/status/speed", json.dumps({
            "level": speed,
            "timestamp": datetime.now().isoformat()
        }))

    def set_face_tracking(self, enabled):
        """얼굴 추적 설정"""
        global _current_tracking
        _current_tracking = enabled
        
        self.mqtt_client.publish("ambient/fan001/status/face-tracking", json.dumps({
            "enabled": enabled,
            "timestamp": datetime.now().isoformat()
        }))
        
        print(f"[FACE] 👁️ Tracking: {'ON' if enabled else 'OFF'}")

    def handle_user_register(self, payload):
        """사용자 등록 처리"""
        name = payload.get('name', '')
        user_id = payload.get('user_id') or name.lower().replace(' ', '_')
        
        print(f"[USER] ✅ Register request: {name} ({user_id})")

    def cleanup(self):
        """정리 작업"""
        print("[FAN] 🧹 Cleaning up...")
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        if GPIO_AVAILABLE and _pwm:
            _pwm.stop()
            GPIO.cleanup()


def signal_handler(sig, frame):
    """종료 시그널 핸들러"""
    global _running
    print("\n[FAN] 🛑 Shutting down...")
    _running = False


if __name__ == "__main__":
    print("=" * 60)
    print("Fan Service Starting...")
    print("=" * 60)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        service = FanService()
        
        print("[INFO] 🚀 Service running... (Press Ctrl+C to stop)")
        
        # 🔥 메인 루프: 무한 대기
        while _running:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n[INFO] 👋 Interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] ❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'service' in locals():
            service.cleanup()
        print("[INFO] 🏁 Fan Service stopped")
