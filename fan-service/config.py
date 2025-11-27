# config.py
import os
from pathlib import Path

class Config:
    # MQTT
    MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt_broker")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "fan-service")

    SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyAMA0")
    SERIAL_BAUDRATE = int(os.getenv("SERIAL_BAUDRATE", "921600"))

    # 데이터 디렉토리
    DATA_DIR = Path("/var/lib/ambient-node")
    USERS_DIR = DATA_DIR / "users"

    # 네트워크
    NETWORK_WAIT_TIMEOUT = 60
