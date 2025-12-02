# 🌪️ Ambient Node: AI Smart Air Circulator

<div align="center">

**AI 비전 기반 사용자 추적형 스마트 에어서큘레이터**

> **2025 캡스톤 디자인 프로젝트**
>
> 🍓 **Platform:** Raspberry Pi 5 (Bookworm 64-bit)
> 🏗️ **Architecture:** MSA (Micro Service Architecture) + BLE Hybrid

</div>

---

본 프로젝트는 엣지 디바이스(Raspberry Pi)에서 독립적으로 구동되는 **보안형 AI 가전 소프트웨어 스택**입니다.
클라우드 연결 없이 온디바이스 AI로 사용자를 추적하며, 자체 개발한 **BLE 프로토콜**을 통해 모바일 앱과 안정적으로 연동됩니다.

<br>

## 📂 시스템 아키텍처 (System Architecture)

<img width="100%" alt="System Architecture" src="https://github.com/user-attachments/assets/9f7235a8-bba6-4928-8e17-4e2fa2de6287" />

### 🧩 주요 컴포넌트
1.  **Flutter App**: BLE 클라이언트 및 사용자 인터페이스 (UI/UX)
2.  **BLE Gateway**: BLE ↔ MQTT 프로토콜 중계 (Python + bluezero)
3.  **AI Service**: 얼굴 인식 및 실시간 추적 (FaceNet + MediaPipe)
4.  **Fan Service**: 모터 제어 및 하드웨어 통신 (UART)
5.  **DB Service**: 데이터 영속성 관리 및 통계 분석 (PostgreSQL)
6.  **MQTT Broker**: 서비스 간 메시지 버스 (Mosquitto)

<hr>

## 📁 프로젝트 구조 (Directory Structure)

```text
/home/pi/ambient-node/
├── docker-compose.yml            # 전체 서비스 오케스트레이션 (AI, DB, Fan, MQTT)
├── Services/
│   ├── ble_gateway.py            # [Host] BLE <-> MQTT 중계 및 이미지 청킹
│   ├── ambient-ble-gateway.service # Systemd: BLE Gateway 자동 실행
│   └── rpicam-stream.service     # Systemd: 카메라 TCP 스트리밍
├── ai-service/                   # [Container] 얼굴 감지/식별 (MediaPipe + TFLite)
├── db-service/                   # [Container] 데이터 저장 및 통계 분석 (PostgreSQL)
├── fan-service/                  # [Container] 모터 제어 및 UART 통신
└── mqtt_broker/                  # [Container] 서비스 간 메시지 버스 (Mosquitto)

/var/lib/ambient-node/            # [Data Volume] 영구 저장소 (Host Mount)
├── users/                        # 사용자 프로필 데이터 (이미지, 임베딩)
│   └── user_12345/
│       ├── embedding.npy         # 얼굴 특징 벡터
│       ├── metadata.json         # 사용자 메타 정보
│       └── user_12345.png        # 프로필 이미지
├── captures/                     # 임시 캡처 이미지
├── db_data/                      # PostgreSQL 데이터 파일
└── mqtt/                         # MQTT 로그 및 데이터
```
<hr>

## 🚀 설치 및 실행 가이드 (Getting Started)
**1. 자동 설치 스크립트 실행 (Recommended)**<br>
필요한 시스템 패키지, Python 가상환경, Docker 권한 설정 등을 한 번에 처리합니다.

```
# 프로젝트 클론
git clone https://github.com/Ambient-Node/ambient-node-pi.git
cd ambient-node-pi

# 설치 스크립트 실행
chmod +x init_setting.sh
./init_setting.sh
```
**./init_setting.sh 수행 내용** <br>
- bluez, libbluetooth-dev 등 필수 패키지 설치
- BLE Gateway용 Python 가상환경(.venv) 생성
- /var/lib/ambient-node 데이터 디렉토리 생성 및 권한 부여

**2. 서비스 실행**<br>
BLE와 카메라는 하드웨어 접근성을 위해 **Systemd**로, 나머지 서비스는 **Docker**로 관리됩니다.
```
# 서비스 파일 등록
sudo cp Services/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# 서비스 시작 및 부팅 시 자동 실행 설정
sudo systemctl enable --now rpicam-stream.service       # 카메라 스트리밍
sudo systemctl enable --now ambient-ble-gateway.service # BLE 게이트웨이
sudo systemctl enable --now ambient-node.service        # Docker Compose (전체 스택)
```
<hr>

## 📡 주요 기능 상세 (Technical Highlights)
### 1️⃣ BLE Gateway (Host Process)
- Tech Stack: Python 3.11, bluezero, paho-mqtt, systemd
- 주요 기능:
  - BLE Peripheral: Flutter 앱과 GATT 통신 수행, 대용량 데이터(이미지) 청크(Chunk) 수신 및 조립.
  - Protocol Bridge: BLE 명령을 MQTT 메시지로 변환하여 내부망에 전파, 상태 변화를 BLE Notify로 앱에 전송.
  - Reliability: JSON 파싱 검증, 에러 처리 및 ACK 응답 시스템 구현.<br><br>
