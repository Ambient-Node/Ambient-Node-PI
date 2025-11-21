# config.py
import os
from pathlib import Path

class Config:
    # MQTT
    MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt_broker") #테스트 하기 위해 잠시 수정.
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "fan-service")

    # GPIO
    FAN_PWM_PIN = 18
    MOTOR_STEP_PIN_H = 21
    MOTOR_DIR_PIN_H = 20
    MOTOR_STEP_PIN_V = 23
    MOTOR_DIR_PIN_V = 24

    SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/serial0")
    SERIAL_BAUDRATE = int(os.getenv("SERIAL_BAUDRATE", "9600"))

    # 데이터 디렉토리
    DATA_DIR = Path("/var/lib/ambient-node")
    USERS_DIR = DATA_DIR / "users"

    # 네트워크
    NETWORK_WAIT_TIMEOUT = 60
