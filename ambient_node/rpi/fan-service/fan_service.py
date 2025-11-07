#!/usr/bin/env python3

"""
Hardware Container (Fan Service) - IMPROVED
- BLE 데이터 수신
- 2축 GPIO 제어 (팬 속도, 수평/수직 모터 회전)
- MQTT 메시지 발행 및 구독
- 명령 큐 기반 처리
"""

import json
import base64
import threading
import queue
import paho.mqtt.client as mqtt
from datetime import datetime
from pathlib import Path
import os
import sys
import signal

# BLE 관련
try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    from bluezero import peripheral
    BLE_AVAILABLE = True
except ImportError:
    print("[WARN] BLE libraries not available, running in MQTT-only mode")
    BLE_AVAILABLE = False

# GPIO 관련
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    print("[WARN] GPIO not available, running in simulation mode")
    GPIO_AVAILABLE = False
    GPIO = None  # Placeholder to avoid NameError

# Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt-broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "fan-service")

# BLE Configuration
SERVICE_UUID = '12345678-1234-5678-1234-56789abcdef0'
WRITE_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef1'
NOTIFY_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef2'
DEVICE_NAME = 'AmbientNode'

# GPIO Pin Configuration (2축 모터)
FAN_PWM_PIN = 18         # BLDC 팬 속도 제어 (PWM)
MOTOR_STEP_PIN_H = 21    # 수평 모터 스텝
MOTOR_DIR_PIN_H = 20     # 수평 모터 방향
MOTOR_STEP_PIN_V = 23    # 수직 모터 스텝
MOTOR_DIR_PIN_V = 24     # 수직 모터 방향

# Data paths
DATA_DIR = Path("/var/lib/ambient-node")
USERS_DIR = DATA_DIR / "users"
DATA_DIR.mkdir(parents=True, exist_ok=True)
USERS_DIR.mkdir(parents=True, exist_ok=True)

# Global state
_current_speed = 0
_current_tracking = False
_current_angle_h = 90  # 수평 각도 (0~180도)
_current_angle_v = 90  # 수직 각도 (0~180도)
_notify_char = None
_pwm = None

