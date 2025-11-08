#!/usr/bin/env python3
"""
Raspberry Pi BLE Server with Fixed PIN Bonding
- Compatible with test_ble_service.dart
- Android creates bond -> RPi returns fixed PIN (123456) via Notification
- User enters PIN in Android OS dialog -> Bonding complete
"""

import json
import threading
from datetime import datetime
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
from bluezero import peripheral

# Configuration (match with test_ble_service.dart)
SERVICE_UUID = '12345678-1234-5678-1234-56789abcdef0'
WRITE_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef1'  # Flutter -> RPi
NOTIFY_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef2'  # RPi -> Flutter
DEVICE_NAME = 'AmbientNode'
FIXED_PASSKEY = 123456  # Fixed 6-digit PIN

_notify_char = None  # Global reference to Notification characteristic

# BlueZ Agent for handling Android bonding requests
AGENT_PATH = '/ambient/agent'

class PairingAgent(dbus.service.Object):
    """
    Agent to handle Android createBond() calls
    - KeyboardDisplay mode: RPi provides passkey, phone inputs
    """
    
    def __init__(self, bus):
        super().__init__(bus, AGENT_PATH)
        self.pending_device = None
    
    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Release(self):
        print('[AGENT] Released')
    
    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        """
        Android requests bonding -> Return fixed passkey & send Notification
        """
        print(f'[AGENT] RequestPasskey for {device} -> Returning {FIXED_PASSKEY}')
        
        # Send PIN via Notification to Android
        self._send_pin_notification(FIXED_PASSKEY)
        
        return dbus.UInt32(FIXED_PASSKEY)
    
    @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
    def DisplayPasskey(self, device, passkey):
        """
        BlueZ requests to display passkey (we ignore, use fixed PIN)
        """
        print(f'[AGENT] DisplayPasskey for {device}: {passkey:06d}')
        # Always send fixed PIN
        self._send_pin_notification(FIXED_PASSKEY)
    
    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        """
        Service usage authorization -> Auto-approve
        """
        print(f'[AGENT] RequestAuthorization for {device} -> Approved')
        return
    
    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        """
        Specific service authorization -> Auto-approve
        """
        print(f'[AGENT] AuthorizeService {uuid} for {device} -> Approved')
        return
    
    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Cancel(self):
        print('[AGENT] Pairing canceled by BlueZ')
    
    def _send_pin_notification(self, pin):
        """
        Send PIN to Android via Notification
        test_ble_service.dart onPairingResponse callback will receive
        """
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
    """
    Register bonding Agent with BlueZ
    - KeyboardDisplay: RPi displays passkey, phone inputs
    """
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    agent = PairingAgent(bus)
    
    manager = dbus.Interface(
        bus.get_object('org.bluez', '/org/bluez'),
        'org.bluez.AgentManager1'
    )
    
    # KeyboardDisplay: peripheral displays passkey + central (phone) inputs
    manager.RegisterAgent(AGENT_PATH, 'KeyboardDisplay')
    manager.RequestDefaultAgent(AGENT_PATH)
    
    print(f'[AGENT] Registered as KeyboardDisplay. Fixed PIN: {FIXED_PASSKEY:06d}')
    return agent


# GATT Service Implementation
def on_write_characteristic(value, options):
    """
    Android -> RPi Write received
    Process data sent by test_ble_service.dart sendJson() method
    """
    try:
        data_str = bytes(value).decode('utf-8')
        payload = json.loads(data_str)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f'[{timestamp}] [WRITE] Received: {payload}')
        
        # Here you can connect to MQTT publishing logic
        # Example: publish_mqtt("ambient/app/command", payload)
        
        # Send response (optional)
        send_notification({
            "type": "ACK",
            "received": payload
        })
        
    except Exception as e:
        print(f'[WRITE ERROR] {e}')


def send_notification(data):
    """
    RPi -> Android Notification
    test_ble_service.dart onPairingResponse callback will receive
    """
    global _notify_char
    if _notify_char is None:
        print('[WARN] Notification characteristic not ready')
        return
    
    try:
        message = json.dumps(data)
        _notify_char.set_value(message.encode('utf-8'))
        print(f'[NOTIFY] Sent: {message}')
    except Exception as e:
        print(f'[NOTIFY ERROR] {e}')


def setup_gatt_and_advertising():
    """
    Setup GATT service and Advertising
    """
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
    
    print(f'[GATT] Advertising as "{DEVICE_NAME}"')
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


# Main
def main():
    print('=' * 60)
    print('Ambient Node BLE Server with Fixed PIN Pairing')
    print('=' * 60)
    print(f'Device Name: {DEVICE_NAME}')
    print(f'Fixed PIN: {FIXED_PASSKEY:06d}')
    print('=' * 60)
    
    # 1. Register BlueZ Agent (bonding handler)
    agent = register_pairing_agent()
    
    # 2. Start GATT service
    ad_mgr, advert, gatt_mgr, app = setup_gatt_and_advertising()
    
    print('\n[INFO] BLE server is running!')
    print('[INFO] Check bluetoothctl settings:')
    print('       - pairable on')
    print('       - discoverable on')
    print(f'\n[INFO] From Android app (test_ble_service.dart):')
    print(f'       1. Scan for "{DEVICE_NAME}" device')
    print(f'       2. Call connectToDevice()')
    print(f'       3. Enter "{FIXED_PASSKEY:06d}" in OS PIN dialog')
    print(f'       4. After bonding, data transfer enabled')
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
        print('[CLEANUP] BLE service stopped.')


if __name__ == '__main__':
    main()
