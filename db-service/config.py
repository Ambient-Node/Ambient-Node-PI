"""DB Service 설정"""
import os

class Config:
    # MQTT
    MQTT_BROKER = os.getenv('MQTT_BROKER', 'mqtt_broker')
    MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
    
    # PostgreSQL
    DB_HOST = os.getenv('DB_HOST', 'postgres')
    DB_PORT = int(os.getenv('DB_PORT', 5432))
    DB_NAME = os.getenv('DB_NAME', 'ambient_node')
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'password')
    
    # 기타
    RECONNECT_DELAY = 5  # 초
