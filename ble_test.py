import json
from bluezero import peripheral

SERVICE_UUID = 'XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX'  # 실제 UUID로 교체
CHAR_UUID    = 'XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX'  # 실제 UUID로 교체
DEVICE_NAME = 'AmbientNode'

_last_payload = {}


def on_write(value, options):
    global _last_payload
    try:
        data = bytes(value).decode('utf-8')
        payload = json.loads(data)
        _last_payload = payload

        # 예시: 상태 처리
        power_on = payload.get('powerOn')
        speed = payload.get('speed')
        tracking = payload.get('trackingOn')
        selected_face = payload.get('selectedFaceId')
        manual = payload.get('manual')  # {'x': float, 'y': float}

        # TODO: 이 값을 사용해 모터/서보를 제어하도록 연결
        print('[BLE] state=', payload)
    except Exception as e:
        print('[BLE] write parse error:', e)


def main():
    # 어댑터 주소 확인
    ada = peripheral.adapter.Adapter()
    adapter_addr = ada.address

    # GATT 애플리케이션/서비스/특성 구성 (localGATT 사용)
    app = peripheral.localGATT.Application()
    srv = peripheral.localGATT.Service(1, SERVICE_UUID, True)
    ch = peripheral.localGATT.Characteristic(
        1,                      # service_id
        1,                      # characteristic_id
        CHAR_UUID,
        [],                     # 초기 값 (byte list)
        False,                  # notifying
        ['write', 'write-without-response'],
        read_callback=None,
        write_callback=on_write,
        notify_callback=None,
    )

    app.add_managed_object(srv)
    app.add_managed_object(ch)

    # GATT 매니저에 앱 등록
    gatt_mgr = peripheral.GATT.GattManager(adapter_addr)
    gatt_mgr.register_application(app, {})

    # 광고 설정 및 등록
    advert = peripheral.advertisement.Advertisement(1, 'peripheral')
    advert.local_name = DEVICE_NAME
    advert.service_UUIDs = [SERVICE_UUID]
    ad_mgr = peripheral.advertisement.AdvertisingManager(adapter_addr)
    ad_mgr.register_advertisement(advert, {})

    print('Advertising as', DEVICE_NAME)
    app.start()


if __name__ == '__main__':
    main()


