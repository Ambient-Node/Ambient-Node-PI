# AI Service Dockerfile for Raspberry Pi 5
# Python 3.10.12 기반

FROM python:3.10.12-slim-bookworm

# 작업 디렉토리
WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    build-essential \
    cmake \
    git \
    libopencv-dev \
    python3-opencv \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libatlas-base-dev \
    ffmpeg \
    mosquitto-clients \
    && rm -rf /var/lib/apt/lists/*

# pip 업그레이드
RUN python3 -m pip install --upgrade pip setuptools wheel

# NumPy 1.x 설치 (2.x 호환성 문제 회피)
RUN python3 -m pip install "numpy<2" --force
