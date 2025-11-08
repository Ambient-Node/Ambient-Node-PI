#!/usr/bin/env python3
"""
BLE Gateway Service (Host에서 실행)
- Flutter 앱과 BLE 통신
- MQTT 브로커를 통해 컨테이너들과 통신
- 페어링 및 데이터 중계
"""

import json
import threading
import time
import signal
import sys
from datetime import datetime

# BLE 관련
try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    from bluezero import peripheral
    BLE_AVAILABLE = True
except ImportError as e:
    print(f"[ERROR] BLE libraries not available: {e}")
    print("[ERROR] Install: sudo apt install python3-dbus python3-gi python3-bluezero")
    sys.exit(1)

# MQTT 관련
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError as e:
    print(f"[ERROR] MQTT library not available: {e}")
    print("[ERROR] Install: pip3 install paho-mqtt")
    sys.exit(1)

# Configuration
MQTT_BROKER = "localhost"  # 호스트에서 실행되므로 localhost 사용
MQTT_PORT = 1883
MQTT_CLIENT_ID = "ble-gateway"

# BLE Configuration (Flutter 앱과 동일하게 설정)
SERVICE_UUID = '12345678-1234-5678-1234-56789abcdef0'
WRITE_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef1'
NOTIFY_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef2'
DEVICE_NAME = 'AmbientNode'
FIXED_PASSKEY = 123456  # Fixed 6-digit PIN

# Global state
_notify_char = None
_mqtt_client = None
_agent_path = '/ambient/agent'


class PairingAgent(dbus.service.Object):
    """
    BlueZ Agent for Android bonding
    - KeyboardDisplay mode: RPi provides passkey, phone inputs
    """
    
    def __init__(self, bus):
        super().__init__(bus, _agent_path)
        self.pending_device = None
    
    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Release(self):
        print('[AGENT] Released')
    
    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        """Android requests bonding -> Return fixed passkey & send Notification"""
        print(f'[AGENT] RequestPasskey for {device} -> Returning {FIXED_PASSKEY}')
        self._send_pin_notification(FIXED_PASSKEY)
        return dbus.UInt32(FIXED_PASSKEY)
    
    @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
    def DisplayPasskey(self, device, passkey):
        """BlueZ requests to display passkey"""
        print(f'[AGENT] DisplayPasskey for {device}: {passkey:06d}')
        self._send_pin_notification(FIXED_PASSKEY)
    
    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        """Service usage authorization -> Auto-approve"""
        print(f'[AGENT] RequestAuthorization for {device} -> Approved')
        return
    
    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        """Specific service authorization -> Auto-approve"""
        print(f'[AGENT] AuthorizeService {uuid} for {device} -> Approved')
        return
    
    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Cancel(self):
        print('[AGENT] Pairing canceled by BlueZ')
    
    def _send_pin_notification(self, pin):
        """Send PIN to Android via Notification"""
        global _notify_char
        if _notify_char is None:
            print('[WARN] Notification characteristic not ready')
            return
        
        try:
            message = json.dumps({
                "type": "PAIRING_PIN",
                "pin": f"{pin:06d}",
                "message": f"Please enter PIN: {pin:06d}"
            })
            _notify_char.set_value(message.encode('utf-8'))
            print(f'[NOTIFY] Sent PIN to Android: {pin:06d}')
        except Exception as e:
            print(f'[NOTIFY ERROR] {e}')


def register_pairing_agent():
    """Register bonding Agent with BlueZ"""
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    agent = PairingAgent(bus)
    
    manager = dbus.Interface(
        bus.get_object('org.bluez', '/org/bluez'),
        'org.bluez.AgentManager1'
    )
    
    manager.RegisterAgent(_agent_path, 'KeyboardDisplay')
    manager.RequestDefaultAgent(_agent_path)
    
    print(f'[AGENT] Registered as KeyboardDisplay. Fixed PIN: {FIXED_PASSKEY:06d}')
    return agent