class FanService:
    def __init__(self):
        self.mqtt_client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message
        
        # 명령 큐 (연속 BLE 전송 처리)
        self.command_queue = queue.Queue()
        threading.Thread(target=self.process_commands, daemon=True).start()
        
        # GPIO 초기화
        if GPIO_AVAILABLE:
            self.init_gpio()
        
        # MQTT 연결
        self.connect_mqtt()
        
        # BLE 초기화 (별도 스레드)
        if BLE_AVAILABLE:
            threading.Thread(target=self.init_ble, daemon=True).start()

    def init_gpio(self):
        """GPIO 핀 초기화 (2축 모터)"""
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(FAN_PWM_PIN, GPIO.OUT)
        
        # 수평 모터
        GPIO.setup(MOTOR_STEP_PIN_H, GPIO.OUT)
        GPIO.setup(MOTOR_DIR_PIN_H, GPIO.OUT)
        
        # 수직 모터
        GPIO.setup(MOTOR_STEP_PIN_V, GPIO.OUT)
        GPIO.setup(MOTOR_DIR_PIN_V, GPIO.OUT)
        
        # PWM 초기화 (BLDC 팬)
        global _pwm
        _pwm = GPIO.PWM(FAN_PWM_PIN, 1000)  # 1kHz
        _pwm.start(0)
        print("[GPIO] Initialized (2-axis motors + fan)")

    def connect_mqtt(self):
        """MQTT 브로커 연결"""
        try:
            # 재시도 로직: MQTT 브로커가 준비될 때까지 대기
            max_retries = 10
            retry_delay = 3  # seconds
            
            for attempt in range(max_retries):
                try:
                    print(f"[FAN] Attempting to connect to MQTT broker (attempt {attempt + 1}/{max_retries})...")
                    self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
                    self.mqtt_client.loop_start()
                    print(f"[MQTT] Connected to {MQTT_BROKER}:{MQTT_PORT}")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"[FAN] Connection failed: {e}. Retrying in {retry_delay} seconds...")
                        import time
                        time.sleep(retry_delay)
                    else:
                        print(f"[ERROR] Failed to connect to MQTT broker after {max_retries} attempts: {e}")
                        raise
        except Exception as e:
            print(f"[ERROR] Failed to connect to MQTT: {e}")

    def on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT 연결 성공 시"""
        if rc == 0:
            print("[MQTT] Connected successfully")
            # AI 얼굴 감지 구독
            client.subscribe("ambient/ai/face-detected")
            client.subscribe("ambient/fan001/cmd/#")
            print("[MQTT] Subscribed to topics")

    def on_mqtt_message(self, client, userdata, msg):
        """MQTT 메시지 수신 처리"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode('utf-8'))
            
            if topic == "ambient/ai/face-detected":
                self.handle_face_detected(payload)
            elif topic.startswith("ambient/fan001/cmd/"):
                self.handle_mqtt_command(topic, payload)
        except Exception as e:
            print(f"[ERROR] MQTT message error: {e}")

    def handle_mqtt_command(self, topic, payload):
        """MQTT 명령 토픽 처리"""
        cmd = topic.split('/')[-1]
        
        if cmd == "speed":
            self.set_fan_speed(payload.get('level', 0))
        elif cmd == "power":
            power = payload.get('action') == 'on'
            self.set_fan_speed(100 if power else 0)
        elif cmd == "face-tracking":
            self.set_face_tracking(payload.get('enabled', False))

    def handle_face_detected(self, payload):
        """얼굴 감지 시 2축 모터 회전"""
        angle_h = payload.get('angle_h', _current_angle_h)
        angle_v = payload.get('angle_v', _current_angle_v)
        user_id = payload.get('user_id')
        
        print(f"[FACE] User {user_id}: H={angle_h}°, V={angle_v}°")
        
        self.rotate_motor_2axis('horizontal', angle_h)
        self.rotate_motor_2axis('vertical', angle_v)

    def rotate_motor_2axis(self, axis, target_angle):
        """2축 모터 제어 (horizontal/vertical)"""
        global _current_angle_h, _current_angle_v
        
        if not GPIO_AVAILABLE:
            print(f"[MOTOR] Simulated {axis} to {target_angle}°")
            return
        
        # 현재 각도 및 핀 선택
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
        
        # 각도 범위 제한
        target_angle = max(0, min(180, target_angle))
        
        # 방향 설정
        direction = 1 if target_angle > current else 0
        GPIO.output(dir_pin, direction)
        
        # 스텝 펄스 생성 (1도 = 10 스텝)
        steps = abs(int((target_angle - current) * 10))
        for i in range(steps):
            GPIO.output(step_pin, GPIO.HIGH)
            threading.Event().wait(0.001)
            GPIO.output(step_pin, GPIO.LOW)
            threading.Event().wait(0.001)
        
        # 상태 업데이트
        if axis == 'horizontal':
            _current_angle_h = target_angle
        else:
            _current_angle_v = target_angle
        
        print(f"[MOTOR] {axis.capitalize()} → {target_angle}°")
        
        # MQTT 상태 발행
        self.mqtt_client.publish("ambient/fan001/status/angle", json.dumps({
            "horizontal": _current_angle_h,
            "vertical": _current_angle_v,
            "timestamp": datetime.now().isoformat()
        }))

    def set_fan_speed(self, speed):
        """BLDC 팬 속도 설정 (0-100)"""
        global _current_speed
        
        if GPIO_AVAILABLE and _pwm:
            _pwm.ChangeDutyCycle(speed)
        
        _current_speed = speed
        power = speed > 0
        print(f"[FAN] Speed: {speed}%, Power: {power}")
        
        # MQTT 상태 발행
        self.mqtt_client.publish("ambient/fan001/status/power", json.dumps({
            "state": "on" if power else "off",
            "timestamp": datetime.now().isoformat()
        }))
        
        self.mqtt_client.publish("ambient/fan001/status/speed", json.dumps({
            "level": speed,
            "timestamp": datetime.now().isoformat()
        }))
        
        # 이벤트 로깅
        self.mqtt_client.publish("ambient/db/log-event", json.dumps({
            "device_id": "fan001",
            "event_type": "speed",
            "event_value": json.dumps({"speed": speed, "power": power}),
            "timestamp": datetime.now().isoformat()
        }))

    def set_face_tracking(self, enabled):
        """얼굴 추적 ON/OFF"""
        global _current_tracking
        _current_tracking = enabled
        
        self.mqtt_client.publish("ambient/fan001/status/face-tracking", json.dumps({
            "enabled": enabled,
            "timestamp": datetime.now().isoformat()
        }))
        
        print(f"[FACE] Tracking: {enabled}")

    def save_user_image(self, user_id, image_base64):
        """사용자 이미지 저장"""
        user_dir = USERS_DIR / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        image_path = user_dir / "face.jpg"
        
        try:
            image_data = base64.b64decode(image_base64)
            with open(image_path, 'wb') as f:
                f.write(image_data)
            print(f"[USER] Saved image: {image_path}")
            return str(image_path)
        except Exception as e:
            print(f"[ERROR] Failed to save image: {e}")
            return None

    def process_commands(self):
        """명령 큐 순차 처리 (BLE 연속 전송 대응)"""
        while True:
            try:
                payload = self.command_queue.get(timeout=0.1)
                self.handle_ble_write(payload)
                self.command_queue.task_done()
            except queue.Empty:
                pass

    def handle_ble_write(self, payload):
        """BLE 수신 데이터 처리"""
        print(f"[BLE] 🔧 명령 처리 시작: {payload}")
        
        # 팬 속도 제어
        if 'speed' in payload:
            speed = payload['speed']
            print(f"[BLE] 🌀 풍속 제어 명령: {speed}")
            self.set_fan_speed(speed)
        
        # 얼굴 추적 ON/OFF
        if 'trackingOn' in payload:
            tracking = payload['trackingOn']
            print(f"[BLE] 👁️ 얼굴 추적 명령: {tracking}")
            self.set_face_tracking(tracking)
        
        # 액션별 처리
        action = payload.get('action')
        
        if action == 'register_user':
            name = payload.get('name', '')
            user_id = name.lower().replace(' ', '_')
            bluetooth_id = payload.get('bluetooth_id')
            
            image_base64 = payload.get('image_base64') or payload.get('imagePath')
            photo_path = None
            if image_base64:
                photo_path = self.save_user_image(user_id, image_base64)
            
            # MQTT로 사용자 등록
            self.mqtt_client.publish("ambient/user/register", json.dumps({
                "user_id": user_id,
                "name": name,
                "bluetooth_id": bluetooth_id,
                "photo_path": photo_path,
                "timestamp": datetime.now().isoformat()
            }))
        
        elif action == 'manual_control':
            direction = payload.get('direction')  # 'up', 'down', 'left', 'right', 'stop'
            step_angle = 5  # 한 번에 5도씩 이동
            
            # 상대 각도 증감 (연속 클릭 지원)
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
            elif direction == 'stop':
                pass  # 정지 명령
            
            # 이벤트 로깅
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

    def on_ble_write_characteristic(self, value, options):
        """BLE Write Characteristic 콜백"""
        try:
            data_str = bytes(value).decode('utf-8')
            print(f"[BLE] 📥 데이터 수신 (raw): {data_str}")
            payload = json.loads(data_str)
            print(f"[BLE] 📦 파싱된 데이터: {payload}")
            
            # 큐에 추가 (순차 처리)
            self.command_queue.put(payload)
            print(f"[BLE] ✅ 명령 큐에 추가됨 (큐 크기: {self.command_queue.qsize()})")
            
            # BLE 응답 (ACK)
            if _notify_char:
                ack_data = {
                    "type": "ACK",
                    "timestamp": datetime.now().isoformat()
                }
                send_notification(ack_data)
                print(f"[BLE] 📤 ACK 전송: {ack_data}")
        except Exception as e:
            print(f"[ERROR] ❌ BLE write error: {e}")
            import traceback
            traceback.print_exc()

    def init_ble(self):
        """BLE 서버 초기화"""
        global _notify_char
        
        if not BLE_AVAILABLE:
            print("[WARN] BLE not available, skipping BLE initialization")
            return
        
        try:
            print("[BLE] 🔵 BLE 초기화 시작...")
            adapter = peripheral.adapter.Adapter()
            adapter_address = adapter.address
            print(f"[BLE] 📡 Adapter Address: {adapter_address}")
            
            app = peripheral.localGATT.Application()
            service = peripheral.localGATT.Service(1, SERVICE_UUID, True)
            print(f"[BLE] 📦 Service UUID: {SERVICE_UUID}")
            
            # Write Characteristic
            write_char = peripheral.localGATT.Characteristic(
                1, 1, WRITE_CHAR_UUID, [],
                False, ['write', 'encrypt-write'],
                read_callback=None,
                write_callback=self.on_ble_write_characteristic,
                notify_callback=None,
            )
            print(f"[BLE] ✍️ Write Characteristic UUID: {WRITE_CHAR_UUID}")
            
            # Notify Characteristic
            _notify_char = peripheral.localGATT.Characteristic(
                1, 2, NOTIFY_CHAR_UUID, [],
                False, ['notify'],
                read_callback=None,
                write_callback=None,
                notify_callback=None,
            )
            print(f"[BLE] 🔔 Notify Characteristic UUID: {NOTIFY_CHAR_UUID}")
            
            app.add_managed_object(service)
            app.add_managed_object(write_char)
            app.add_managed_object(_notify_char)
            
            gatt_manager = peripheral.GATT.GattManager(adapter_address)
            gatt_manager.register_application(app, {})
            print("[BLE] ✅ GATT Application 등록 완료")
            
            advert = peripheral.advertisement.Advertisement(1, 'peripheral')
            advert.local_name = DEVICE_NAME
            advert.service_UUIDs = [SERVICE_UUID]
            
            ad_manager = peripheral.advertisement.AdvertisingManager(adapter_address)
            ad_manager.register_advertisement(advert, {})
            
            print(f"[BLE] 🎉 Advertising as '{DEVICE_NAME}'")
            print(f"[BLE] 📢 앱에서 '{DEVICE_NAME}' 기기를 검색할 수 있습니다")
            
            # GLib main loop
            GLib.MainLoop().run()
        except Exception as e:
            print(f"[ERROR] ❌ BLE initialization failed: {e}")
            import traceback
            traceback.print_exc()

    def start(self):
        """서비스 시작"""
        print("[FAN] Starting Fan Service...")
        try:
            while True:
                threading.Event().wait(1)
        except KeyboardInterrupt:
            print("\n[FAN] Shutting down...")
            if GPIO_AVAILABLE and _pwm:
                _pwm.stop()
                GPIO.cleanup()
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            print("[FAN] Fan Service stopped")

def send_notification(data):
    """BLE Notification 발송"""
    global _notify_char
    if _notify_char is None:
        return
    try:
        message = json.dumps(data)
        _notify_char.set_value(message.encode('utf-8'))
    except Exception as e:
        print(f"[ERROR] Notification error: {e}")

def main():
    service = FanService()
    service.start()

if __name__ == "__main__":
    main()
