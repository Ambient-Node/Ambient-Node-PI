#!/usr/bin/env python3
"""BLE Gateway Service - 청크 인덱스 및 JSON 파싱 수정됨"""

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

# 청크 수신 버퍼
# 리스트 형태로 관리 [ "chunk0", "chunk1", ... ]
_chunk_buffer = [] 
_expected_chunks = 0

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
        pass
    
    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        return
    
    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        return
    
    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Cancel(self):
        pass

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
    return agent


# ========================================
# 이미지 저장
# ========================================
def save_base64_image_to_png(base64_str: str, save_dir: str, filename: str) -> str:
    if not os.path.exists(save_dir):
        os.makedirs(save_dir, exist_ok=True)
    
    try:
        # 패딩 보정
        missing_padding = len(base64_str) % 4
        if missing_padding:
            base64_str += '=' * (4 - missing_padding)
        
        img_data = base64.b64decode(base64_str)
        
        # 유효성 검증
        try:
            img = Image.open(io.BytesIO(img_data))
            img.verify()
        except Exception:
            print(f"[IMAGE] Invalid image data")
            return ""
        
        save_path = os.path.join(save_dir, filename)
        with open(save_path, 'wb') as f:
            f.write(img_data)
        
        print(f"[IMAGE] Saved: {save_path}")
        return save_path
    
    except Exception as e:
        print(f"[IMAGE] Save failed: {e}")
        return ""


# ========================================
# MQTT 핸들러
# ========================================
def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f'[MQTT] ✅ Connected')
        client.subscribe("ambient/user/register-ack")
        client.subscribe("ambient/session/active")
        client.subscribe("ambient/stats/response")
        client.subscribe("ambient/ai/face-detected")
        client.subscribe("ambient/ai/face-lost")

def on_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        
        # 토픽별 응답 처리 (Notification)
        if msg.topic == "ambient/user/register-ack":
            send_notification({
                "type": "REGISTER_ACK",
                "success": payload.get('success', False),
                "user_id": payload.get('user_id'),
                "error": payload.get('error')
            })
        elif msg.topic == "ambient/ai/face-detected":
            # 앱 UI용 간단 알림
            send_notification({
                "type": "FACE_DETECTED",
                "user_id": payload.get('user_id')
            })
        elif msg.topic == "ambient/session/active":
             send_notification({
                "type": "SESSION_UPDATE",
                "session_id": payload.get('session_id'),
                "user_list": payload.get('user_list')
            })
            
    except Exception as e:
        print(f"[MQTT] Msg error: {e}")

def send_notification(data: dict):
    global _notify_char
    if _notify_char:
        try:
            payload = json.dumps(data)
            _notify_char.set_value(payload.encode('utf-8'))
        except Exception as e:
            print(f"[BLE] Notify error: {e}")


# ========================================
# 데이터 처리 로직
# ========================================
def process_complete_data(data_str):
    global _mqtt_client

    try:
        payload = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f'[WARN] JSON parse error: {e}')
        # 데이터 앞부분 일부 출력해 디버깅
        print(f'[DEBUG] Received Data (first 50): {data_str[:50]}')
        send_notification({"type": "ERROR", "message": "Invalid JSON"})
        return

    timestamp = datetime.now().isoformat()
    action = payload.get('action', '')
    
    topic = None
    mqtt_payload = {}

    if action == 'user_register':
        user_id = payload.get('user_id')
        # 앱이 user_id를 안 보냈을 경우 대비
        if not user_id:
            user_id = f"user_{int(time.time())}"
            
        username = payload.get('name', 'Unknown')
        base64_img = payload.get('image_base64')
        
        image_path = ""
        if base64_img:
            user_dir = os.path.join(USER_IMAGES_DIR, user_id)
            filename = f"{user_id}.png"
            image_path = save_base64_image_to_png(base64_img, user_dir, filename)
        
        topic = "ambient/user/register"
        mqtt_payload = {
            "user_id": user_id,
            "username": username,
            "image_path": image_path,
            "timestamp": timestamp
        }
        print(f'[BLE] Register request: {username}')

    elif action == 'speed_change':
        speed = payload.get('speed', 0)
        topic = "ambient/command/speed"
        mqtt_payload = {"event_type": "speed_change", "speed": speed, "timestamp": timestamp}
        print(f'[BLE] Speed: {speed}')

    elif action == 'mode_change':
        mode = payload.get('mode', 'manual')
        topic = "ambient/command/mode"
        mqtt_payload = {"event_type": "mode_change", "mode": mode, "timestamp": timestamp}
        print(f'[BLE] Mode: {mode}')

    elif action == 'user_select':
        user_list = payload.get('users', [])
        topic = "ambient/user/select"
        mqtt_payload = {"event_type": "user_select", "user_list": user_list, "timestamp": timestamp}
        print(f'[BLE] User select: {len(user_list)} users')

    else:
        print(f'[WARN] Unknown action: {action}')
        return

    # MQTT Publish
    if _mqtt_client and _mqtt_client.is_connected() and topic:
        _mqtt_client.publish(topic, json.dumps(mqtt_payload), qos=1)
        # ACK for command actions
        if action in ['speed_change', 'mode_change', 'user_select']:
            send_notification({"type": "ACK", "action": action, "success": True})


