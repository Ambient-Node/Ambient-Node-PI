FROM python:3.11-slim

WORKDIR /app

# 필요한 패키지 설치
RUN pip install --no-cache-dir paho-mqtt

# 애플리케이션 복사
COPY db_service.py .

# 볼륨 마운트 포인트 생성
RUN mkdir -p /var/lib/ambient-node

# 실행
CMD ["python", "db_service.py"]