### 2️⃣ AI Service
- Tech Stack: TensorFlow Lite, MediaPipe, OpenCV
- 주요 기능:
  - 얼굴 인식: FaceNet 기반 임베딩 생성 및 코사인 유사도 비교.
  - 얼굴 추적: 프레임 간 객체 추적(Tracking ID 부여) 및 DB 사용자 매핑.
  - 이벤트 발행: face-detected(인식), face-position(좌표, 10Hz), face-lost(소실) 이벤트 발행.<br><br>
### 3️⃣ Fan Service
- Tech Stack: Python 3.11, pyserial
- 주요 기능:
  - Hardware HAL: MQTT 명령을 해석하여 XIAO RP2040 마이크로컨트롤러로 UART 명령 전송.
  - Mode Control: AI 좌표를 수신하여 팬 헤드 제어 (Pan-Tilt), 자연풍/회전 모드 관리.<br><br>

**🔌 UART 명령 프로토콜 (→ XIAO RP2040)**
```
S {level}               # 풍속 제어 (0~5)
A {direction} {toggle}  # 수동 각도 (l, r, u, d, c / 0, 1)
N {toggle}              # 자연풍 On/Off (1/0)
R {toggle}              # 회전 모드 On/Off (1/0)
P ({x},{y})             # 얼굴 좌표 전송 (AI Tracking)
P X                     # 추적 종료 신호
```

### 4️⃣ DB Service
- Tech Stack: PostgreSQL 15, psycopg2
- Database ERD:
<img width="80%" alt="DB ERD" src="https://github.com/user-attachments/assets/69d1c8dd-6338-4678-aa46-66e97221be37" />
<br><br>

**💾 데이터 구조 특징 (Hybrid Schema)**
- 정형 데이터: users, user_sessions 등 관계형 데이터는 테이블로 관리.
- 비정형 데이터: device_events 테이블의 event_data 컬럼은 JSONB로 관리하여 다양한 센서/로그를 유연하게 저장.

| **이벤트 타입 (event_type)** |	**설명 (Description)** |	**JSONB 데이터 예시 (event_data)**	| **비고** |
| --- | --- | --- | --- |
| speed_change |	풍속 조절	|{"speed": 3}	| 0~5단계 속도 기록 |
| mode_change |	동작 모드 변경	|{"type": "motor", "mode": "ai_tracking"}<br>{"type": "wind", "mode": "natural_wind"}	| 모터 제어와 바람 제어를 구분하여 기록 |
| direction_change |	수동 방향 조절	|{"direction": "left", "toggleOn": 1}	| 앱 조이스틱 조작 로그 |
| timer |	타이머 설정	|{"duration_sec": 3600}	| 종료 예약 시간 (초 단위) |
| face_detected |	얼굴 인식 성공	|{"confidence": 0.85}	| 인식 정확도(신뢰도) 기록 |
| face_lost |	얼굴 추적 소실 |	{"duration_seconds": 12.5}	| 추적 지속 시간 기록 |

<hr>

## 📨 MQTT 토픽 설계 (Message Bus)

| **토픽** | **발행자** | **구독자** | **용도** |
| --- | --- | --- | --- |
| **사용자 / 세션 관리** |  |  |  |
| ambient/user/register | BLE Gateway | DB, AI | 사용자 등록 (이미지 경로 포함) |
| ambient/user/delete | BLE Gateway | DB | 사용자 정보 및 로그 삭제 요청 |
| ambient/user/update | BLE Gateway | DB, AI | 사용자 이름 수정 |
| ambient/user/select | BLE Gateway | DB | 추적 대상 선택 및 세션 시작 |
| ambient/session/request | AI Service, BLE | DB | 현재 활성 세션 정보 요청 |
| ambient/session/active | DB Service | AI, BLE | 활성 세션 정보 브로드캐스트 (상태 동기화) |
| **팬 제어 명령** |  |  |  |
| ambient/command/speed | BLE Gateway | Fan, DB | 풍속 조절 (0~5단계) |
| ambient/command/direction | BLE Gateway | Fan, DB | 수동 회전 조작 (좌/우/상/하) |
| ambient/command/mode | BLE Gateway | Fan, DB, AI | 동작 모드 변경 (Motor/Wind 타입 구분) |
| ambient/command/timer | BLE Gateway | Fan, DB | 타이머 설정 (초 단위) |
| **AI 이벤트** |  |  |  |
| ambient/ai/face-detected | AI Service | DB, BLE | 얼굴 인식 성공 (신원 식별 로그) |
| ambient/ai/face-position | AI Service | Fan | 실시간 얼굴 좌표 (트래킹용, QoS 0) |
| ambient/ai/face-lost | AI Service | Fan, DB, BLE | 추적 대상 소실 및 대기 모드 전환 |
| **통계 조회** |  |  |  |
| ambient/stats/request | BLE Gateway | DB | 사용 통계 데이터 요청 |
| ambient/stats/response | DB Service | BLE | 통계 분석 결과 응답 (JSON) |

<hr>

## 📊 모니터링 및 디버깅
```
# 1. 전체 Docker 로그 확인
docker compose logs -f

# 2. 특정 컨테이너 로그 (예: AI 서비스)
docker compose logs -f ai_service

# 3. BLE Gateway 로그 (Systemd)
journalctl -u ambient-ble-gateway.service -f
```

    
