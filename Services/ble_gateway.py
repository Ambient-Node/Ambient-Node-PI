#!/usr/bin/env python3
"""BLE Gateway Service - 사용자 등록/삭제 및 ACK 처리 완벽 구현"""

import base64
import os
import json
import threading
import time
import signal
import sys
import uuid
import shutil
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

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "ble-gateway"
SERVICE_UUID = '12345678-1234-5678-1234-56789abcdef0'
WRITE_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef1'
NOTIFY_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef2'
DEVICE_NAME = 'AmbientNode'

_notify_char = None
_mqtt_client = None
_agent_path = '/ambient/agent'

_chunk_buffer = []
_expected_total = 0

USER_IMAGES_DIR = "/var/lib/ambient-node/users"

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

def extract_user_id(payload: dict) -> str:
    if 'user_id' in payload and payload['user_id']:
        return payload['user_id']
    user_list = payload.get('user_list', [])
    if user_list and isinstance(user_list, list) and len(user_list) > 0:
        first_user = user_list[0]
        if isinstance(first_user, dict):
            return first_user.get('user_id')
    return None

def send_ack(action, user_id=None, success=True, error=None):
    payload = {
        "type": "ACK",
        "action": action,
        "success": success
    }
    if user_id:
        payload["user_id"] = user_id
    if error:
        payload["error"] = error
        
    send_notification(payload)

def process_complete_data(data_str):
    global _mqtt_client

    try:
        payload = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f'[WARN] JSON parse error: {e}')
        send_notification({"type": "ERROR", "message": "Invalid JSON"})
        return

    timestamp = datetime.now().isoformat()
    action = payload.get('action', '')
    
    user_id = extract_user_id(payload)
    
    topic = None
    mqtt_payload = {}

    if action == 'user_register':
        register_user_id = payload.get('user_id')
        username = payload.get('username', 'Unknown')
        base64_img = payload.get('image_base64')
        
        print(f'[BLE] Registering: {username} ({register_user_id})')
        
        image_path = ""
        if base64_img:
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
        
        send_ack("user_register", user_id=register_user_id, success=True)

    elif action == 'user_delete':
        if user_id:
            print(f'[BLE] Deleting user: {user_id}')
            user_dir = os.path.join(USER_IMAGES_DIR, user_id)
            
            try:
                if os.path.exists(user_dir):
                    shutil.rmtree(user_dir)
                    print(f'[BLE] Directory deleted: {user_dir}')
                
                topic = "ambient/user/delete"
                mqtt_payload = {
                    "user_id": user_id,
                    "timestamp": timestamp
                }
                
                send_ack("user_delete", user_id=user_id, success=True)
                
            except Exception as e:
                print(f'[BLE] Delete failed: {e}')
                send_ack("user_delete", user_id=user_id, success=False, error=str(e))
                return
        else:
            print('[WARN] User delete missing user_id')
            return

    elif action == 'user_update':
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

    elif action == 'mode_change':
        mode = payload.get('mode', 'manual_control')
        cmd_type = payload.get('type', 'motor')
        topic = "ambient/command/mode"
        mqtt_payload = {"event_type": "mode_change", "type": cmd_type, "mode": mode, "user_id": user_id, "timestamp": timestamp}
        send_ack("mode_change", user_id, True)

    elif action == 'speed_change':
        speed = payload.get('speed', 0)
        topic = "ambient/command/speed"
        mqtt_payload = {"event_type": "speed_change", "speed": speed, "user_id": user_id, "timestamp": timestamp}
        send_ack("speed_change", user_id, True)

    elif action == 'direction_change':
        direction = payload.get('direction', 'center')
        toggle_on = payload.get('toggleOn', 0)
        topic = "ambient/command/direction"
        mqtt_payload = {"event_type": "direction_change", "direction": direction, "toggleOn": toggle_on, "user_id": user_id, "timestamp": timestamp}
        send_ack("direction_change", user_id, True)

    elif action == 'user_select':
        user_list = payload.get('user_list', [])
        topic = "ambient/user/select"
        mqtt_payload = {"event_type": "user_select", "user_list": user_list, "timestamp": timestamp}
        send_ack("user_select", user_id, True)
        
    elif action == 'shutdown':
        os.system('sudo shutdown -h now')
        return

    elif action == 'mqtt_publish':
        topic = payload.get('topic')
        mqtt_payload = payload.get('payload')

    else:
        print(f'[WARN] Unknown action: {action}')
        return

    if _mqtt_client and _mqtt_client.is_connected() and topic:
        _mqtt_client.publish(topic, json.dumps(mqtt_payload), qos=1)
        print(f'[MQTT] Published to {topic}')

def on_write_characteristic(value, options):
    global _chunk_buffer, _expected_total
    try:
        data_str = bytes(value).decode('utf-8')
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