
import time
import cv2
import mediapipe as mp
import csv
import os
from datetime import datetime
from config import Config
from camera import CameraStream
from face_recognition import FaceRecognizer
from face_tracker import FaceTracker
from mqtt_client import MQTTClient

class AIService:
    def __init__(self, config):
        self.config = config
        
        self.camera = CameraStream(config)
        self.recognizer = FaceRecognizer(
            config.MODEL_PATH, 
            config.FACE_DIR, 
            config.SIMILARITY_THRESHOLD
        )
        self.tracker = FaceTracker(
            max_distance=config.MAX_MATCH_DISTANCE,
            lost_timeout=config.FACE_LOST_TIMEOUT,
        )
        self.mqtt = MQTTClient(config.BROKER, config.PORT)
        
        self.mqtt.on_session_update = self.on_session_update
        self.mqtt.on_user_register = self.on_user_register
        self.mqtt.on_user_update = self.on_user_update
        self.mqtt.on_mode_change = self.on_mode_change
        
        self.current_mode = "manual_control"
        
        self.last_position_time = 0
        self.scale_x = config.CAMERA_WIDTH / config.PROCESSING_WIDTH
        self.scale_y = config.CAMERA_HEIGHT / config.PROCESSING_HEIGHT
        
        self.csv_writer = None
        self.csv_file = None
        self.trial_count = 0
        self.session_start_time = None
        self.fps_samples = []
        
        print(f"[AI] Config loaded:")
        print(f"  - FACE_LOST_TIMEOUT: {config.FACE_LOST_TIMEOUT}s")
        print(f"  - FACE_ID_INTERVAL: {config.FACE_ID_INTERVAL}s")
        print(f"  - MQTT_SEND_INTERVAL: {config.MQTT_SEND_INTERVAL}s")

    def _init_csv_logging(self):
        """CSV 파일 초기화"""
        csv_dir = "/var/lib/ambient-node/ai_logs"
        os.makedirs(csv_dir, exist_ok=True)
        csv_path = os.path.join(csv_dir, f"ai_accuracy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

        self.csv_file = open(csv_path, 'w', newline='')  # 파일 객체 저장
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow([
            'timestamp', 'trial', 'user_id', 'confidence', 'fps',
            'num_tracked', 'mode', 'session_id', 'face_count'
        ])
        print(f"[CSV] Logging to {csv_path}")

    def log_recognition(self, user_id, confidence, fps, num_tracked):
        """얼굴 인식 결과 로깅"""
        if self.csv_writer is None:
            return
            
        self.trial_count += 1
        timestamp = datetime.now().isoformat()
        session_id = getattr(self, 'current_session_id', 'none')
        
        self.csv_writer.writerow([
            timestamp,
            self.trial_count,
            user_id or 'unknown',
            f"{confidence:.3f}" if confidence else '',
            f"{fps:.1f}" if fps else '',
            num_tracked,
            self.current_mode,
            session_id,
            len(self.tracker.tracked_faces)
        ])
        self.csv_writer.writerows([])  # 즉시 플러시

    def log_fps_summary(self):
        """FPS 통계 요약"""
        if len(self.fps_samples) > 0:
            avg_fps = sum(self.fps_samples) / len(self.fps_samples)
            print(f"[CSV] FPS Summary: avg={avg_fps:.1f}, samples={len(self.fps_samples)}")
            self.csv_writer.writerow([
                datetime.now().isoformat(), '', '', '', f"{avg_fps:.1f}", 
                '', 'SUMMARY', '', len(self.fps_samples)
            ])

    def on_mode_change(self, mode):
        print(f"[AI] Mode switched: {self.current_mode} -> {mode}")
        self.current_mode = mode
        
        # CSV에 모드 변경 기록
        if self.csv_writer:
            self.csv_writer.writerow([
                datetime.now().isoformat(), '', '', '', '', 
                0, f"MODE:{mode}", '', 0
            ])

        if mode != 'ai_tracking':
            print("[AI] Tracking stopped. Resetting tracker...")
            self.tracker.reset()
        
    def on_session_update(self, session_id, user_ids):
        print(f"[AI] Session updated: {session_id}")
        print(f"[AI] Tracking users: {user_ids}")
        self.current_session_id = session_id
        
        if self.csv_writer and self.session_start_time is None:
            self.session_start_time = time.time()

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
                if self.csv_writer:
                    self.csv_writer.writerow([
                        datetime.now().isoformat(), 'REGISTER', user_id, username, '', 
                        0, self.current_mode, '', 0
                    ])
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
        print("[AI] Service started")
        self._init_csv_logging() 
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
                    if self.current_mode != 'ai_tracking':
                        time.sleep(1.0)
                        continue
                    
                    current_time = time.time()
                    frame = self.camera.get_frame()
                    
                    if frame is None:
                        time.sleep(0.001)
                        continue
                    
                    frame_processing = cv2.resize(
                        frame, 
                        (self.config.PROCESSING_WIDTH, self.config.PROCESSING_HEIGHT)
                    )

                    detected_positions = self._detect_faces(frame_processing, face_detection)
                    
                    updated_ids, lost_faces = self.tracker.update(detected_positions, current_time)
                
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
                    
                    for face_id, user_id, confidence in newly_identified:
                        self.mqtt.publish_face_detected(user_id, confidence)
                        self.log_recognition(user_id, confidence, fps, len(self.tracker.tracked_faces))
                    
                    if current_time - self.last_position_time >= self.config.MQTT_SEND_INTERVAL:
                        session_id, selected_users = self.mqtt.get_current_session()
                        selected_faces = self.tracker.get_selected_faces(selected_users)
                        
                        for face_info in selected_faces:
                            user_id = face_info['user_id']
                            x, y = face_info['center']
                            self.mqtt.publish_face_position(user_id, x, y)
                        
                        self.last_position_time = current_time
                    
                    for lost_info in lost_faces:
                        self.mqtt.publish_face_lost(
                            lost_info['user_id'],
                            lost_info['duration']
                        )
                        print(f"[AI] User lost: {lost_info['user_id']} (duration={lost_info['duration']:.1f}s)")
                        
                        if self.csv_writer:
                            self.csv_writer.writerow([
                                datetime.now().isoformat(), 'FACE_LOST', 
                                lost_info['user_id'], '', '', 
                                0, self.current_mode, '', lost_info['duration']
                            ])
                    
                    # FPS 계산 및 로깅
                    frame_count += 1
                    if frame_count % 30 == 0:
                        elapsed = time.time() - fps_start
                        fps = 30 / elapsed
                        fps_start = time.time()
                        self.fps_samples.append(fps)
                        print(f"[INFO] FPS: {fps:.1f} | Tracked: {len(self.tracker.tracked_faces)}")
                        
                        # 10분마다 FPS 요약
                        if len(self.fps_samples) % 300 == 0:  # 10분(600초/2초)
                            self.log_fps_summary()
                    
                    time.sleep(0.001)
            
            except KeyboardInterrupt:
                print("\n[AI] Stopping...")
            finally:
                self.camera.stop()
                self.mqtt.stop()
                
                if self.csv_writer:
                    self.log_fps_summary()
                    if self.session_start_time:
                        session_duration = time.time() - self.session_start_time
                        print(f"[CSV] Session duration: {session_duration:.1f}s, trials: {self.trial_count}")
                    
                    if self.csv_file and not self.csv_file.closed:
                        self.csv_file.close()
                        print(f"[CSV] Final report saved")

    def _detect_faces(self, frame_processing, face_detection):
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

def main():
    config = Config()
    service = AIService(config)
    service.run()

if __name__ == '__main__':
    main()
