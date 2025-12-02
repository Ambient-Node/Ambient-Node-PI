# Ambient-Node

```
/home/pi/ambient-node/
├── docker-compose.yml           
├── Services/
│   ├── ble_gateway.py            
│   ├── ambient-node.service      # systemd 서비스 파일 (Docker Compose 실행용)
│   ├── ambient-ble-gateway.service # systemd 서비스 파일 (BLE Gateway 실행용)
│   └── rpicam-stream.service     # 카메라 스트리밍 서비스
├── ai-service/
│   ├── Dockerfile
│   ├── main.py
│   ├── config.py
│   ├── face_recognition.py
│   ├── face_tracker.py
│   └── mqtt_client.py
├── db-service/
│   ├── Dockerfile
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── handlers.py
│   └── mqtt_client.py
├── fan-service/
│   ├── Dockerfile
│   ├── main.py
│   ├── hardware.py               # 시리얼 통신 (Ambient-Node-HW)
│   ├── config.py
│   └── mqtt_client.py
└── mqtt_broker/
    └── mosquitto.conf            # 브로커 설정

/var/lib/ambient-node/            # [영속 데이터 저장소] (Host Volume)
├── users/                        # 사용자 프로필 데이터
│   └── user_12345/
│       ├── embedding.npy         # 얼굴 특징 벡터
│       ├── metadata.json         # 이름 정보
│       └── user_12345.png        # 프로필 이미지 (App 표시용)
├── captures/                     # 임시 캡처 이미지
├── db_data/                      # PostgreSQL 데이터 파일 (docker volume 마운트)
└── mqtt/                         # MQTT 로그 및 데이터

```
