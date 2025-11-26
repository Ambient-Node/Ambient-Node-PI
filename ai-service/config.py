"""설정 관리 (FHD 복구 & 반응속도 최적화)"""
import os

class Config:
    # TCP 연결
    TCP_IP = 'localhost'
    TCP_PORT = 8888
    
    # ✅ 1. 해상도: 입력은 FHD, 처리는 640x360 (16:9 비율 유지)
    CAMERA_WIDTH = 1920
    CAMERA_HEIGHT = 1080
    PROCESSING_WIDTH = 640
    PROCESSING_HEIGHT = 360
                        
    # ✅ 2. 전송 주기: 0.25초 (4Hz)
    MQTT_SEND_INTERVAL = 0.25
    FACE_ID_INTERVAL = 0.5
    
    # ✅ 3. 트래킹 설정 (유령 좌표 방지)
    FACE_LOST_TIMEOUT = 0.5   # 0.5초만 안 보여도 즉시 삭제
    MAX_MATCH_DISTANCE = 150  # FHD 해상도에서의 거리 오차 허용 범위
    
    # 모델 관련
    MIN_FACE_SIZE = 0
    SIMILARITY_THRESHOLD = 0.4
    
    # 경로
    SAVE_DIR = os.getenv('SAVE_DIR', '/var/lib/ambient-node/captures')
    FACE_DIR = os.getenv('FACE_DIR', '/var/lib/ambient-node/users')
    MODEL_PATH = os.getenv('TFLITE_MODEL', '/app/facenet.tflite')
    
    # MQTT
    BROKER = os.getenv('MQTT_BROKER', 'localhost')
    PORT = int(os.getenv('MQTT_PORT', 1883))