# Ambient Node Raspberry Pi 서비스

## 📁 프로젝트 구조

```
/home/pi/ambient-node/
├── docker-compose.yml          # 모든 컨테이너 정의
├── fan-service/                # Hardware Container
│   ├── Dockerfile
│   └── fan_service.py          # BLE → GPIO → MQTT
├── db-service/                 # Database Container
│   ├── Dockerfile
│   └── db_service.py          # SQLite + MQTT 구독
└── mqtt-broker/                # MQTT Broker
    └── mosquitto.conf         # Mosquitto 설정

/var/lib/ambient-node/          # 호스트 영속 데이터
├── users/                      # 사용자 사진
│   └── {user_id}/
│       └── face.jpg
├── db.sqlite                   # SQLite 데이터베이스
└── mqtt/                       # MQTT 데이터
    ├── data/
    └── log/
```

## 🚀 설치 및 실행

### 1. 필요한 패키지 설치

```bash
# Docker 설치 (아직 안 했다면)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Docker Compose 설치
sudo apt-get install docker-compose -y
```

### 2. 디렉토리 생성

```bash
sudo mkdir -p /var/lib/ambient-node/{users,mqtt/{data,log}}
sudo chown -R $USER:$USER /var/lib/ambient-node
```

### 3. 서비스 시작

```bash
cd /home/pi/ambient-node
docker-compose up -d
```

### 4. 로그 확인

```bash
# 모든 서비스 로그
docker-compose logs -f

# 특정 서비스 로그
docker-compose logs -f fan-service
docker-compose logs -f db-service
docker-compose logs -f mqtt-broker
```

### 5. 서비스 중지

```bash
docker-compose down
```

## 🔧 설정

### GPIO 핀 설정 수정

`fan-service/fan_service.py`에서 GPIO 핀 번호를 수정할 수 있습니다:

```python
FAN_PWM_PIN = 18      # 팬 속도 제어 (PWM)
MOTOR_STEP_PIN = 21   # 회전 모터 스텝
MOTOR_DIR_PIN = 20    # 회전 모터 방향
```

### MQTT 브로커 설정

`mqtt-broker/mosquitto.conf`에서 포트, 로그 레벨 등을 수정할 수 있습니다.

## 📊 데이터베이스 접근

```bash
# SQLite 데이터베이스 확인
sqlite3 /var/lib/ambient-node/db.sqlite

# 테이블 목록
.tables

# 사용자 목록
SELECT * FROM users;

# 이벤트 로그
SELECT * FROM device_events ORDER BY timestamp DESC LIMIT 10;

# 통계
SELECT 
    COUNT(*) as total_users,
    (SELECT COUNT(*) FROM device_events) as total_events,
    (SELECT COUNT(*) FROM user_sessions WHERE session_end IS NULL) as active_sessions
FROM users;
```

## 🔍 트러블슈팅

### GPIO 권한 문제

Hardware Container는 `privileged: true` 모드로 실행됩니다. GPIO 접근이 안 되면:

```bash
# GPIO 권한 확인
ls -l /sys/class/gpio/

# 필요시 사용자를 gpio 그룹에 추가
sudo usermod -aG gpio $USER
```

### BLE 연결 안 됨

```bash
# BLE 서비스 상태 확인
sudo systemctl status bluetooth

# BLE 어댑터 활성화
sudo bluetoothctl
[bluetooth]# power on
[bluetooth]# pairable on
[bluetooth]# discoverable on
```

### MQTT 연결 안 됨

```bash
# MQTT 브로커 로그 확인
docker-compose logs mqtt-broker

# MQTT 테스트 (다른 터미널에서)
mosquitto_sub -h localhost -t "#" -v
```

### 컨테이너 재시작

```bash
# 특정 서비스만 재시작
docker-compose restart fan-service
docker-compose restart db-service

# 모든 서비스 재시작
docker-compose restart
```

## 🔄 데이터 흐름

1. **Flutter App** → **BLE** → **Hardware Container**
   - 팬 제어: `{"speed": 50, "trackingOn": true}`
   - 사용자 등록: `{"action": "register_user", "name": "...", "image_base64": "..."}`
   - 수동 제어: `{"action": "manual_control", "direction": "up"}`

2. **Hardware Container** → **GPIO** (팬/모터 제어)
   - PWM으로 팬 속도 제어
   - 스텝 모터로 각도 제어

3. **Hardware Container** → **MQTT** (상태/이벤트 발행)
   - `ambient/command/*` - 제어 명령
   - `ambient/status/*` - 상태 업데이트
   - `ambient/user/register` - 사용자 등록
   - `ambient/db/log-event` - 이벤트 로깅

4. **MQTT Broker** → **DB Container**
   - 모든 이벤트를 SQLite에 저장

5. **MQTT Broker** → **AI Container** (추후)
   - 얼굴 감지 알림

6. **AI Container** → **MQTT** → **Hardware Container**
   - `ambient/ai/face-detected` → 모터 자동 회전

## 📝 TODO

- [ ] AI Container 추가 (얼굴 인식)
- [ ] 웹 대시보드 추가
- [ ] 통계 API 엔드포인트
- [ ] 이미지 리사이징 최적화
- [ ] BLE 페어링 개선

