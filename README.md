# 🌪️ Ambient Node: AI Smart Air Circulator

**AI 비전 기반 사용자 추적형 스마트 에어서큘레이터**

> **2025 캡스톤 디자인 프로젝트**
> *   **Platform:** Raspberry Pi 5 (Bookworm 64-bit)
> *   **Architecture:** MSA (Micro Service Architecture) + BLE Hybrid

본 프로젝트는 엣지 디바이스(Raspberry Pi)에서 독립적으로 구동되는 **보안형 AI 가전 소프트웨어 스택**입니다.
클라우드 연결 없이 온디바이스 AI로 사용자를 추적하며, 자체 개발한 **BLE 프로토콜**을 통해 모바일 앱과 안정적으로 연동됩니다.

---

## 📂 시스템 아키텍처 (System Architecture)

전체 시스템은 **Docker 컨테이너**로 격리된 서비스들과, 하드웨어 제어를 위해 **Host 레벨**에서 실행되는 서비스들로 구성됩니다.

```
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

/var/lib/ambient-node/            # [Data Volume] 영구 저장소 (사용자 사진, DB 파일 등)
├── users/                        # 사용자 프로필 데이터
│   └── user_12345/
│       ├── embedding.npy         # 얼굴 특징 벡터
│       ├── metadata.json         # 이름 정보
│       └── user_12345.png        # 프로필 이미지 (App 표시용)
├── captures/                     # 임시 캡처 이미지
├── db_data/                      # PostgreSQL 데이터 파일 (docker volume 마운트)
└── mqtt/                         # MQTT 로그 및 데이터

```

## 🚀 설치 및 실행 가이드 (Getting Started)
1. 자동 설치 스크립트 실행 (Recommended)
필요한 시스템 패키지, Python 가상환경, Docker 권한 설정 등을 한 번에 처리합니다.

```
# 프로젝트 클론
git clone https://github.com/Ambient-Node/ambient-node-pi.git
cd ambient-node-pi

# 설치 스크립트 실행
chmod +x init_setting.sh
./init_setting.sh
```

### ./init_setting.sh
- bluez, libbluetooth-dev 등 필수 패키지 설치
- BLE Gateway용 Python 가상환경(.venv) 생성
- /var/lib/ambient-node 데이터 디렉토리 생성 및 권한 부여

## 🛠️ 서비스 실행 방법
1. 메인 시스템 실행 (Docker Compose)
AI, DB, Fan, MQTT 브로커 등 핵심 컨테이너를 실행합니다.
```
# 이미지 빌드 및 백그라운드 실행
docker compose up -d --build

# 실행 상태 확인
docker compose ps
```
2. 호스트 서비스 실행 (BLE & Camera)
BLE와 카메라는 하드웨어 접근성을 위해 Systemd 서비스로 관리됩니다.
```
# 서비스 파일 등록
sudo cp Services/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# 서비스 시작 및 부팅 시 자동 실행 설정
sudo systemctl enable --now rpicam-stream.service       # 카메라 스트리밍
sudo systemctl enable --now ambient-ble-gateway.service # BLE 게이트웨이
```

## 📡 주요 기능 상세 (Technical Highlights)
1. BLE Gateway (Host Process)
- 역할: 모바일 앱(Flutter)과 내부 MQTT 버스 간의 통신을 중계합니다.
- 기술적 특징:
  - Chunking Protocol: BLE의 작은 패킷 크기(MTU) 한계를 극복하기 위해, 대용량 프로필 이미지를 조각내어 전송하고 재조립합니다.
  - ACK System: 사용자 등록/삭제 등 중요 명령에 대해 응답(Acknowledgement)을 보내 데이터 무결성을 보장합니다.
2. Fan Service (Hardware HAL)
    - 역할: 상위 레벨의 MQTT 명령을 MCU(RP2040)가 이해할 수 있는 UART 시리얼 프로토콜로 변환합니다.
    - 안전 장치: 자연풍 모드 전환 시 모터 상태를 동기화하고, 비정상 종료 시 자동으로 안전 모드로 복귀합니다.
3. DB Service (Hybrid Analytics)
    - 역할: PostgreSQL을 사용하여 사용자 정보(정형)와 센서/이벤트 로그(비정형 JSONB)를 통합 관리합니다.
    - 분석: 별도의 분석 서버 없이 SQL 윈도우 함수를 활용하여 실시간 사용 패턴(주 사용 시간대, 선호 풍속)을 분석합니다.

## 📊 모니터링 및 디버깅
```
# 1. 전체 Docker 로그 확인
docker compose logs -f

# 2. 특정 컨테이너 로그 (예: AI 서비스)
docker compose logs -f ai_service

# 3. BLE Gateway 로그 (Systemd)
journalctl -u ambient-ble-gateway.service -f
```

    
