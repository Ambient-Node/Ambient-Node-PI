# Ambient Node 통합 테스트 요약

## 수정 완료 사항

### 1. Flutter 앱 (main.dart)
✅ **BLE 서비스 통합**
- 더미 BleService 제거, 실제 TestBleService 사용
- 초기 연결 상태를 `false`로 수정 (기존: 하드코딩 `true`)
- BLE 연결 상태 콜백 추가 (연결/해제 시 UI 자동 업데이트)
- 기기 이름 콜백 추가 (연결된 기기 이름 표시)
- DeviceSelectionScreen 연결 로직 활성화

✅ **상세 로그 추가**
- 연결 상태 변경 시: `🔵 [BLE] 연결 상태 변경: true/false`
- 기기 이름 업데이트: `🔵 [BLE] 기기 이름: AmbientNode`
- 데이터 전송: `📤 [BLE] 데이터 전송: {speed: 50, trackingOn: true}`
- 전송 실패: `❌ [BLE] 전송 실패: ...`

### 2. BLE 서비스 (test_ble_service.dart)
✅ **전체 프로세스 로그 추가**
- 초기화: `🔍 [BLE] 초기화 및 연결 시작...`
- 권한 확인: `✅ [BLE] 권한 승인됨`
- 기기 스캔: `📡 [BLE] 발견된 기기: "AmbientNode" (ID: ...)`
- 연결 시도: `🔗 [BLE] 연결 시도 1/3...`
- 본딩: `🔐 [BLE] 본딩 시작...` → `✅ [BLE] 본딩 완료`
- GATT 서비스: `📦 서비스 UUID: ...`, `📝 특성 UUID: ...`
- 데이터 전송: `📤 [BLE] JSON 전송 중: {"speed": 50}`
- Notification: `📬 [BLE] Notification 수신: ...`

### 3. 라즈베리파이 Fan Service (fan_service.py)
✅ **BLE 초기화 로그 강화**
- `🔵 BLE 초기화 시작...`
- `📡 Adapter Address: XX:XX:XX:XX:XX:XX`
- `📦 Service UUID: 12345678-1234-5678-1234-56789abcdef0`
- `✍️ Write Characteristic UUID: ...`
- `🔔 Notify Characteristic UUID: ...`
- `🎉 Advertising as 'AmbientNode'`
- `📢 앱에서 'AmbientNode' 기기를 검색할 수 있습니다`

✅ **데이터 수신/처리 로그**
- `📥 데이터 수신 (raw): {"speed": 50}`
- `📦 파싱된 데이터: {speed: 50, trackingOn: true}`
- `✅ 명령 큐에 추가됨 (큐 크기: 1)`
- `🔧 명령 처리 시작: ...`
- `🌀 풍속 제어 명령: 50`
- `👁️ 얼굴 추적 명령: true`
- `📤 ACK 전송: {type: "ACK", ...}`

### 4. Docker Compose 설정
✅ **BLE 디바이스 접근 권한 추가**
```yaml
fan_service:
  privileged: true
  devices:
    - /dev/ttyAMA0:/dev/ttyAMA0
    - /dev/bluetooth:/dev/bluetooth
    - /dev/hci0:/dev/hci0
  volumes:
    - /var/run/dbus:/var/run/dbus
  environment:
    - DBUS_SYSTEM_BUS_ADDRESS=unix:path=/var/run/dbus/system_bus_socket
```

---

## 테스트 절차

### 1단계: 라즈베리파이 컨테이너 재시작
```bash
cd ~/ambient-node
docker compose down
docker compose up -d
```

### 2단계: Fan Service 로그 확인
```bash
docker compose logs -f fan-service
```

**기대 로그:**
```
[BLE] 🔵 BLE 초기화 시작...
[BLE] 📡 Adapter Address: XX:XX:XX:XX:XX:XX
[BLE] 📦 Service UUID: 12345678-1234-5678-1234-56789abcdef0
[BLE] ✍️ Write Characteristic UUID: 12345678-1234-5678-1234-56789abcdef1
[BLE] 🔔 Notify Characteristic UUID: 12345678-1234-5678-1234-56789abcdef2
[BLE] ✅ GATT Application 등록 완료
[BLE] 🎉 Advertising as 'AmbientNode'
[BLE] 📢 앱에서 'AmbientNode' 기기를 검색할 수 있습니다
```

### 3단계: 앱 실행 및 연결
1. Flutter 앱 실행
2. Dashboard 화면 우측 상단의 **Bluetooth 스위치가 OFF(회색)** 상태 확인
3. Bluetooth 아이콘 또는 스위치 클릭
4. DeviceSelectionScreen에서 "AmbientNode" 검색
5. 기기 클릭하여 연결

