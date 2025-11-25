#!/usr/bin/env python3
"""BLE Gateway Service - user_list 처리 및 user_id 직접 수신 지원"""

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

# ... (임포트 및 설정 부분은 기존과 동일) ...

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

# 청크 수신 버퍼
_chunk_buffer = []
_expected_total = 0

# 이미지 저장 경로
USER_IMAGES_DIR = "/var/lib/ambient-node/users"

# ... (PairingAgent 클래스 및 register_pairing_agent 함수는 기존과 동일) ...
# ... (save_base64_image_to_png 함수 기존과 동일) ...
# ... (MQTT 핸들러 on_mqtt_connect, on_mqtt_message, send_notification 기존과 동일) ...

# ========================================
# Pairing Agent (생략 - 위와 동일)
# ========================================
class PairingAgent(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, _agent_path)
    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Release(self): pass
    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
    def RequestAuthorization(self, device): return
    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid): return
    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Cancel(self): pass

def register_pairing_agent():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    agent = PairingAgent(bus)
    manager = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.AgentManager1')
    manager.RegisterAgent(_agent_path, 'NoInputNoOutput')
    manager.RequestDefaultAgent(_agent_path)
    return agent

# ========================================
# 이미지 저장 함수 (생략 - 위와 동일)
# ========================================
def save_base64_image_to_png(base64_str: str, save_dir: str, filename: str) -> str:
    if not os.path.exists(save_dir):
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            print(f"[IMAGE] Failed to create directory {save_dir}: {e}")
            return ""
    try:
        missing_padding = len(base64_str) % 4
        if missing_padding: base64_str += '=' * (4 - missing_padding)
        img_data = base64.b64decode(base64_str)
        try:
            img = Image.open(io.BytesIO(img_data))
            img.verify()
        except Exception: return ""
        save_path = os.path.join(save_dir, filename)
        with open(save_path, 'wb') as f: f.write(img_data)
        return save_path
    except Exception as e:
        print(f"[IMAGE] Error: {e}")
        return ""

# ========================================
# MQTT 핸들러 (생략 - 위와 동일)
# ========================================
def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f'[MQTT] Connected')
        client.subscribe("ambient/user/register-ack")
        client.subscribe("ambient/session/active")
        client.subscribe("ambient/stats/response")
        client.subscribe("ambient/ai/face-detected")
        client.subscribe("ambient/ai/face-lost")

def on_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        if msg.topic == "ambient/user/register-ack":
            send_notification({"type": "REGISTER_ACK", "success": payload.get('success', False), "user_id": payload.get('user_id'), "error": payload.get('error')})
        elif msg.topic == "ambient/ai/face-detected":
            send_notification({"type": "FACE_DETECTED", "user_id": payload.get('user_id')})
        elif msg.topic == "ambient/session/active":
             send_notification({"type": "SESSION_UPDATE", "session_id": payload.get('session_id'), "user_list": payload.get('user_list')})
        elif msg.topic == "ambient/stats/response":
            send_notification(payload)
    except Exception as e:
        print(f"[MQTT] Msg error: {e}")

def send_notification(data: dict):
    global _notify_char
    if _notify_char and data:
        try:
            payload = json.dumps(data)
            _notify_char.set_value(payload.encode('utf-8'))
            print(f'[BLE] Notification sent: {payload}')
        except Exception as e:
            print(f"[BLE] Notify error: {e}")

# ========================================
# ✅ [핵심 수정] user_id 추출 로직 강화
# ========================================
def extract_user_id(payload: dict) -> str:
    """
    1순위: Payload 최상위의 'user_id' 필드 (앱에서 보낸 커맨드)
    2순위: 'user_list' 내부의 첫 번째 사용자 (기존 user_select 로직 호환)
    """
    # 1. 앱이 직접 보낸 user_id 확인
    if 'user_id' in payload and payload['user_id']:
        return payload['user_id']
    
    # 2. user_list가 있는 경우 (user_select 이벤트 등)
    user_list = payload.get('user_list', [])
    if user_list and isinstance(user_list, list) and len(user_list) > 0:
        # 리스트 내부 객체가 dict인지 확인
        first_user = user_list[0]
        if isinstance(first_user, dict):
            return first_user.get('user_id')
            
    return None

