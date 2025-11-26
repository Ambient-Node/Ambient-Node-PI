"""설정 관리 (640x480 최적화 및 기준 상향)"""
import os

class Config:
    # TCP 설정
    TCP_IP = 'localhost'
    TCP_PORT = 8888
    
    CAMERA_WIDTH = 640
    CAMERA_HEIGHT = 480
    PROCESSING_WIDTH = 640   # 입력과 동일하게 설정하여 리사이즈 부하 최소화
    PROCESSING_HEIGHT = 480
                        
    # 타이밍
    MQTT_SEND_INTERVAL = 0.25 
    FACE_ID_INTERVAL = 0.5     # 신원 확인 주기
    
    FACE_LOST_TIMEOUT = 1.0    # 1초만 안 보여도 추적 중단 (기존 8초 -> 1초)
    MIN_FACE_SIZE = 0          # 자동
    
    # 모델 설정
    SIMILARITY_THRESHOLD = 0.4 
    MAX_MATCH_DISTANCE = 150   # 640해상도에 맞춰 거리 기준 축소 (300 -> 150)
    
    # 경로
    SAVE_DIR = os.getenv('SAVE_DIR', '/var/lib/ambient-node/captures')
    FACE_DIR = os.getenv('FACE_DIR', '/var/lib/ambient-node/users')
    MODEL_PATH = os.getenv('TFLITE_MODEL', '/app/facenet.tflite') # FaceNet 복귀
    
    # MQTT
    BROKER = os.getenv('MQTT_BROKER', 'localhost')
    PORT = int(os.getenv('MQTT_PORT', 1883))