
"""설정 관리"""
import os

class Config:
    # TCP
    TCP_IP = 'localhost'
    TCP_PORT = 8888
    
    # 카메라
    CAMERA_WIDTH = 1920
    CAMERA_HEIGHT = 1080
    PROCESSING_WIDTH = 640
    PROCESSING_HEIGHT = 360
                                                                                      
    # 타이밍
    MQTT_SEND_INTERVAL = 0.1
    FACE_ID_INTERVAL = 1.0
    FACE_LOST_TIMEOUT = 8.0
    
    # 얼굴 감지
    MIN_FACE_SIZE = 800
    SIMILARITY_THRESHOLD = 0.4
    MAX_MATCH_DISTANCE = 300
    
    # 경로
    SAVE_DIR = os.getenv('SAVE_DIR', '/var/lib/ambient-node/captures')
    FACE_DIR = os.getenv('FACE_DIR', '/var/lib/ambient-node/users')
    MODEL_PATH = os.getenv('TFLITE_MODEL', '/app/facenet.tflite')
    
    # MQTT
    BROKER = os.getenv('MQTT_BROKER', 'localhost')
    PORT = int(os.getenv('MQTT_PORT', 1883))
