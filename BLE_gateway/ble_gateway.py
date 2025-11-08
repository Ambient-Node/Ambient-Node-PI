#!/usr/bin/env python3
"""BLE Gateway Service - 청크 수신 지원"""

import json
import threading
import time
import signal
import sys
from datetime import datetime

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    from bluezero import peripheral
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
_chunk_total = 0


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


def on_write_characteristic(value, options):
    """BLE Write 수신 - 청크 처리 포함"""
    global _mqtt_client, _chunk_buffer, _chunk_total

    try:
        data_str = bytes(value).decode('utf-8')
        
        # 청크 헤더 확인
        if data_str.startswith('<CHUNK:') and '>' in data_str:
            header_end = data_str.index('>')
            header = data_str[7:header_end]  # '<CHUNK:' 제거
            
            if header == 'END':
                # 청크 수신 완료
                print(f'[BLE] 청크 수신 완료: 총 {len(_chunk_buffer)}개')
                full_data = ''.join(_chunk_buffer)
                _chunk_buffer = []
                _chunk_total = 0
                
                # 완전한 데이터 처리
                process_complete_data(full_data)
                return
            
            # 청크 번호 파싱
            chunk_info = header.split('/')
            if len(chunk_info) == 2:
                chunk_num = int(chunk_info[0])
                total_chunks = int(chunk_info[1])
                chunk_data = data_str[header_end + 1:]
                
                _chunk_buffer.append(chunk_data)
                _chunk_total = total_chunks
                print(f'[BLE] 청크 수신: {chunk_num + 1}/{total_chunks}')
                return
        
        # 일반 데이터 (청크 아님)
        print(f'[BLE] 수신: {data_str[:100]}...')  # 처음 100자만 출력
        process_complete_data(data_str)

    except Exception as e:
        print(f'[ERROR] {e}')
        import traceback
        traceback.print_exc()


def process_complete_data(data_str):
    """완전한 데이터 처리"""
    global _mqtt_client

    try:
        payload = json.loads(data_str)
    except json.JSONDecodeError:
        print(f'[WARN] Not JSON')
        return

    timestamp = datetime.now().isoformat()
    topic = None
    mqtt_payload = {}

    action = payload.get('action', '')

    # 토픽 매핑
    if action == 'register_user':
        topic = "ambient/user/register"
        mqtt_payload = {
            "user_id": payload.get('name', '').lower().replace(' ', '_'),
            "name": payload.get('name', ''),
            "bluetooth_id": payload.get('bluetooth_id'),
            "image_base64": payload.get('image_base64'),
            "timestamp": timestamp
        }
        print(f'[BLE] 사용자 등록: {mqtt_payload["name"]}')

    elif action == 'select_user':
        topic = "ambient/user/select"
        mqtt_payload = {"user_id": payload.get('user_id'), "timestamp": timestamp}
        print(f'[BLE] 사용자 선택: {mqtt_payload["user_id"]}')

    elif action == 'power' or 'power' in payload:
        topic = "ambient/command/power"
        mqtt_payload = {"state": payload.get('power') or payload.get('state'), "timestamp": timestamp}
        print(f'[BLE] 전원: {mqtt_payload["state"]}')

    elif action == 'speed' or 'speed' in payload:
        topic = "ambient/command/speed"
        mqtt_payload = {"level": payload.get('speed') or payload.get('level'), "timestamp": timestamp}
        print(f'[BLE] 속도: {mqtt_payload["level"]}')

    elif action == 'angle' or action == 'manual_control' or 'direction' in payload:
        topic = "ambient/command/angle"
        mqtt_payload = {"direction": payload.get('direction') or payload.get('angle'), "timestamp": timestamp}
        print(f'[BLE] 각도: {mqtt_payload["direction"]}')

    elif action == 'face_tracking' or 'trackingOn' in payload:
        topic = "ambient/command/face-tracking"
        mqtt_payload = {"enabled": payload.get('trackingOn') or payload.get('enabled'), "timestamp": timestamp}
        print(f'[BLE] 얼굴 추적: {mqtt_payload["enabled"]}')

    elif action == 'stats_request':
        topic = "ambient/db/stats-request"
        mqtt_payload = {"user_id": payload.get('user_id'), "period": payload.get('period', 'day'), "timestamp": timestamp}
        print(f'[BLE] 통계 요청: {mqtt_payload["user_id"]}, 기간: {mqtt_payload["period"]}')

    elif action == 'update_user':
        topic = "ambient/user/update"
        mqtt_payload = {
            "user_id": payload.get('user_id'),
            "name": payload.get('name', ''),
            "image_base64": payload.get('image_base64'),
            "timestamp": timestamp
        }
        print(f'[BLE] 사용자 수정: {mqtt_payload["user_id"]}')
    
    elif action == 'delete_user':
        topic = "ambient/user/delete"
        mqtt_payload = {
            "user_id": payload.get('user_id'),
            "timestamp": timestamp
        }
        print(f'[BLE] 사용자 삭제: {mqtt_payload["user_id"]}')

    else:
        print(f'[WARN] Unknown action: {action}')
        return

    # MQTT 발행
    if _mqtt_client and _mqtt_client.is_connected():
        if topic:
            _mqtt_client.publish(topic, json.dumps(mqtt_payload))
            print(f'[MQTT] Published to {topic}')
            send_notification({"type": "ACK", "topic": topic, "timestamp": timestamp})
        else:
            print(f'[WARN] No topic mapped for action: {action}')
    else:
        print(f'[WARN] MQTT not connected')  

