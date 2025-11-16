# ai-service/Dockerfile
FROM python:3.10-slim-bullseye

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    libopencv-dev \
    python3-opencv \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리 설정
WORKDIR /app

# 필요한 디렉토리 생성
RUN mkdir -p /var/lib/ambient-node/captures \
    /var/lib/ambient-node/users

# Python 패키지 먼저 설치 (캐싱 최적화)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY main.py .
COPY facenet.tflite /app/

# 권한 설정
RUN chmod +x main.py

# 환경변수 설정
ENV PYTHONUNBUFFERED=1

# 실행 (헤드리스 모드)
CMD ["python3", "main.py", "--headless"]
