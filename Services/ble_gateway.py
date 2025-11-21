#!/usr/bin/env python3
"""BLE Gateway Service - 개선된 사용자 선택/등록 처리"""

import base64
import os
import json
import threading
import time
import signal
import sys
import uuid
from datetime import datetime
from PIL import Image
import io

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    from bluezero import peripheral, adapter
    BLE_AVAILABLE = True
except ImportError as e:
    print(f"[ERROR] BLE libraries not available: {e}")
    sys.exit(1)

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError as e:
    print(f"[ERROR] MQTT library not available: {e}")
    sys.exit(1)

# Configuration
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "ble-gateway"
SERVICE_UUID = '12345678-1234-5678-1234-56789abcdef0'
WRITE_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef1'
NOTIFY_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef2'
DEVICE_NAME = 'AmbientNode'

# Global state
_notify_char = None
_mqtt_client = None
_agent_path = '/ambient/agent'

# 청크 수신 버퍼 (단순 방식)
_chunk_buffer = []
_chunk_total = 0

# 이미지 저장 경로
USER_IMAGES_DIR = "/var/lib/ambient-node/users"


# ========================================
# Pairing Agent
# ========================================
class PairingAgent(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, _agent_path)
    
    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Release(self):
        print('[AGENT] Released')
    
    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        print(f'[AGENT] RequestAuthorization for {device} -> Approved')
        return
    
    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        print(f'[AGENT] AuthorizeService {uuid} for {device} -> Approved')
        return
    
    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Cancel(self):
        print('[AGENT] Pairing canceled')


def register_pairing_agent():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    agent = PairingAgent(bus)
    manager = dbus.Interface(
        bus.get_object('org.bluez', '/org/bluez'),
        'org.bluez.AgentManager1'
    )
    manager.RegisterAgent(_agent_path, 'NoInputNoOutput')
    manager.RequestDefaultAgent(_agent_path)
    print(f'[AGENT] Registered as NoInputNoOutput')
    return agent


# ========================================
# 이미지 저장 (개선: 유효성 검증)
# ========================================
def save_base64_image_to_png(base64_str: str, save_dir: str, filename: str) -> str:
    """base64 → PNG 저장 (유효성 검증 포함)"""
    if not os.path.exists(save_dir):
        os.makedirs(save_dir, exist_ok=True)
        print(f"[IMAGE] Created directory: {save_dir}")
    
    try:
        # 패딩 자동 보정
        missing_padding = len(base64_str) % 4
        if missing_padding:
            base64_str += '=' * (4 - missing_padding)
        
        # 디코딩
        img_data = base64.b64decode(base64_str)
        
        # 이미지 유효성 검증
        img = Image.open(io.BytesIO(img_data))
        img.verify()
        
        # 저장
        save_path = os.path.join(save_dir, filename)
        with open(save_path, 'wb') as f:
            f.write(img_data)
        
        print(f"[IMAGE] Saved: {save_path}")
        return save_path
    
    except base64.binascii.Error as e:
        print(f"[IMAGE] Base64 decode error: {e}")
        return ""
    except Exception as e:
        print(f"[IMAGE] Save failed: {e}")
        return ""


# ========================================
# MQTT 메시지 수신 (응답 처리)
# ========================================
def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    """MQTT 연결 성공"""
    if reason_code == 0:
        print(f'[MQTT] ✅ Connected to {MQTT_BROKER}:{MQTT_PORT}')
        
        topics = [
            "ambient/user/register-ack",
            "ambient/session/active",
            "ambient/stats/response",
            "ambient/ai/face-detected",
            "ambient/ai/face-lost",
        ]
        
        for topic in topics:
            client.subscribe(topic)
            print(f'[MQTT] 📬 Subscribed to {topic}')
    else:
        print(f'[MQTT] ❌ Connection failed: {reason_code}')


