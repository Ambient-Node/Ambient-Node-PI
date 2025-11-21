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
        
        # ✅ Config에서 타임아웃 값 주입
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
        self.last_position_time = 0
        
        # 스케일
        self.scale_x = config.CAMERA_WIDTH / config.PROCESSING_WIDTH
        self.scale_y = config.CAMERA_HEIGHT / config.PROCESSING_HEIGHT
        
        print(f"[AI] Config loaded:")
        print(f"  - FACE_LOST_TIMEOUT: {config.FACE_LOST_TIMEOUT}s")
        print(f"  - FACE_ID_INTERVAL: {config.FACE_ID_INTERVAL}s")
        print(f"  - MQTT_SEND_INTERVAL: {config.MQTT_SEND_INTERVAL}s")

    def on_session_update(self, session_id, user_ids):
        """세션 업데이트 콜백"""
        print(f"[AI] Session updated: {session_id}")
        print(f"[AI] Tracking users: {user_ids}")

    def on_user_register(self, payload):
        """새 사용자 등록 콜백"""
        user_id = payload.get('user_id')
        username = payload.get('username')
        image_path = payload.get('image_path')
        
        print(f"[AI] New user registration: {username} ({user_id})")
        
        if not image_path:
            print("[AI] Error: No image_path")
            return
        
        try:
            success = self.recognizer.register_user(user_id, username, image_path)
            if success:
                print(f"[AI] ✅ User registered")
            else:
                print(f"[AI] ❌ Registration failed")
        except Exception as e:
            print(f"[AI] Registration error: {e}")

    def on_user_update(self, payload):
        """사용자 정보 업데이트"""
        user_id = payload.get('user_id')
        username = payload.get('username')
        print(f"[AI] User updated: {user_id} → {username}")
        
        if user_id in self.recognizer.known_usernames:
            self.recognizer.known_usernames[user_id] = username

    def run(self):
        """메인 루프"""
        print("[AI] Service started")
        self.camera.start()
        
        try:
            while True:
                current_time = time.time()
                frame = self.camera.get_frame()
                
                if frame is None:
                    time.sleep(0.01)
                    continue
                
                # 1. MediaPipe로 얼굴 감지
                detected_positions = self._detect_faces(frame)
                
                # 2. 추적 업데이트
                updated_ids, lost_faces = self.tracker.update(detected_positions, current_time)
                
                # 3. ✅ Config.FACE_ID_INTERVAL 주기로 얼굴 인식
                newly_identified = self.tracker.identify_faces(
                    self.recognizer,
                    frame,
                    current_time,
                    interval=self.config.FACE_ID_INTERVAL
                )
                
                # face-detected: 처음 인식된 사용자만 발행
                for face_id, user_id, confidence in newly_identified:
                    self.mqtt.publish_face_detected(user_id, confidence)
                    print(f"[AI] 🆕 New user detected: {user_id} (conf={confidence:.2f})")
                
                # ✅ face-position: Config.MQTT_SEND_INTERVAL 주기로 발행
                if current_time - self.last_position_time >= self.config.MQTT_SEND_INTERVAL:
                    session_id, selected_users = self.mqtt.get_current_session()
                    selected_faces = self.tracker.get_selected_faces(selected_users)
                    
                    for face_info in selected_faces:
                        user_id = face_info['user_id']
                        x, y = face_info['center']
                        self.mqtt.publish_face_position(user_id, x, y)
                    
                    self.last_position_time = current_time
                
                # face-lost: Config.FACE_LOST_TIMEOUT 후 발행
                for lost_info in lost_faces:
                    self.mqtt.publish_face_lost(
                        lost_info['user_id'],
                        lost_info['duration']
                    )
                    print(f"[AI] 👋 User lost: {lost_info['user_id']} (duration={lost_info['duration']:.1f}s)")
                
                time.sleep(0.01)
        
        except KeyboardInterrupt:
            print("\n[AI] Stopping...")
        finally:
            self.camera.stop()
            self.mqtt.stop()

    def _detect_faces(self, frame):
        """MediaPipe로 얼굴 감지"""
        small = cv2.resize(frame, (self.config.PROCESSING_WIDTH, self.config.PROCESSING_HEIGHT))
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        
        results = self.face_detection.process(rgb)
        
        detected = []
        if results.detections:
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                
                x_center = int((bbox.xmin + bbox.width / 2) * self.config.PROCESSING_WIDTH * self.scale_x)
                y_center = int((bbox.ymin + bbox.height / 2) * self.config.PROCESSING_HEIGHT * self.scale_y)
                
                x1 = int(bbox.xmin * self.config.PROCESSING_WIDTH * self.scale_x)
                y1 = int(bbox.ymin * self.config.PROCESSING_HEIGHT * self.scale_y)
                x2 = int((bbox.xmin + bbox.width) * self.config.PROCESSING_WIDTH * self.scale_x)
                y2 = int((bbox.ymin + bbox.height) * self.config.PROCESSING_HEIGHT * self.scale_y)
                
                detected.append({
                    'center': (x_center, y_center),
                    'bbox': (x1, y1, x2, y2)
                })
        
        return detected


def main():
    config = Config()
    service = AIService(config)
    service.run()


if __name__ == '__main__':
    main()