**앱 로그 확인 (Flutter Debug Console):**
```
🔍 [BLE] 초기화 및 연결 시작...
✅ [BLE] 권한 승인됨
✅ [BLE] 블루투스 켜짐
🔍 [BLE] 기기 스캔 시작 (5초)...
📡 [BLE] 발견된 기기: "AmbientNode" (ID: ...)
✅ [BLE] 매칭되는 기기 발견: "AmbientNode"
🔗 [BLE] 연결 시도 1/3...
✅ [BLE] 물리적 연결 성공
🔐 [BLE] 본딩 시작...
✅ [BLE] 본딩 완료
🔍 [BLE] GATT 서비스 탐색 중...
📦 서비스 UUID: 12345678-1234-5678-1234-56789abcdef0
✅ [BLE] 서비스 탐색 완료
🎉 [BLE] 연결 성공: "AmbientNode"
🔵 [Main] 연결 상태 업데이트: true
```

**라즈베리파이 로그:**
```
(BLE 연결 시 추가 로그는 없을 수 있음 - 정상)
```

### 4단계: 풍속 제어 테스트
1. 앱에서 풍속 슬라이더를 0 → 50으로 변경

**앱 로그:**
```
📤 [BLE] 데이터 전송: {speed: 50, trackingOn: false}
📤 [BLE] JSON 전송 중: {"speed":50,"trackingOn":false}
✅ [BLE] JSON 전송 성공
```

**라즈베리파이 로그:**
```
[BLE] 📥 데이터 수신 (raw): {"speed":50,"trackingOn":false}
[BLE] 📦 파싱된 데이터: {'speed': 50, 'trackingOn': False}
[BLE] ✅ 명령 큐에 추가됨 (큐 크기: 1)
[BLE] 📤 ACK 전송: {'type': 'ACK', 'timestamp': '2025-11-07T21:30:00'}
[BLE] 🔧 명령 처리 시작: {'speed': 50, 'trackingOn': False}
[BLE] 🌀 풍속 제어 명령: 50
[FAN] Speed: 50%, Power: True
[MQTT] Published to ambient/fan001/status/speed
[MQTT] Published to ambient/fan001/status/power
```

### 5단계: MQTT 메시지 확인 (선택)
**별도 터미널:**
```bash
mosquitto_sub -h localhost -p 1883 -t "#" -v
```

**기대 메시지:**
```
ambient/fan001/status/speed {"level": 50, "timestamp": "..."}
ambient/fan001/status/power {"state": "on", "timestamp": "..."}
ambient/db/log-event {"device_id": "fan001", "event_type": "speed", ...}
```

---

## 문제 해결

### BLE 기기가 앱에서 안 보일 때
1. **라즈베리파이 로그 확인**
   ```bash
   docker compose logs fan-service | grep BLE
   ```
   - `🎉 Advertising as 'AmbientNode'` 메시지가 있는지 확인
   - 에러 메시지가 있는지 확인

2. **컨테이너 내부에서 BLE 디바이스 확인**
   ```bash
   docker exec -it ambient-fan-service ls -la /dev/hci*
   docker exec -it ambient-fan-service ls -la /var/run/dbus/
   ```

3. **호스트 블루투스 상태 확인**
   ```bash
   sudo bluetoothctl
   [bluetooth]# show
   [bluetooth]# power on
   ```

### Dashboard 스위치가 여전히 켜져 있을 때
- 앱을 완전히 종료 후 재실행
- `connected = false`로 초기화되는지 확인

### 데이터 전송이 안 될 때
- 앱 로그에서 `❌ [BLE] 전송 실패: Not connected` 확인
- 연결 상태가 `true`인지 확인
- 라즈베리파이 로그에 `📥 데이터 수신` 메시지가 있는지 확인

---

## 핵심 확인 포인트

✅ **앱 시작 시**: Dashboard 우측 상단 스위치가 **OFF(회색)**
✅ **BLE 연결 후**: 스위치가 **ON(파란색)**으로 변경
✅ **기기 이름**: "AmbientNode"로 표시
✅ **풍속 제어**: 슬라이더 변경 시 라즈베리파이에서 로그 출력
✅ **MQTT 발행**: DB Service가 이벤트 수신 및 저장

---

## 다음 단계

1. ✅ BLE 연결 및 데이터 전송 확인
2. ⬜ 수동 모터 제어 테스트 (상/하/좌/우 버튼)
3. ⬜ 얼굴 추적 ON/OFF 테스트
4. ⬜ 사용자 등록 테스트
5. ⬜ AI 얼굴 감지 시뮬레이션 (MQTT 직접 발행)