def on_mqtt_message(client, userdata, msg):
    """MQTT 메시지 수신 → BLE Notify"""
    try:
        payload = json.loads(msg.payload.decode())
        print(f'[MQTT] 📥 Received on {msg.topic}')
        
        # 토픽별 처리
        if msg.topic == "ambient/user/register-ack":
            send_notification({
                "type": "REGISTER_ACK",
                "success": payload.get('success', False),
                "user_id": payload.get('user_id'),
                "error": payload.get('error'),
                "timestamp": payload.get('timestamp')
            })
        
        elif msg.topic == "ambient/session/active":
            send_notification({
                "type": "SESSION_UPDATE",
                "session_id": payload.get('session_id'),
                "user_list": payload.get('user_list', []),
                "timestamp": payload.get('timestamp')
            })
        
        elif msg.topic == "ambient/stats/response":
            send_notification({
                "type": "STATS",
                "data": payload,
                "timestamp": payload.get('timestamp')
            })
        
        elif msg.topic == "ambient/ai/face-detected":
            send_notification({
                "type": "FACE_DETECTED",
                "user_id": payload.get('user_id'),
                "confidence": payload.get('confidence'),
                "timestamp": payload.get('timestamp')
            })
        
        elif msg.topic == "ambient/ai/face-lost":
            send_notification({
                "type": "FACE_LOST",
                "user_id": payload.get('user_id'),
                "duration": payload.get('duration_seconds'),
                "timestamp": payload.get('timestamp')
            })
    
    except Exception as e:
        print(f"[MQTT] Message error: {e}")


# ========================================
# BLE Notify 전송
# ========================================
def send_notification(data: dict):
    """BLE Notify로 Flutter 앱에 데이터 전송"""
    global _notify_char
    if _notify_char:
        try:
            payload = json.dumps(data)
            _notify_char.set_value(payload.encode('utf-8'))
            print(f"[BLE] Notify sent: {data.get('type')}")
        except Exception as e:
            print(f"[BLE] Notify error: {e}")


