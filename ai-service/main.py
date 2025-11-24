#!/usr/bin/env python3
"""AI Service - 메인 실행 파일 (시각화 추가)"""

import os
import time
import cv2
import mediapipe as mp
from config import Config
from camera import CameraStream
from face_recognition import FaceRecognizer
from face_tracker import FaceTracker
from mqtt_client import MQTTClient
from visualizer import FaceDetectionVisualizer


class AIService:
    def __init__(self, config):
        self.config = config
        
        # 시각화 활성화 여부 (환경변수로 제어)
        enable_display = os.getenv('ENABLE_DISPLAY', 'true').lower() == 'true'
        self.visualizer = FaceDetectionVisualizer(enable_display=enable_display)
        
        self.camera = CameraStream(config)
        self.recognizer = FaceRecognizer(config.MODEL_PATH, config.FACE_DIR)
        self.tracker = FaceTracker(
            max_distance=config.MAX_MATCH_DISTANCE,
            lost_timeout=config.FACE_LOST_TIMEOUT,
        )
        self.mqtt = MQTTClient(config.BROKER, config.PORT)
        
        self.mqtt.on_session_update = self.on_session_update
        self.mqtt.on_user_register = self.on_user_register
        self.mqtt.on_user_update = self.on_user_update
        
        self.last_position_time = 0
        self.scale_x = config.CAMERA_WIDTH / config.PROCESSING_WIDTH
        self.scale_y = config.CAMERA_HEIGHT / config.PROCESSING_HEIGHT
        
        print(f"[AI] Config loaded:")
        print(f"  - FACE_LOST_TIMEOUT: {config.FACE_LOST_TIMEOUT}s")
        print(f"  - FACE_ID_INTERVAL: {config.FACE_ID_INTERVAL}s")
        print(f"  - MQTT_SEND_INTERVAL: {config.MQTT_SEND_INTERVAL}s")
        print(f"  - DISPLAY: {enable_display}")

    def on_session_update(self, session_id, user_ids):
        print(f"[AI] Session updated: {session_id}")
        print(f"[AI] Tracking users: {user_ids}")

    def on_user_register(self, payload):
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
                print(f"[AI] User registered")
            else:
                print(f"[AI] Registration failed")
        except Exception as e:
            print(f"[AI] Registration error: {e}")

    def on_user_update(self, payload):
        user_id = payload.get('user_id')
        username = payload.get('username')
        print(f"[AI] User updated: {user_id} → {username}")
        
        if user_id in self.recognizer.known_usernames:
            self.recognizer.known_usernames[user_id] = username

    def run(self):
        """메인 루프 (시각화 추가)"""
        print("[AI] Service started")
        self.camera.start()
        
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.3
        ) as face_detection:
            
            last_global_identify_time = 0
            frame_count = 0
            fps_start = time.time()
            fps = 0.0
            
            try:
                while True:
                    current_time = time.time()
                    frame = self.camera.get_frame()
                    
                    if frame is None:
                        time.sleep(0.001)
                        continue
                    
                    # Processing 해상도로 리사이즈
                    frame_processing = cv2.resize(
                        frame, 
                        (self.config.PROCESSING_WIDTH, self.config.PROCESSING_HEIGHT)
                    )
                
                    # 1. MediaPipe로 얼굴 감지
                    detected_positions = self._detect_faces(frame_processing, face_detection)
                    
                    # 2. 추적 업데이트
                    updated_ids, lost_faces = self.tracker.update(detected_positions, current_time)
                
                    # 3. 전역 타이머로 얼굴 인식
                    force_identify = (current_time - last_global_identify_time >= self.config.FACE_ID_INTERVAL)
                    
                    newly_identified = self.tracker.identify_faces(
                        self.recognizer,
                        frame_processing,
                        current_time,
                        interval=self.config.FACE_ID_INTERVAL,
                        force_all=force_identify
                    )
                    
                    if force_identify:
                        last_global_identify_time = current_time
                        if len(updated_ids) > 0:
                            print(f"[DEBUG] Identifying {len(updated_ids)} faces")
                    
                    # face-detected
                    for face_id, user_id, confidence in newly_identified:
                        self.mqtt.publish_face_detected(user_id, confidence)
                    
                    # face-position
                    if current_time - self.last_position_time >= self.config.MQTT_SEND_INTERVAL:
                        session_id, selected_users = self.mqtt.get_current_session()
                        selected_faces = self.tracker.get_selected_faces(selected_users)
                        
                        for face_info in selected_faces:
                            user_id = face_info['user_id']
                            x, y = face_info['center']
                            self.mqtt.publish_face_position(user_id, x, y)
                        
                        self.last_position_time = current_time
                    
                    # face-lost
                    for lost_info in lost_faces:
                        self.mqtt.publish_face_lost(
                            lost_info['user_id'],
                            lost_info['duration']
                        )
                        print(f"[AI] 👋 User lost: {lost_info['user_id']} (duration={lost_info['duration']:.1f}s)")
                    
                    # ========== 시각화 추가 ==========
                    # 4. 감지 결과를 시각화 형식으로 변환
                    detections = self._prepare_detections_for_display()
                    
                    # 5. 바운딩 박스 그리기
                    display_frame = self.visualizer.draw_face_boxes(frame_processing, detections)
                    
                    # 6. 화면 표시
                    key = self.visualizer.show(display_frame)
                    
                    # ESC 키로 종료
                    if key == 27:
                        print("\n[AI] ESC pressed, stopping...")
                        break
                    # ==================================
                    
                    # FPS 계산
                    frame_count += 1
                    if frame_count % 30 == 0:
                        elapsed = time.time() - fps_start
                        fps = 30 / elapsed
                        fps_start = time.time()
                        print(f"[INFO] FPS: {fps:.1f} | Tracked: {len(self.tracker.tracked_faces)}")
                    
                    time.sleep(0.001)
            
            except KeyboardInterrupt:
                print("\n[AI] Stopping...")
            finally:
                self.visualizer.close()  # 화면 닫기
                self.camera.stop()
                self.mqtt.stop()

    def _detect_faces(self, frame_processing, face_detection):
        """MediaPipe로 얼굴 감지"""
        rgb = cv2.cvtColor(frame_processing, cv2.COLOR_BGR2RGB)
        results = face_detection.process(rgb)
        
        detected = []
        if results.detections:
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                
                x1 = int(bbox.xmin * self.config.PROCESSING_WIDTH)
                y1 = int(bbox.ymin * self.config.PROCESSING_HEIGHT)
                x2 = int((bbox.xmin + bbox.width) * self.config.PROCESSING_WIDTH)
                y2 = int((bbox.ymin + bbox.height) * self.config.PROCESSING_HEIGHT)
                
                x_center_fhd = int((bbox.xmin + bbox.width / 2) * self.config.PROCESSING_WIDTH * self.scale_x)
                y_center_fhd = int((bbox.ymin + bbox.height / 2) * self.config.PROCESSING_HEIGHT * self.scale_y)
                
                detected.append({
                    'center': (x_center_fhd, y_center_fhd),
                    'bbox': (x1, y1, x2, y2)
                })
        
        return detected
    
    def _prepare_detections_for_display(self):
        """추적 중인 얼굴을 시각화용 형식으로 변환"""
        detections = []
        
        with self.tracker.lock:
            for fid, finfo in self.tracker.tracked_faces.items():
                user_id = finfo.get('user_id')
                username = self.recognizer.known_usernames.get(user_id, 'Unknown') if user_id else 'Unknown'
                confidence = finfo.get('confidence', 0.0)
                bbox = finfo['bbox']
                
                # bbox를 (x, y, w, h) 형식으로 변환
                x1, y1, x2, y2 = bbox
                
                detections.append({
                    'bbox': (x1, y1, x2 - x1, y2 - y1),  # (x, y, w, h)
                    'user_id': user_id,
                    'username': username,
                    'confidence': confidence
                })
        
        return detections


def main():
    config = Config()
    service = AIService(config)
    service.run()


if __name__ == '__main__':
    main()