# ========================================
# 데이터 처리 로직
# ========================================
def process_complete_data(data_str):
    global _mqtt_client

    try:
        payload = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f'[WARN] JSON parse error: {e}')
        # Git 충돌 마커 등 정크 데이터가 들어올 경우 방어
        send_notification({"type": "ERROR", "message": "Invalid JSON"})
        return

    timestamp = datetime.now().isoformat()
    action = payload.get('action', '')
    
    # ✅ 수정: 개선된 함수를 통해 user_id 추출
    # 이제 앱에서 {"action": "speed_change", "speed": 1, "user_id": "user_xxx"} 로 보내면
    # 여기서 user_id 변수에 "user_xxx"가 정상적으로 담깁니다.
    user_id = extract_user_id(payload)
    
    topic = None
    mqtt_payload = {}

    if action == 'user_register':
        # 등록 시에는 payload의 user_id가 신규 ID가 되거나 없을 수 있음
        register_user_id = payload.get('user_id')
        if not register_user_id:
            register_user_id = f"user_{int(time.time())}"
            
        username = payload.get('username', 'Unknown')
        base64_img = payload.get('image_base64')
        
        print(f'[BLE] Processing registration for: {username} ({register_user_id})')
        
        image_path = ""
        if base64_img:
            # 이미지 저장은 시간이 걸리므로 실전에서는 스레드로 분리 권장 (아래 피드백 참조)
            user_dir = os.path.join(USER_IMAGES_DIR, register_user_id)
            filename = f"{register_user_id}.png"
            image_path = save_base64_image_to_png(base64_img, user_dir, filename)
        
        topic = "ambient/user/register"
        mqtt_payload = {
            "user_id": register_user_id,
            "username": username,
            "image_path": image_path,
            "timestamp": timestamp
        }

    elif action == 'user_update':
        # user_id 변수 활용
        username = payload.get('username', 'Unknown')
        base64_img = payload.get('image_base64')
        
        print(f'[BLE] Processing update for: {username} ({user_id})')
        
        image_path = ""
        if base64_img and user_id:
            user_dir = os.path.join(USER_IMAGES_DIR, user_id)
            filename = f"{user_id}.png"
            image_path = save_base64_image_to_png(base64_img, user_dir, filename)
        
        topic = "ambient/user/update"
        mqtt_payload = {
            "user_id": user_id,
            "username": username,
            "image_path": image_path,
            "timestamp": timestamp
        }

    elif action == 'user_delete':
        topic = "ambient/user/delete"
        mqtt_payload = {
            "user_id": user_id,
            "timestamp": timestamp
        }
        print(f'[BLE] User delete: {user_id}')

    elif action == 'speed_change':
        speed = payload.get('speed', 0)
        
        topic = "ambient/command/speed"
        mqtt_payload = {
            "event_type": "speed_change",
            "speed": speed,
            "user_id": user_id, # 앱이 보내줬으면 여기에 값이 들어감
            "timestamp": timestamp
        }
        print(f'[BLE] Speed: {speed} (user: {user_id})')

    elif action == 'angle_change':
        direction = payload.get('direction', 'center')
        toggle_on = payload.get('toggleOn', 0)
        
        topic = "ambient/command/angle"
        mqtt_payload = {
            "event_type": "angle_change",
            "direction": direction,
            "toggleOn": toggle_on,
            "user_id": user_id, # 앱이 보내줬으면 여기에 값이 들어감
            "timestamp": timestamp
        }
        print(f'[BLE] Angle: {direction} (user: {user_id})')

    elif action == 'mode_change':
        mode = payload.get('mode', 'manual')
        
        topic = "ambient/command/mode"
        mqtt_payload = {
            "event_type": "mode_change",
            "mode": mode,
            "user_id": user_id,
            "timestamp": timestamp
        }
        print(f'[BLE] Mode: {mode} (user: {user_id})')

    elif action == 'user_select':
        user_list = payload.get('user_list', [])
        
        topic = "ambient/user/select"
        mqtt_payload = {
            "event_type": "user_select",
            "user_list": user_list,
            "timestamp": timestamp
        }
        print(f'[BLE] User select: {len(user_list)} users')
        
    elif action == 'shutdown':
        os.system('sudo shutdown -h now')

    elif action == 'mqtt_publish':
        req_topic = payload.get('topic')
        req_payload = payload.get('payload')
        
        if req_topic and req_payload:
            topic = req_topic
            mqtt_payload = req_payload
            print(f'[BLE] Proxying MQTT to: {topic}')
        else:
            print('[WARN] mqtt_publish missing topic or payload')
            return
        
    else:
        print(f'[WARN] Unknown action: {action}')
        return

    # MQTT Publish
    if _mqtt_client and _mqtt_client.is_connected() and topic:
        _mqtt_client.publish(topic, json.dumps(mqtt_payload), qos=1)
        print(f'[MQTT] Published to {topic}: {mqtt_payload}')
        
        if action in ['speed_change', 'angle_change', 'mode_change', 'user_select']:
            send_notification({"type": "ACK", "action": action, "success": True})

