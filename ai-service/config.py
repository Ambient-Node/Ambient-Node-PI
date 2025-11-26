"""설정 관리 (Confidence 최적화)"""
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
    FACE_ID_INTERVAL = 0.8  # 1.0 → 0.8 (인식 빈도 증가)
    FACE_LOST_TIMEOUT = 8.0
    
    # 얼굴 감지
    MIN_FACE_SIZE = 600      # 800 → 600 (작은 얼굴도 감지)
    SIMILARITY_THRESHOLD = 0.36  # 0. → 0.36 (현재 로그 0.33~0.50 최적)
    MAX_MATCH_DISTANCE = 250  # 300 → 250 (추적 안정화)
    
    # 경로
    SAVE_DIR = os.getenv('SAVE_DIR', '/var/lib/ambient-node/captures')
    FACE_DIR = os.getenv('FACE_DIR', '/var/lib/ambient-node/users')
    MODEL_PATH = os.getenv('TFLITE_MODEL', '/app/facenet.tflite')
    
    # MQTT
    BROKER = os.getenv('MQTT_BROKER', 'localhost')
    PORT = int(os.getenv('MQTT_PORT', 1883))
