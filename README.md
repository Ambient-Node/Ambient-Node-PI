# Ambient-Node container (temporary architecture)

```
/home/pi/ambient-node/              ← 프로젝트 루트
├── docker-compose.yml              ← 모든 컨테이너 정의
├── BLE_gateway/
│   └── ble_gateway.py              ← App으로부터 BLE 데이터를 받고, mqtt 발행해주는 역할
├── fan-service/                    ← 사실 라파에서는 코드 없이 docker 실행만 시켜도 됨. (빌드한 후)
│   ├── Dockerfile
│   ├── fan_service.py
├── db-service/                     ← 사실 라파에서는 코드 없이 docker 실행만 시켜도 됨. (빌드한 후)
│   ├── Dockerfile
│   └── db_service.py
├── ai-service/                     ← 사실 라파에서는 코드 없이 docker 실행만 시켜도 됨. (빌드한 후)
│   ├── Dockerfile
│   └── 미정
└── mqtt-broker/
    └── mosquitto.conf              ← 브로커 설정 파일

/var/lib/ambient-node/              ← 호스트의 영속 데이터
├── users/                          ← 사용자 사진
│   ├── 이름/
│   │   └── face_001.jpg
├── db.sqlite                       ← DB 파일
└── mqtt/
    ├── data/                       ← 브로커 데이터
    └── log/                        ← 브로커 로그

/var/lib/docker/                    ← Docker 내부 관리 (신경 안 써도 됨)
└── containers/
    ├── ambient-mqtt-broker/        ← Docker가 자동 관리
    ├── ambient-fan-service/
    └── ambient-db-service/

```
