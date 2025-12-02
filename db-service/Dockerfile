# db-service/Dockerfile

FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치 (PostgreSQL client 라이브러리, 기타 필요 패키지)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY config.py database.py mqtt_client.py handlers.py main.py ./

# 환경 변수
ENV PYTHONUNBUFFERED=1

# 컨테이너 시작 시 실행할 커맨드
CMD ["python3", "main.py"]