# ========================================
# 완전한 데이터 처리 (핵심 로직)
# ========================================
def process_complete_data(data_str):
    """완전한 데이터 처리 - 개선된 버전"""
    global _mqtt_client

    try:
        payload = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f'[WARN] JSON parse error: {e}')
        send_notification({
            "type": "ERROR",
            "message": "Invalid JSON format",
            "timestamp": datetime.now().isoformat()
        })
        return

    timestamp = datetime.now().isoformat()
    action = payload.get('action', '')
    topic = None
    mqtt_payload = {}

    # ========================================
    # 1. 사용자 등록 (user_register)
    # ========================================
    if action == 'user_register':
        # UUID로 고유 ID 생성
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        username = payload.get('name', 'Unknown')
        base64_img = payload.get('image_base64')
        
        # 이미지 저장
        image_path = ""
        if base64_img:
            user_dir = os.path.join(USER_IMAGES_DIR, user_id)
            filename = f"{user_id}.png"
            image_path = save_base64_image_to_png(base64_img, user_dir, filename)
            
            if not image_path:
                send_notification({
                    "type": "ERROR",
                    "message": "Image save failed",
                    "timestamp": timestamp
                })
                return
        
        topic = "ambient/user/register"
        mqtt_payload = {
            "event_type": "user_register",
            "user_id": user_id,
            "username": username,
            "image_path": image_path,
            "timestamp": timestamp
        }
        print(f'[BLE] 사용자 등록: {username} ({user_id})')

    # ========================================
    # 2. 사용자 선택 (user_select)
    # ========================================
    elif action == 'user_select':
        user_list = payload.get('users', [])
        
        if not isinstance(user_list, list):
            send_notification({
                "type": "ERROR",
                "message": "'users' field must be an array",
                "timestamp": timestamp
            })
            return
        
        topic = "ambient/user/select"
        mqtt_payload = {
            "event_type": "user_select",
            "user_list": user_list,
            "timestamp": timestamp
        }
        
        if len(user_list) == 0:
            print(f'[BLE] 모든 사용자 선택 해제')
        else:
            usernames = [u.get('name', u.get('user_id', '?')) for u in user_list]
            print(f'[BLE] 사용자 선택: {", ".join(usernames)} ({len(user_list)}명)')

    # ========================================
    # 3. 사용자 정보 수정 (user_update)
    # ========================================
    elif action == 'user_update':
        topic = "ambient/user/update"
        mqtt_payload = {
            "event_type": "user_update",
            "user_id": payload.get('user_id'),
            "username": payload.get('username'),
            "timestamp": timestamp
    
        print(f'[BLE] 사용자 정보 수정: {payload.get("user_id")}')

    # ========================================
    # 4. 풍속 변경 (speed_change)
    # ========================================
    elif action == 'speed_change':
        speed = int(payload.get('speed', 0))
        
        if not (0 <= speed <= 5):
            send_notification({
                "type": "ERROR",
                "message": f"Invalid speed: {speed} (must be 0-5)",
                "timestamp": timestamp
            })
            return
        
        topic = "ambient/command/speed"
        mqtt_payload = {
            "event_type": "speed_change",
            "speed": speed,
            "timestamp": timestamp
        }
        print(f'[BLE] 풍속 변경: {speed}')

    # ========================================
    # 4. 각도 변경 (angle_change)
    # ========================================
    elif action == 'angle_change':
        direction = payload.get('direction', 'center')
        
        topic = "ambient/command/angle"
        mqtt_payload = {
            "event_type": "angle_change",
            "direction": direction,
            "timestamp": timestamp
        }
        print(f'[BLE] 각도 변경: {direction}')

    # ========================================
    # 5. 모드 변경 (mode_change)
    # ========================================
    elif action == 'mode_change':
        mode = payload.get('mode', 'manual')
        
        topic = "ambient/command/mode"
        mqtt_payload = {
            "event_type": "mode_change",
            "mode": mode,
            "timestamp": timestamp
        }
        print(f'[BLE] 모드 변경: {mode}')

    # ========================================
    # 6. 통계 조회 (stats_request)
    # ========================================
    elif action == 'stats_request':
        request_id = payload.get('request_id', f"req-{int(time.time() * 1000)}")
        
        topic = "ambient/stats/request"
        mqtt_payload = {
            "request_id": request_id,
            "type": payload.get('type', 'usage'),
            "period": payload.get('period', 'day'),
            "user_id": payload.get('user_id'),
            "timestamp": timestamp
        }
        print(f'[BLE] 📊 통계 요청: {mqtt_payload["type"]}')

    # ========================================
    # 알 수 없는 action
    # ========================================
    else:
        print(f'[WARN] Unknown action: {action}')
        send_notification({
            "type": "ERROR",
            "message": f"Unknown action: {action}",
            "timestamp": timestamp
        })
        return

    # ========================================
    # MQTT 발행
    # ========================================
    if _mqtt_client and _mqtt_client.is_connected():
        if topic and mqtt_payload:
            _mqtt_client.publish(topic, json.dumps(mqtt_payload), qos=1)
            print(f'[MQTT] 📤 Published to {topic}')
            
            # ACK 전송
            send_notification({
                "type": "ACK",
                "action": action,
                "success": True,
                "timestamp": timestamp
            })
    else:
        print(f'[WARN] MQTT not connected')
        send_notification({
            "type": "ERROR",
            "message": "MQTT not connected",
            "timestamp": timestamp
        })


# ========================================
# BLE Write 수신 (청크 처리 포함)
# ========================================
def on_write_characteristic(value, options):
    """BLE Write 수신 - 청크 처리"""
    global _mqtt_client, _chunk_buffer, _chunk_total
    
    try:
        data_str = bytes(value).decode('utf-8')
        
        # 청크 헤더 확인
        if data_str.startswith('<CHUNK:'):
            if '>' in data_str:
                header_end = data_str.index('>')
                header = data_str[7:header_end]
                parts = header.split(',')
                
                if len(parts) == 3:
                    chunk_id = parts[0]
                    current = int(parts[1])
                    total = int(parts[2])
                    chunk_data = data_str[header_end + 1:]
                    
                    # 청크 버퍼 초기화
                    if chunk_id not in _chunk_buffer:
                        _chunk_buffer[chunk_id] = {
                            "data": [''] * total,
                            "total": total,
                            "timestamp": time.time()
                        }
                    
                    # 청크 저장
                    _chunk_buffer[chunk_id]["data"][current - 1] = chunk_data
                    print(f'[BLE] 📦 Chunk {current}/{total} received')
                    
                    # 완료 확인
                    if all(_chunk_buffer[chunk_id]["data"]):
                        complete_data = ''.join(_chunk_buffer[chunk_id]["data"])
                        del _chunk_buffer[chunk_id]
                        print(f'[BLE] All chunks assembled')
                        
                        # 완전한 데이터 처리
                        process_complete_data(complete_data)
                    return
        
        # 일반 데이터 (청크 아님)
        process_complete_data(data_str)
    
    except Exception as e:
        print(f'[BLE] Write error: {e}')
        send_notification({
            "type": "ERROR",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        })


# ========================================
# BLE Read 수신 (연결 상태 확인)
# ========================================
def on_read_characteristic():
    """BLE Read 응답 - 연결 상태"""
    return json.dumps({
        "status": "connected",
        "timestamp": datetime.now().isoformat()
    }).encode('utf-8')


# ========================================
# GATT 및 광고 설정
# ========================================
def setup_gatt_and_advertising():
    """GATT 서비스 및 광고 설정"""
    global _notify_char

    adapter_obj = peripheral.adapter.Adapter()
    app = peripheral.localGATT.Application()
    service = peripheral.localGATT.Service(1, SERVICE_UUID, True)

    write_char = peripheral.localGATT.Characteristic(
        1, 1, WRITE_CHAR_UUID, [], False, ['write-without-response', 'write'],
        read_callback=None, write_callback=on_write_characteristic, notify_callback=None
    )

    _notify_char = peripheral.localGATT.Characteristic(
        1, 2, NOTIFY_CHAR_UUID, [], False, ['notify'],
        read_callback=on_read_characteristic, write_callback=None, notify_callback=None
    )

    app.add_managed_object(service)
    app.add_managed_object(write_char)
    app.add_managed_object(_notify_char)

    gatt_manager = peripheral.GATT.GattManager(adapter_obj.address)
    gatt_manager.register_application(app, {})

    advert = peripheral.advertisement.Advertisement(1, 'peripheral')
    advert.local_name = DEVICE_NAME
    advert.service_uuids = [SERVICE_UUID]

    ad_manager = peripheral.advertisement.AdvertisingManager(adapter_obj.address)
    ad_manager.register_advertisement(advert, {})

    print(f'[BLE] 📡 Advertising as "{DEVICE_NAME}"')
    print(f'[BLE] ✅ Using adapter: {adapter_obj.address}')
    
    threading.Thread(target=lambda: app.start(), daemon=True).start()
    return ad_manager, advert, gatt_manager, app


# ========================================
# 시그널 핸들러
# ========================================
def signal_handler(sig, frame):
    """종료 시그널 핸들러"""
    print('\n[EXIT] Shutting down...')
    if _mqtt_client:
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
    sys.exit(0)


# ========================================
# 메인
# ========================================
def main():
    global _mqtt_client
    
    print("=" * 60)
    print("BLE Gateway Service Starting...")
    print("=" * 60)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Pairing Agent 등록
    agent = register_pairing_agent()
    
    # MQTT 연결
    _mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    _mqtt_client.on_connect = on_mqtt_connect
    _mqtt_client.on_message = on_mqtt_message
    _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    _mqtt_client.loop_start()
    
    # MQTT 구독
    topics = [
        "ambient/user/register-ack",
        "ambient/session/active",
        "ambient/stats/response",
        "ambient/ai/face-detected",
        "ambient/ai/face-lost",
    ]
    for topic in topics:
        _mqtt_client.subscribe(topic)
    print(f"[MQTT] Connected and subscribed")
    
    # BLE Peripheral 시작
    try:
        app = peripheral.Peripheral(DEVICE_NAME, local_name=DEVICE_NAME)
        app.add_service(srv_id=1, uuid=SERVICE_UUID, primary=True)
        
        # Write Characteristic
        app.add_characteristic(
            srv_id=1, chr_id=1, uuid=WRITE_CHAR_UUID,
            value=[], notifying=False,
            flags=['write', 'write-without-response'],
            write_callback=on_write_characteristic
        )
        
        # Notify Characteristic
        _notify_char = app.add_characteristic(
            srv_id=1, chr_id=2, uuid=NOTIFY_CHAR_UUID,
            value=[], notifying=True,
            flags=['notify', 'read'],
            read_callback=on_read_characteristic
        )
        
        print("[BLE] Peripheral started")
        print(f"[BLE] Device Name: {DEVICE_NAME}")
        print(f"[BLE] Service UUID: {SERVICE_UUID}")
        
        # 광고 시작
        app.publish()
        
        # 메인 루프
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        print("\n[BLE] Shutting down...")
    finally:
        if _mqtt_client:
            _mqtt_client.loop_stop()
            _mqtt_client.disconnect()
        print("[BLE] Stopped")


if __name__ == '__main__':
    main()