# ========================================
# BLE Write 수신
# ========================================
def on_write_characteristic(value, options):
    """BLE Write 수신 - 청크 인덱싱 수정됨"""
    global _chunk_buffer, _expected_chunks
    
    try:
        data_str = bytes(value).decode('utf-8')
        
        # 1. 청크 데이터 확인 (<CHUNK:0/100>...)
        if data_str.startswith('<CHUNK:'):
            try:
                # <CHUNK: 제거
                content = data_str[7:]
                if '>' not in content:
                    return # 잘못된 형식

                header_part, chunk_data = content.split('>', 1)
                
                if '/' in header_part:
                    idx_str, total_str = header_part.split('/')
                    current_idx = int(idx_str)
                    total_chunks = int(total_str)
                    
                    # 버퍼 초기화 (새로운 전송 시작)
                    if len(_chunk_buffer) != total_chunks:
                        _chunk_buffer = [''] * total_chunks
                        _expected_chunks = total_chunks
                        # print(f'[BLE] New chunk stream: {total_chunks} chunks')

                    # 데이터 저장 (0-based index 그대로 사용)
                    if 0 <= current_idx < total_chunks:
                        _chunk_buffer[current_idx] = chunk_data
                        
                        # 진행 상황 로그 (너무 자주 찍히지 않게 10개 단위로)
                        if current_idx % 10 == 0 or current_idx == total_chunks - 1:
                            print(f'[BLE] 📦 Chunk {current_idx + 1}/{total_chunks}')
                    
                    # 2. 종료 조건 확인 (<CHUNK:END>가 오거나, 모든 버퍼가 찼을 때)
                    # 여기서는 'END' 패킷을 별도로 기다리지 않고 모든 슬롯이 차면 즉시 처리
                    if all(_chunk_buffer):
                        print(f'[BLE] ✅ All {total_chunks} chunks received. assembling...')
                        complete_data = ''.join(_chunk_buffer)
                        
                        # 버퍼 리셋
                        _chunk_buffer = []
                        _expected_chunks = 0
                        
                        # 데이터 처리
                        process_complete_data(complete_data)
                    return

                elif header_part == 'END':
                    # END 패킷은 무시 (위에서 all() 체크로 처리됨)
                    return

            except ValueError as ve:
                print(f'[BLE] Chunk parse error: {ve}')
                return

        # 3. 일반 데이터 (청크 아님)
        process_complete_data(data_str)
    
    except Exception as e:
        print(f'[BLE] Write error: {e}')
        send_notification({"type": "ERROR", "message": str(e)})


def on_read_characteristic():
    return json.dumps({"status": "connected"}).encode('utf-8')


# ========================================
# 메인 실행
# ========================================
def main():
    global _mqtt_client, _notify_char
    
    print("=" * 60)
    print("BLE Gateway Service Starting...")
    print("=" * 60)
    
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    
    agent = register_pairing_agent()
    
    _mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    _mqtt_client.on_connect = on_mqtt_connect
    _mqtt_client.on_message = on_mqtt_message
    _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    _mqtt_client.loop_start()
    
    try:
        app = peripheral.Peripheral(DEVICE_NAME, local_name=DEVICE_NAME)
        app.add_service(srv_id=1, uuid=SERVICE_UUID, primary=True)
        
        app.add_characteristic(srv_id=1, chr_id=1, uuid=WRITE_CHAR_UUID,
            value=[], notifying=False, flags=['write', 'write-without-response'],
            write_callback=on_write_characteristic)
        
        _notify_char = app.add_characteristic(srv_id=1, chr_id=2, uuid=NOTIFY_CHAR_UUID,
            value=[], notifying=True, flags=['notify', 'read'],
            read_callback=on_read_characteristic)
        
        app.publish()
        GLib.MainLoop().run()
        
    finally:
        if _mqtt_client:
            _mqtt_client.loop_stop()

if __name__ == '__main__':
    main()