def on_write_characteristic(value, options):
    """
    BLE Write Characteristic 콜백
    Flutter 앱에서 전송한 데이터를 MQTT로 중계
    """
    global _mqtt_client
    
    try:
        data_str = bytes(value).decode('utf-8')
        print(f'[BLE] 📥 Received: {data_str}')
        
        # JSON 파싱
        try:
            payload = json.loads(data_str)
        except json.JSONDecodeError:
            print(f'[WARN] Not JSON, treating as plain text')
            payload = {"raw": data_str}
        
        timestamp = datetime.now().isoformat()
        
        # MQTT로 전달 (토픽 결정)
        if 'action' in payload:
            action = payload['action']
            
            if action == 'register_user':
                # 사용자 등록
                topic = "ambient/user/register"
                mqtt_payload = {
                    "user_id": payload.get('name', '').lower().replace(' ', '_'),
                    "name": payload.get('name', ''),
                    "bluetooth_id": payload.get('bluetooth_id'),
                    "image_base64": payload.get('image_base64') or payload.get('imagePath'),
                    "timestamp": timestamp
                }
                
            elif action == 'manual_control':
                # 수동 제어
                topic = "ambient/fan001/cmd/manual"
                mqtt_payload = {
                    "direction": payload.get('direction'),
                    "timestamp": timestamp
                }
                
            else:
                # 기타 액션
                topic = "ambient/app/command"
                mqtt_payload = payload
                mqtt_payload['timestamp'] = timestamp
        
        elif 'speed' in payload:
            # 팬 속도 제어
            topic = "ambient/fan001/cmd/speed"
            mqtt_payload = {
                "level": payload['speed'],
                "timestamp": timestamp
            }
        
        elif 'trackingOn' in payload:
            # 얼굴 추적
            topic = "ambient/fan001/cmd/face-tracking"
            mqtt_payload = {
                "enabled": payload['trackingOn'],
                "timestamp": timestamp
            }
        
        else:
            # 기본 명령
            topic = "ambient/app/command"
            mqtt_payload = payload
            mqtt_payload['timestamp'] = timestamp
        
        # MQTT 발행
        if _mqtt_client and _mqtt_client.is_connected():
            _mqtt_client.publish(topic, json.dumps(mqtt_payload))
            print(f'[MQTT] 📤 Published to {topic}: {mqtt_payload}')
            
            # ACK 전송
            send_notification({
                "type": "ACK",
                "timestamp": timestamp
            })
        else:
            print('[ERROR] MQTT client not connected')
            send_notification({
                "type": "ERROR",
                "message": "MQTT not connected"
            })
        
    except Exception as e:
        print(f'[ERROR] BLE write error: {e}')
        import traceback
        traceback.print_exc()


def send_notification(data):
    """BLE Notification 발송"""
    global _notify_char
    if _notify_char is None:
        print('[WARN] Notification characteristic not ready')
        return
    
    try:
        message = json.dumps(data)
        _notify_char.set_value(message.encode('utf-8'))
        print(f'[NOTIFY] 📤 Sent: {message}')
    except Exception as e:
        print(f'[NOTIFY ERROR] {e}')


def setup_gatt_and_advertising():
    """Setup GATT service and Advertising"""
    global _notify_char
    
    adapter = peripheral.adapter.Adapter()
    adapter_address = adapter.address
    
    # Create Application
    app = peripheral.localGATT.Application()
    
    # Create Service
    service = peripheral.localGATT.Service(1, SERVICE_UUID, True)
    
    # Write Characteristic (requires encryption -> triggers bonding)
    write_char = peripheral.localGATT.Characteristic(
        1,  # service_id
        1,  # characteristic_id
        WRITE_CHAR_UUID,
        [],  # value (initial)
        False,  # writable_auxillaries
        ['write', 'encrypt-write'],  # flags: encryption required
        read_callback=None,
        write_callback=on_write_characteristic,
        notify_callback=None,
    )
    
    # Notify Characteristic (RPi -> Android)
    _notify_char = peripheral.localGATT.Characteristic(
        1,  # service_id
        2,  # characteristic_id
        NOTIFY_CHAR_UUID,
        [],
        False,
        ['notify'],
        read_callback=None,
        write_callback=None,
        notify_callback=None,
    )
    
    # Add to Application
    app.add_managed_object(service)
    app.add_managed_object(write_char)
    app.add_managed_object(_notify_char)
    
    # Register GATT Manager
    gatt_manager = peripheral.GATT.GattManager(adapter_address)
    gatt_manager.register_application(app, {})
    
    # Setup Advertising
    advert = peripheral.advertisement.Advertisement(1, 'peripheral')
    advert.local_name = DEVICE_NAME
    advert.service_UUIDs = [SERVICE_UUID]
    
    ad_manager = peripheral.advertisement.AdvertisingManager(adapter_address)
    ad_manager.register_advertisement(advert, {})
    
    print(f'[GATT] 📡 Advertising as "{DEVICE_NAME}"')
    print(f'[GATT] Service UUID: {SERVICE_UUID}')
    print(f'[GATT] Write UUID: {WRITE_CHAR_UUID}')
    print(f'[GATT] Notify UUID: {NOTIFY_CHAR_UUID}')
    
    # Start Application (in separate thread)
    def start_app():
        try:
            app.start()
        except Exception as e:
            print(f'[GATT ERROR] app.start() failed: {e}')
    
    threading.Thread(target=start_app, daemon=True).start()
    
    return ad_manager, advert, gatt_manager, app


