FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    libdbus-1-dev \
    libglib2.0-dev \
    libbluetooth-dev \
    python3-dev \
    build-essential \
    pkg-config \
    libcairo2-dev \
    libgirepository1.0-dev \
    gir1.2-gtk-3.0 \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지 설치
RUN pip install --no-cache-dir \
    paho-mqtt \
    bluezero \
    RPi.GPIO

# 애플리케이션 복사
COPY fan_service.py .

# 볼륨 마운트 포인트
RUN mkdir -p /var/lib/ambient-node/users

# BLE 및 GPIO 접근을 위한 권한 (privileged 모드 필요)
# 또는 --device 옵션 사용

# 실행
CMD ["python", "fan_service.py"]
