# BLE Gateway 설정 가이드

## 개요

이 시스템은 **BLE Gateway**를 라즈베리파이 호스트에서 실행하고, MQTT를 통해 Docker 컨테이너들과 통신하는 구조입니다.

```
Flutter 앱 (BLE Client)
    ↕ BLE 통신
라즈베리파이 호스트 (ble_gateway.py)
    ↕ MQTT
Docker 컨테이너들 (fan-service, db-service)
```

## 아키텍처

### 1. BLE Gateway (`ble_gateway.py`)
- **위치**: 라즈베리파이 호스트에서 실행
- **역할**:
  - Flutter 앱과 BLE 통신
  - 페어링 처리 (고정 PIN: 123456)
  - BLE 명령을 MQTT로 변환하여 컨테이너에 전달
  - 컨테이너의 상태를 BLE Notification으로 앱에 전달

### 2. Fan Service (컨테이너)
- **역할**:
  - MQTT 명령 수신 (속도, 추적, 수동 제어 등)
  - GPIO 제어 (팬, 모터)
  - 상태를 MQTT로 발행

### 3. DB Service (컨테이너)
- **역할**:
  - MQTT 이벤트 수신 및 DB 저장
  - 사용자 등록, 세션 관리

## 설치 방법

### 1. BLE Gateway 설치

라즈베리파이에서 다음 명령 실행:

```bash
cd /path/to/ambient-node/rpi
chmod +x setup_ble_gateway.sh
./setup_ble_gateway.sh
```

이 스크립트는:
- 필요한 시스템 패키지 설치 (bluez, python3-dbus 등)
- Python 패키지 설치 (paho-mqtt)
- Bluetooth 활성화 및 설정
- systemd 서비스 등록 및 시작

### 2. Docker 컨테이너 시작

```bash
cd /path/to/ambient-node/rpi
docker-compose up -d
```

## BLE Gateway 관리

### 서비스 상태 확인
```bash
sudo systemctl status ambient-ble-gateway
```

### 로그 확인 (실시간)
```bash
sudo journalctl -u ambient-ble-gateway -f
```

### 서비스 재시작
```bash
sudo systemctl restart ambient-ble-gateway
```

### 서비스 중지
```bash
sudo systemctl stop ambient-ble-gateway
```

### 서비스 비활성화 (자동 시작 해제)
```bash
sudo systemctl disable ambient-ble-gateway
```

## MQTT 토픽 구조

### BLE Gateway → 컨테이너

| 토픽 | 설명 | 예시 페이로드 |
|------|------|---------------|
| `ambient/fan001/cmd/speed` | 팬 속도 제어 | `{"level": 50, "timestamp": "..."}` |
| `ambient/fan001/cmd/face-tracking` | 얼굴 추적 설정 | `{"enabled": true, "timestamp": "..."}` |
| `ambient/fan001/cmd/manual` | 수동 제어 | `{"direction": "left", "timestamp": "..."}` |
| `ambient/user/register` | 사용자 등록 | `{"user_id": "...", "name": "...", "image_base64": "..."}` |

### 컨테이너 → BLE Gateway

| 토픽 | 설명 | 예시 페이로드 |
|------|------|---------------|
| `ambient/fan001/status/speed` | 팬 속도 상태 | `{"level": 50, "timestamp": "..."}` |
| `ambient/fan001/status/power` | 전원 상태 | `{"state": "on", "timestamp": "..."}` |
| `ambient/fan001/status/angle` | 모터 각도 | `{"horizontal": 90, "vertical": 90}` |
| `ambient/ai/face-detected` | 얼굴 감지 | `{"user_id": "...", "angle_h": 90, "angle_v": 90}` |

## Flutter 앱 연결

### 1. 앱에서 BLE 스캔
- 기기 이름: `AmbientNode`
- 자동으로 검색됨

### 2. 연결 및 페어링
- 앱에서 연결 시도
- OS 페어링 다이얼로그에서 PIN 입력: **123456**

### 3. 데이터 전송
- 앱에서 JSON 데이터 전송
- BLE Gateway가 MQTT로 변환하여 컨테이너에 전달

## 트러블슈팅

### BLE Gateway가 시작되지 않음
```bash
# 로그 확인
sudo journalctl -u ambient-ble-gateway -n 50

# Bluetooth 상태 확인
sudo systemctl status bluetooth

# Bluetooth 재시작
sudo systemctl restart bluetooth
```

### Flutter 앱에서 기기를 찾을 수 없음
```bash
# Bluetooth가 discoverable인지 확인
sudo bluetoothctl
> discoverable on
> pairable on
> exit

# BLE Gateway 재시작
sudo systemctl restart ambient-ble-gateway
```

### MQTT 연결 실패
```bash
# MQTT 브로커 상태 확인
docker ps | grep mqtt

# MQTT 브로커 로그 확인
docker logs ambient-mqtt-broker

# 포트 확인
netstat -tuln | grep 1883
```

### 컨테이너가 명령을 받지 못함
```bash
# 컨테이너 로그 확인
docker logs ambient-fan-service -f

# MQTT 메시지 모니터링 (호스트에서)
mosquitto_sub -h localhost -t 'ambient/#' -v
```

## 개발 모드

개발 중에는 systemd 서비스 대신 직접 실행 가능:

```bash
cd /path/to/ambient-node/rpi
python3 ble_gateway.py
```

종료: `Ctrl+C`

## 파일 구조

```
rpi/
├── ble_gateway.py                  # BLE Gateway 메인 코드
├── ambient-ble-gateway.service     # systemd 서비스 파일
├── setup_ble_gateway.sh            # 설치 스크립트
├── docker-compose.yml              # Docker 컨테이너 설정
├── fan-service/
│   └── fan_service.py              # 팬 제어 서비스 (MQTT 전용)
└── db-service/
    └── db_service.py               # DB 서비스
```

## UUID 정보

BLE 서비스 및 특성 UUID (Flutter 앱과 동일):

- **Service UUID**: `12345678-1234-5678-1234-56789abcdef0`
- **Write Characteristic UUID**: `12345678-1234-5678-1234-56789abcdef1`
- **Notify Characteristic UUID**: `12345678-1234-5678-1234-56789abcdef2`

## 보안

- 고정 PIN: **123456** (프로덕션 환경에서는 변경 권장)
- BLE 암호화 필수 (`encrypt-write` 플래그)
- MQTT는 현재 인증 없음 (필요시 mosquitto.conf에서 설정)