def send_notification(data):
    global _notify_char
    if _notify_char:
        try:
            message = json.dumps(data)
            _notify_char.set_value(message.encode('utf-8'))
        except Exception as e:
            print(f'[NOTIFY ERROR] {e}')


def setup_gatt_and_advertising():
    global _notify_char

    adapter = peripheral.adapter.Adapter()
    app = peripheral.localGATT.Application()
    service = peripheral.localGATT.Service(1, SERVICE_UUID, True)

    write_char = peripheral.localGATT.Characteristic(
        1, 1, WRITE_CHAR_UUID, [], False, ['write'],
        read_callback=None, write_callback=on_write_characteristic, notify_callback=None
    )

    _notify_char = peripheral.localGATT.Characteristic(
        1, 2, NOTIFY_CHAR_UUID, [], False, ['notify'],
        read_callback=None, write_callback=None, notify_callback=None
    )

    app.add_managed_object(service)
    app.add_managed_object(write_char)
    app.add_managed_object(_notify_char)

    gatt_manager = peripheral.GATT.GattManager(adapter.address)
    gatt_manager.register_application(app, {})

    advert = peripheral.advertisement.Advertisement(1, 'peripheral')
    advert.local_name = DEVICE_NAME
    advert.service_UUIDs = [SERVICE_UUID]

    ad_manager = peripheral.advertisement.AdvertisingManager(adapter.address)
    ad_manager.register_advertisement(advert, {})

    print(f'[GATT] Advertising as "{DEVICE_NAME}"')

    threading.Thread(target=lambda: app.start(), daemon=True).start()

    return ad_manager, advert, gatt_manager, app


def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f'[MQTT] Connected')
        topics = [
            "ambient/status/#",
            "ambient/ai/gesture-detected",
            "ambient/ai/face-detected",
            "ambient/ai/face-position",
            "ambient/user/embedding-ready",
            "ambient/user/session-start",
            "ambient/user/session-end",
            "ambient/db/stats-response",
        ]
        for topic in topics:
            client.subscribe(topic)


def on_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        send_notification({
            "type": "STATUS_UPDATE",
            "topic": msg.topic,
            "data": payload,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        print(f'[ERROR] {e}')


def setup_mqtt():
    global _mqtt_client

    _mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    _mqtt_client.on_connect = on_mqtt_connect
    _mqtt_client.on_message = on_mqtt_message

    _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    _mqtt_client.loop_start()
    return True


def signal_handler(sig, frame):
    print('\n[EXIT] Shutting down...')
    if _mqtt_client:
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
    sys.exit(0)


def main():
    print('=' * 60)
    print('BLE Gateway Service')
    print('=' * 60)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_mqtt()
    agent = register_pairing_agent()
    ad_mgr, advert, gatt_mgr, app = setup_gatt_and_advertising()

    print('\n[INFO] BLE Gateway running!')

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        print('\n[EXIT] Shutting down...')


if __name__ == '__main__':
    main()