def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    """MQTT 연결 성공"""
    if reason_code == 0:
        print(f'[MQTT] ✅ Connected to broker at {MQTT_BROKER}:{MQTT_PORT}')
        
        # 상태 토픽 구독 (컨테이너에서 앱으로 전달할 데이터)
        topics = [
            "ambient/fan001/status/#",
            "ambient/ai/face-detected",
            "ambient/db/stats-response",
        ]
        
        for topic in topics:
            client.subscribe(topic)
            print(f'[MQTT] 📬 Subscribed to {topic}')
    else:
        print(f'[MQTT] ❌ Connection failed with code: {reason_code}')


def on_mqtt_message(client, userdata, msg):
    """
    MQTT 메시지 수신
    컨테이너에서 온 상태 업데이트를 BLE Notification으로 전달
    """
    try:
        topic = msg.topic
        payload_str = msg.payload.decode('utf-8')
        payload = json.loads(payload_str)
        
        print(f'[MQTT] 📥 Received on {topic}: {payload}')
        
        # BLE Notification으로 전달
        notification_data = {
            "type": "STATUS_UPDATE",
            "topic": topic,
            "data": payload,
            "timestamp": datetime.now().isoformat()
        }
        
        send_notification(notification_data)
        
    except Exception as e:
        print(f'[ERROR] MQTT message error: {e}')


def setup_mqtt():
    """MQTT 클라이언트 설정"""
    global _mqtt_client
    
    try:
        _mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=MQTT_CLIENT_ID
        )
        _mqtt_client.on_connect = on_mqtt_connect
        _mqtt_client.on_message = on_mqtt_message
        
        print(f'[MQTT] 🔄 Connecting to {MQTT_BROKER}:{MQTT_PORT}...')
        _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        _mqtt_client.loop_start()
        
        print('[MQTT] ✅ MQTT client started')
        return True
        
    except Exception as e:
        print(f'[ERROR] MQTT setup failed: {e}')
        return False


def signal_handler(sig, frame):
    """종료 시그널 핸들러"""
    print('\n[EXIT] 🛑 Shutting down...')
    
    if _mqtt_client:
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
    
    sys.exit(0)


def main():
    print('=' * 60)
    print('BLE Gateway Service')
    print('=' * 60)
    print(f'Device Name: {DEVICE_NAME}')
    print(f'Fixed PIN: {FIXED_PASSKEY:06d}')
    print(f'MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}')
    print('=' * 60)
    
    # 시그널 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 1. MQTT 연결
    if not setup_mqtt():
        print('[ERROR] Failed to setup MQTT, exiting...')
        sys.exit(1)
    
    # 2. BLE Agent 등록
    agent = register_pairing_agent()
    
    # 3. GATT 서비스 시작
    ad_mgr, advert, gatt_mgr, app = setup_gatt_and_advertising()
    
    print('\n[INFO] 🚀 BLE Gateway is running!')
    print('[INFO] Bluetooth settings:')
    print('       - pairable on')
    print('       - discoverable on')
    print(f'\n[INFO] From Flutter app:')
    print(f'       1. Scan for "{DEVICE_NAME}" device')
    print(f'       2. Connect and bond')
    print(f'       3. Enter PIN "{FIXED_PASSKEY:06d}" in OS dialog')
    print(f'       4. Send commands via BLE')
    print('\n[INFO] Press Ctrl+C to stop\n')
    
    try:
        # Run GLib main loop (Agent D-Bus processing)
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        print('\n[EXIT] Shutting down...')
    finally:
        try:
            ad_mgr.unregister_advertisement(advert)
            gatt_mgr.unregister_application(app)
        except Exception:
            pass
        
        if _mqtt_client:
            _mqtt_client.loop_stop()
            _mqtt_client.disconnect()
        
        print('[CLEANUP] BLE Gateway stopped.')


if __name__ == '__main__':
    main()
