#!/usr/bin/env python3
"""AI Service - 메인 실행 파일"""

import time
import cv2
import mediapipe as mp

from config import Config
from camera import CameraStream
from face_recognition import FaceRecognizer
from face_tracker import FaceTracker
from mqtt_client import MQTTClient

class AIService:
    def __init__(self, config):
        self.config = config
        
        # 컴포넌트 초기화
        self.camera = CameraStream(config)
        self.recognizer = FaceRecognizer(config.MODEL_PATH, config.FACE_DIR)
        
        self.tracker = FaceTracker(
            max_distance=config.MAX_MATCH_DISTANCE,
            lost_timeout=config.FACE_LOST_TIMEOUT,
        )
        
        self.mqtt = MQTTClient(config.BROKER, config.PORT)
        
        # MQTT 콜백 연결
        self.mqtt.on_session_update = self.on_session_update
        self.mqtt.on_user_register = self.on_user_register
        self.mqtt.on_user_update = self.on_user_update
        
        # MediaPipe
        self.face_detection = mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.3
        )
        
        # 타이머
        self.last_send_time = 0
        self.last_id_time = 0
        
        # 스케일
        self.scale_x = config.CAMERA_WIDTH / config.PROCESSING_WIDTH
        self.scale_y = config.CAMERA_HEIGHT / config.PROCESSING_HEIGHT

    def on_session_update(self, session_id, user_ids):
        """세션 업데이트 콜백"""
        print(f"[AI] Session updated: {session_id}")
        print(f"[AI] Tracking users: {user_ids}")

    def on_user_register(self, payload):
        """새 사용자 등록 콜백 - 임베딩 생성 및 저장"""
        user_id = payload.get('user_id')
        username = payload.get('username')
        image_path = payload.get('image_path') # 이미지 경로 받기
        
        print(f"[AI] New user registration request: {username} ({user_id})")
        
        if not image_path:
            print("[AI] Error: No image_path in payload")
            return

        try:
            # [수정] 임베딩 생성 및 저장 요청
            success = self.recognizer.register_user(user_id, username, image_path)
            
            if success:
                print(f"[AI] User registered successfully")
            else:
                print(f"[AI] Failed to register user (check logs)")
                
        except Exception as e:
            print(f"[AI] Registration error: {e}")

    def on_user_update(self, payload):
        """사용자 정보 업데이트 콜백 - username 변경"""
        user_id = payload.get('user_id')
        new_username = payload.get('username')
        
        print(f"[AI] User update: {user_id} → {new_username}")
        
        try:
            success = self.recognizer.update_username(user_id, new_username)
            if success:
                print(f"[AI] Username updated in memory")
            else:
                print(f"[AI] Update failed (check logs)")
        except Exception as e:
            print(f"[AI] Update error: {e}")

    def detect_faces(self, frame):
        """얼굴 감지"""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_detection.process(rgb)
        
        if not results.detections:
            return []
        
        h, w = frame.shape[:2]
        detected = []
        
        for detection in results.detections:
            bbox = detection.location_data.relative_bounding_box
            x = int(bbox.xmin * w)
            y = int(bbox.ymin * h)
            bw = int(bbox.width * w)
            bh = int(bbox.height * h)
            
            if bw * bh < self.config.MIN_FACE_SIZE:
                continue
            
            x_fhd = int(x * self.scale_x)
            y_fhd = int(y * self.scale_y)
            
            detected.append({
                'bbox': (x, y, bw, bh),
                'center': (x_fhd + int(bw * self.scale_x) // 2,
                          y_fhd + int(bh * self.scale_y) // 2)
            })
        
        return detected

    def run(self):
        """메인 루프"""
        self.camera.start()
        print("[AI] Service started")
        
        try:
            while True:
                frame = self.camera.get_frame()
                if frame is None:
                    time.sleep(0.001)
                    continue
                
                current_time = time.time()
                
                # 1. 얼굴 감지
                frame_small = cv2.resize(
                    frame,
                    (self.config.PROCESSING_WIDTH, self.config.PROCESSING_HEIGHT)
                )
                detected = self.detect_faces(frame_small)
                
                # 2. 얼굴 추적
                updated_ids, lost_faces = self.tracker.update(detected, current_time)
                
                # 3. 얼굴 신원 확인 (1초마다)
                if current_time - self.last_id_time >= self.config.FACE_ID_INTERVAL:
                    identified = self.tracker.identify_faces(
                        self.recognizer,
                        frame_small,
                        current_time,
                        self.config.FACE_ID_INTERVAL,
                    )
                    
                    session_id, selected_ids = self.mqtt.get_current_session()
                    
                    for face_id, user_id, conf in identified:
                        if user_id not in selected_ids:
                            continue
                        
                        face = self.tracker.tracked_faces.get(face_id)
                        if face:
                            x, y = face['center']
                            self.mqtt.publish_face_detected(user_id, conf, x, y)
                    
                    self.last_id_time = current_time
                
                # 4. face_position 발행 (10Hz)
                session_id, selected_ids = self.mqtt.get_current_session()
                
                if (current_time - self.last_send_time >= self.config.MQTT_SEND_INTERVAL
                    and selected_ids):
                    selected_faces = self.tracker.get_selected_faces(selected_ids)
                    for face in selected_faces:
                        x, y = face['center']
                        self.mqtt.publish_face_position(face['user_id'], x, y)
                    
                    self.last_send_time = current_time
                
                # 5. face_lost 발행
                if session_id and lost_faces:
                    for lost in lost_faces:
                        user_id = lost['user_id']
                        duration = lost['duration']
                        
                        if user_id in selected_ids:
                            self.mqtt.publish_face_lost(user_id, duration)
                            
        except KeyboardInterrupt:
            print("\n[AI] Terminating...")
        finally:
            self.camera.stop()
            self.mqtt.stop()

def main():
    config = Config()
    service = AIService(config)
    service.run()

if __name__ == '__main__':
    main()
