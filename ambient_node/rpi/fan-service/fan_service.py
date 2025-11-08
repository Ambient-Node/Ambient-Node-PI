#!/usr/bin/env python3

"""
Hardware Container (Fan Service) - FIXED VERSION
- BLE 데이터 수신
- 2축 GPIO 제어 (팬 속도, 수평/수직 모터 회전)
- MQTT 메시지 발행 및 구독
- 명령 큐 기반 처리
"""

import json
import base64
import threading
import queue
import time
import paho.mqtt.client as mqtt
from datetime import datetime
from pathlib import Path
import os
import sys
import signal

# BLE는 호스트의 ble_gateway.py에서 처리

# GPIO 관련
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    print(f"[WARN] GPIO not available: {e}")
    GPIO_AVAILABLE = False
    GPIO = None

# Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt-broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "fan-service")

# BLE는 호스트의 ble_gateway.py에서 처리

# GPIO Pin Configuration (2축 모터)
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


class FanService:
    def __init__(self):
        print("[FAN] ⚙️ Initializing Fan Service...")
        
        # MQTT 클라이언트 초기화 (최신 API)
        try:
            self.mqtt_client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=MQTT_CLIENT_ID
            )
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            print("[MQTT] ✅ Client initialized (CallbackAPIVersion.VERSION2)")
        except Exception as e:
            print(f"[ERROR] MQTT client init failed: {e}")
            raise
        
        # 명령 큐
        self.command_queue = queue.Queue()
        self.command_thread = threading.Thread(
            target=self.process_commands,
            daemon=True,
            name="CommandProcessor"
        )
        self.command_thread.start()
        print("[QUEUE] ✅ Command queue started")
        
        # GPIO 초기화
        if GPIO_AVAILABLE:
            try:
                self.init_gpio()
            except Exception as e:
                print(f"[ERROR] GPIO init failed: {e}")
        else:
            print("[GPIO] ⚠️ Running in simulation mode")
        
        # MQTT 연결
        try:
            self.connect_mqtt()
        except Exception as e:
            print(f"[ERROR] MQTT connection failed: {e}")
        
        print("[FAN] 🎉 Fan Service initialization complete (MQTT-only mode)!")

    def init_gpio(self):
        """GPIO 핀 초기화"""
        GPIO.setwarnings(False)  # 경고 끄기
        GPIO.setmode(GPIO.BCM)
        
        # 기존 설정 정리
        try:
            GPIO.cleanup()
        except:
            pass
        
        # 핀 설정
        GPIO.setup(FAN_PWM_PIN, GPIO.OUT)
        GPIO.setup(MOTOR_STEP_PIN_H, GPIO.OUT)
        GPIO.setup(MOTOR_DIR_PIN_H, GPIO.OUT)
        GPIO.setup(MOTOR_STEP_PIN_V, GPIO.OUT)
        GPIO.setup(MOTOR_DIR_PIN_V, GPIO.OUT)
        
        # PWM 초기화
        global _pwm
        _pwm = GPIO.PWM(FAN_PWM_PIN, 1000)
        _pwm.start(0)
        
        print("[GPIO] ✅ Initialized (2-axis motors + fan, warnings disabled)")

    def connect_mqtt(self):
        """MQTT 브로커 연결 (재시도 로직 포함)"""
        max_retries = 10
        retry_delay = 3
        
        for attempt in range(max_retries):
            try:
                print(f"[MQTT] 🔄 Connecting to {MQTT_BROKER}:{MQTT_PORT} (attempt {attempt + 1}/{max_retries})...")
                self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
                self.mqtt_client.loop_start()
                print(f"[MQTT] ✅ Connected to broker!")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[MQTT] ⚠️ Connection failed: {e}. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print(f"[ERROR] ❌ Failed to connect after {max_retries} attempts: {e}")
                    raise

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT 연결 성공 (최신 API 시그니처)"""
        if reason_code == 0:
            print("[MQTT] 📡 Connected successfully")
            client.subscribe("ambient/ai/face-detected")
            client.subscribe("ambient/fan001/cmd/#")
            client.subscribe("ambient/user/register")  # BLE 게이트웨이에서 전달
            print("[MQTT] 📬 Subscribed to topics")
        else:
            print(f"[MQTT] ❌ Connection failed with code: {reason_code}")

    def on_mqtt_message(self, client, userdata, msg):
        """MQTT 메시지 수신"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode('utf-8'))
            
            if topic == "ambient/ai/face-detected":
                self.handle_face_detected(payload)
            elif topic.startswith("ambient/fan001/cmd/"):
                self.handle_mqtt_command(topic, payload)
            elif topic == "ambient/user/register":
                self.handle_user_register(payload)
        except Exception as e:
            print(f"[ERROR] MQTT message error: {e}")

    def handle_mqtt_command(self, topic, payload):
        """MQTT 명령 처리"""
        cmd = topic.split('/')[-1]
        
        if cmd == "speed":
            self.set_fan_speed(payload.get('level', 0))
        elif cmd == "power":
            power = payload.get('action') == 'on'
            self.set_fan_speed(100 if power else 0)
        elif cmd == "face-tracking":
            self.set_face_tracking(payload.get('enabled', False))
        elif cmd == "manual":
            # 수동 제어 (BLE 게이트웨이에서 전달)
            direction = payload.get('direction')
            step_angle = 5
            
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
            
            self.mqtt_client.publish("ambient/db/log-event", json.dumps({
                "device_id": "fan001",
                "event_type": "manual_control",
                "event_value": json.dumps({
                    "direction": direction,
                    "angle_h": _current_angle_h,
                    "angle_v": _current_angle_v
                }),
                "timestamp": datetime.now().isoformat()
            }))

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
        
        # 핀 및 현재 각도 선택
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
        
        self.mqtt_client.publish("ambient/fan001/status/angle", json.dumps({
            "horizontal": _current_angle_h,
            "vertical": _current_angle_v,
            "timestamp": datetime.now().isoformat()
        }))

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
        
        self.mqtt_client.publish("ambient/db/log-event", json.dumps({
            "device_id": "fan001",
            "event_type": "speed",
            "event_value": json.dumps({"speed": speed, "power": power}),
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
        """사용자 등록 처리 (BLE 게이트웨이에서 전달)"""
        name = payload.get('name', '')
        user_id = payload.get('user_id') or name.lower().replace(' ', '_')
        bluetooth_id = payload.get('bluetooth_id')
        image_base64 = payload.get('image_base64')
        
        # 이미지 저장
        photo_path = None
        if image_base64:
            photo_path = self.save_user_image(user_id, image_base64)
        
        # DB 서비스로 전달
        self.mqtt_client.publish("ambient/user/register", json.dumps({
            "user_id": user_id,
            "name": name,
            "bluetooth_id": bluetooth_id,
            "photo_path": photo_path,
            "timestamp": datetime.now().isoformat()
        }))
        
        print(f"[USER] ✅ Registered: {name} ({user_id})")
    
    def save_user_image(self, user_id, image_base64):
        """사용자 이미지 저장"""
        user_dir = USERS_DIR / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        image_path = user_dir / "face.jpg"
        
        try:
            image_data = base64.b64decode(image_base64)
            with open(image_path, 'wb') as f:
                f.write(image_data)
            print(f"[USER] 💾 Saved image: {image_path}")
            return str(image_path)
        except Exception as e:
            print(f"[ERROR] Failed to save image: {e}")
            return None

    def process_commands(self):
        """명령 큐 처리 (현재는 사용 안 함, MQTT로 직접 처리)"""
        print("[QUEUE] 🔄 Command processor started (standby mode)")
        while True:
            try:
                payload = self.command_queue.get(timeout=1)
                # 필요시 여기서 추가 처리
                self.command_queue.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                print(f"[ERROR] Command processing error: {e}")


def signal_handler(sig, frame):
    """종료 시그널 핸들러"""
    print("\n[FAN] 🛑 Shutting down...")
    if GPIO_AVAILABLE and _pwm:
        _pwm.stop()
        GPIO.cleanup()
    sys.exit(0)


if __name__ == "__main__":
    # 시그널 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 서비스 시작
    service = FanService()
    
    print("[INFO] 🚀 Service running... (Press Ctrl+C to stop)")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] 👋 Service stopped by user")
