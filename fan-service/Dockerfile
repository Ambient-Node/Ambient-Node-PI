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

# 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 파일 복사
COPY *.py /app/

# 볼륨 마운트 포인트
RUN mkdir -p /var/lib/ambient-node/users

# 환경 변수 설정
ENV PYTHONUNBUFFERED=1
ENV MQTT_BROKER=mqtt_broker
ENV MQTT_PORT=1883
ENV MQTT_CLIENT_ID=fan-service

# 실행
CMD ["python3", "main.py"]
