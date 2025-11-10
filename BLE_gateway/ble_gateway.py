#!/usr/bin/env python3
"""BLE Gateway Service - 청크 수신 지원, 사용자 선택/해제 처리"""
import base64
import os
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

# 이미지 저장 경로
USER_IMAGES_DIR = "/var/lib/ambient-node/users"


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


def save_base64_image_to_png(base64_str: str, save_dir: str, filename: str) -> str:
    """
    base64 문자열을 디코딩하여 PNG 파일로 저장
    """
    if not os.path.exists(save_dir):
        os.makedirs(save_dir, exist_ok=True)
        print(f"[IMAGE] Created user directory: {save_dir}")
    
    try:
        img_data = base64.b64decode(base64_str)
        save_path = os.path.join(save_dir, filename)
        
        with open(save_path, 'wb') as f:
            f.write(img_data)
        
        print(f"[IMAGE] ✅ Saved user photo at {save_path}")
        return save_path
    except Exception as e:
        print(f"[IMAGE] ❌ Save failed: {e}")
        return ""


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
                print(f'[BLE] ✅ 청크 수신 완료: 총 {len(_chunk_buffer)}개')
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
                
                # 10개마다 또는 마지막에만 로그
                if (chunk_num + 1) % 10 == 0 or (chunk_num + 1) == total_chunks:
                    print(f'[BLE] 청크 수신: {chunk_num + 1}/{total_chunks}')
                return
        
        # 일반 데이터 (청크 아님)
        print(f'[BLE] 📥 일반 데이터 수신: {data_str[:100]}...')
        process_complete_data(data_str)

    except Exception as e:
        print(f'[ERROR] {e}')
        import traceback
        traceback.print_exc()


def process_complete_data(data_str):
    """완전한 데이터 처리 - 최신 토픽 구조에 맞게 매핑"""
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

    # 토픽 매핑 (복수형 사용자 액션 통합)
    if action == 'register_user':
        topic = "ambient/user/register"
        user_id = payload.get('name', '').lower().replace(' ', '_')
        base64_img = payload.get('image_base64')
        
        # 이미지 저장 (PNG로 변환)
        image_path = ""
        if base64_img:
            user_dir = os.path.join(USER_IMAGES_DIR, user_id)
            filename = "face_001.png"
            image_path = save_base64_image_to_png(base64_img, user_dir, filename)
        
        mqtt_payload = {
            "user_id": user_id,
            "name": payload.get('name', ''),
            "bluetooth_id": payload.get('bluetooth_id', ''),
            "image_path": image_path,  # 파일 시스템 경로
            "image_base64": base64_img,  # 백업용
            "timestamp": timestamp
        }
        print(f'[BLE] 🔐 사용자 등록: {mqtt_payload["name"]} (ID: {user_id})')

    elif action == 'select_users':
        topic = "ambient/user/select"
        user_list = payload.get('users', [])
        
        if len(user_list) == 0:
            print("[WARN] Empty user list in select_users")
            return
        
        mqtt_payload = {
            "user_list": user_list,
            "count": len(user_list),
            "timestamp": timestamp
        }
        print(f'[BLE] 👥 사용자 선택: {len(user_list)}명')

    elif action == 'deselect_users' or action == 'clearselection':
        topic = "ambient/user/deselect"
        mqtt_payload = {
            "user_list": [],  # 빈 리스트로 해제 처리
            "timestamp": timestamp
        }
        print(f'[BLE] ❌ 사용자 선택 해제')

    elif action == 'speed' or 'speed' in payload:
        topic = "ambient/command/speed"
        mqtt_payload = {
            "level": int(payload.get('speed') or payload.get('level', 0)),
            "timestamp": timestamp
        }
        print(f'[BLE] 💨 속도 설정: {mqtt_payload["level"]}')

    elif action == 'angle' or 'manual_control' in payload or 'direction' in payload:
        topic = "ambient/command/angle"
        direction = payload.get('direction') or payload.get('angle', 'center')
        mqtt_payload = {
            "direction": direction,
            "timestamp": timestamp
        }
        print(f'[BLE] 🔄 각도 조절: {direction}')

    elif action == 'stats_request':
        topic = "ambient/db/stats-request"
        mqtt_payload = {
            "user_id": payload.get('user_id', ''),
            "period": payload.get('period', 'day'),
            "timestamp": timestamp
        }
        print(f'[BLE] 📊 통계 요청: {mqtt_payload["user_id"]} ({mqtt_payload["period"]})')

    else:
        print(f'[WARN] Unknown action: {action}')
        send_notification({"type": "ERROR", "message": f"Unknown action: {action}"})
        return

    # MQTT 발행 및 ACK 전송
    if _mqtt_client and _mqtt_client.is_connected():
        if topic and mqtt_payload:
            _mqtt_client.publish(topic, json.dumps(mqtt_payload))
            print(f'[MQTT] 📤 Published to {topic}')
            
            # 성공 ACK 전송
            send_notification({
                "type": "ACK",
                "action": action,
                "topic": topic,
                "data": mqtt_payload,
                "timestamp": timestamp
            })
        else:
            print(f'[WARN] No valid topic or payload for action: {action}')
            send_notification({
                "type": "ERROR",
                "message": f"No topic for {action}",
                "timestamp": timestamp
            })
    else:
        print(f'[WARN] MQTT not connected')
        send_notification({
            "type": "ERROR",
            "message": "MQTT not connected",
            "timestamp": timestamp
        })