# ... (이하 on_write_characteristic, on_read_characteristic, setup_gatt, main 등 기존과 동일) ...
# ========================================
# BLE Write 수신 (생략 - 기존 로직 유지)
# ========================================
def on_write_characteristic(value, options):
    global _chunk_buffer, _expected_total
    try:
        data_str = bytes(value).decode('utf-8')
        # 청크 처리 로직 (기존과 동일)
        if data_str.startswith('<CHUNK:'):
            try:
                tag_end = data_str.find('>')
                if tag_end == -1: return
                header_content = data_str[7:tag_end]
                chunk_data = data_str[tag_end+1:]
                if chunk_data.startswith('>'): chunk_data = chunk_data[1:]

                if header_content == 'END':
                    if _chunk_buffer and all(_chunk_buffer):
                        print(f'[BLE] End signal. Assembling {_expected_total} chunks...')
                        complete_data = ''.join(_chunk_buffer)
                        _chunk_buffer = []
                        _expected_total = 0
                        process_complete_data(complete_data)
                    return

                if '/' in header_content:
                    idx_str, total_str = header_content.split('/')
                    current_idx = int(idx_str)
                    total_chunks = int(total_str)
                    
                    if _expected_total != total_chunks:
                        _expected_total = total_chunks
                        _chunk_buffer = [''] * total_chunks

                    if 0 <= current_idx < total_chunks:
                        _chunk_buffer[current_idx] = chunk_data
                        if total_chunks > 10:
                            if current_idx % (total_chunks // 10) == 0: print(f'[BLE] Chunk {current_idx + 1}/{total_chunks}')
                        else: print(f'[BLE] Chunk {current_idx + 1}/{total_chunks}')

                    if all(_chunk_buffer):
                        print(f'[BLE] All chunks assembled (Auto).')
                        complete_data = ''.join(_chunk_buffer)
                        _chunk_buffer = []
                        _expected_total = 0
                        process_complete_data(complete_data)
                    return
            except ValueError as ve:
                print(f'[BLE] Chunk parse error: {ve}')
                return
        process_complete_data(data_str)
    except Exception as e:
        print(f'[BLE] Write error: {e}')
        send_notification({"type": "ERROR", "message": str(e)})

def on_read_characteristic():
    result = {"status": "connected"}
    return json.dumps(result).encode('utf-8')

def setup_gatt_and_advertising():
    global _notify_char
    adapter_obj = peripheral.adapter.Adapter()
    app = peripheral.localGATT.Application()
    service = peripheral.localGATT.Service(1, SERVICE_UUID, True)
    write_char = peripheral.localGATT.Characteristic(1, 1, WRITE_CHAR_UUID, [], False, ['write-without-response', 'write'], read_callback=None, write_callback=on_write_characteristic, notify_callback=None)
    _notify_char = peripheral.localGATT.Characteristic(1, 2, NOTIFY_CHAR_UUID, [], False, ['notify'], read_callback=on_read_characteristic, write_callback=None, notify_callback=None)
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
    print(f'[BLE] Advertising as "{DEVICE_NAME}"')
    print(f'[BLE] Using adapter: {adapter_obj.address}')
    threading.Thread(target=lambda: app.start(), daemon=True).start()
    return ad_manager, advert, gatt_manager, app

def main():
    global _mqtt_client
    print("=" * 60); print("BLE Gateway Service Starting..."); print("=" * 60)
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    agent = register_pairing_agent()
    _mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    _mqtt_client.on_connect = on_mqtt_connect
    _mqtt_client.on_message = on_mqtt_message
    _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    _mqtt_client.loop_start()
    try:
        ad_manager, advert, gatt_manager, app = setup_gatt_and_advertising()
        GLib.MainLoop().run()
    finally:
        if _mqtt_client:
            _mqtt_client.loop_stop()
            _mqtt_client.disconnect()

if __name__ == '__main__':
    main()