def send_notification(data):
    """BLE Notification 발송"""
    global _notify_char
    if _notify_char:
        try:
            message = json.dumps(data)
            _notify_char.set_value(message.encode('utf-8'))
            print(f'[NOTIFY] 📤 Sent: {message[:100]}...')
        except Exception as e:
            print(f'[NOTIFY ERROR] {e}')


def setup_gatt_and_advertising():
    """GATT 서비스 및 광고 설정"""
    global _notify_char

    adapter = peripheral.adapter.Adapter()
    app = peripheral.localGATT.Application()
    service = peripheral.localGATT.Service(1, SERVICE_UUID, True)

    write_char = peripheral.localGATT.Characteristic(
        1, 1, WRITE_CHAR_UUID, [], False, ['write-without-response', 'write'],
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
    advert.service_uuids = [SERVICE_UUID]

    ad_manager = peripheral.advertisement.AdvertisingManager(adapter.address)
    ad_manager.register_advertisement(advert, {})

    print(f'[GATT] 📡 Advertising as "{DEVICE_NAME}"')
    
    threading.Thread(target=lambda: app.start(), daemon=True).start()
    return ad_manager, advert, gatt_manager, app


def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    """MQTT 연결 성공 - App Sub 토픽 구독"""
    if reason_code == 0:
        print(f'[MQTT] ✅ Connected to {MQTT_BROKER}:{MQTT_PORT}')
        
        topics = [
            "ambient/status/speed",
            "ambient/status/tracking", 
            "ambient/user/embedding-ready",
            "ambient/db/stats-response",
        ]
        
        for topic in topics:
            client.subscribe(topic)
            print(f'[MQTT] 📬 Subscribed to {topic}')
    else:
        print(f'[MQTT] ❌ Connection failed: {reason_code}')


def on_mqtt_message(client, userdata, msg):
    """MQTT 메시지 수신 - App Sub 토픽에서 BLE Notification으로 전달"""
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        print(f'[MQTT] 📥 Received on {msg.topic}: {payload}')
        
        send_notification({
            "type": "STATUS_UPDATE",
            "topic": msg.topic,
            "data": payload,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        print(f'[ERROR] MQTT message error: {e}')


def setup_mqtt():
    """MQTT 클라이언트 설정"""
    global _mqtt_client
    
    _mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    _mqtt_client.on_connect = on_mqtt_connect
    _mqtt_client.on_message = on_mqtt_message
    
    _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    _mqtt_client.loop_start()
    return True


def signal_handler(sig, frame):
    """종료 시그널 핸들러"""
    print('\n[EXIT] Shutting down...')
    if _mqtt_client:
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
    sys.exit(0)


def main():
    print('=' * 60)
    print('BLE Gateway Service')
    print('=' * 60)
    print(f'Device Name: {DEVICE_NAME}')

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_mqtt()
    agent = register_pairing_agent()
    ad_mgr, advert, gatt_mgr, app = setup_gatt_and_advertising()

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        print('\n[EXIT] User interrupt')


if __name__ == '__main__':
    main()
