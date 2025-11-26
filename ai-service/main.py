#!/usr/bin/env python3
"""AI Service - 메인 실행 파일 (NMS 적용 및 실시간성 최적화)"""

import time
import cv2
import numpy as np  # ✅ NMS 연산을 위한 필수 라이브러리
import mediapipe as mp
from config import Config
from camera import CameraStream
from face_recognition import FaceRecognizer
from face_tracker import FaceTracker
from mqtt_client import MQTTClient

# ==========================================
# ✅ 1. NMS (Non-Maximum Suppression) 함수 추가
# ==========================================
def non_max_suppression(boxes, scores, overlap_thresh=0.3):
    """
    겹쳐있는 박스들 중 신뢰도가 가장 높은 하나만 남기고 제거합니다.
    """
    if len(boxes) == 0:
        return []

    if boxes.dtype.kind == "i":
        boxes = boxes.astype("float")

    pick = []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]

    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    idxs = np.argsort(scores)  # 점수 기준 정렬

    while len(idxs) > 0:
        last = len(idxs) - 1
        i = idxs[last]
        pick.append(i)

        xx1 = np.maximum(x1[i], x1[idxs[:last]])
        yy1 = np.maximum(y1[i], y1[idxs[:last]])
        xx2 = np.minimum(x2[i], x2[idxs[:last]])
        yy2 = np.minimum(y2[i], y2[idxs[:last]])

        w = np.maximum(0, xx2 - xx1 + 1)
        h = np.maximum(0, yy2 - yy1 + 1)

        overlap = (w * h) / area[idxs[:last]]

        idxs = np.delete(idxs, np.concatenate(([last],
            np.where(overlap > overlap_thresh)[0])))

    return pick


class AIService:
    def __init__(self, config):
        self.config = config
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
        self.mqtt.on_mode_change = self.on_mode_change
        self.current_mode = "manual_control"
        self.last_position_time = 0
        self.scale_x = config.CAMERA_WIDTH / config.PROCESSING_WIDTH
        self.scale_y = config.CAMERA_HEIGHT / config.PROCESSING_HEIGHT
        
        print(f"[AI] Config loaded:")
        print(f"  - FACE_LOST_TIMEOUT: {config.FACE_LOST_TIMEOUT}s")
        print(f"  - FACE_ID_INTERVAL: {config.FACE_ID_INTERVAL}s")
        print(f"  - MQTT_SEND_INTERVAL: {config.MQTT_SEND_INTERVAL}s")

    def on_mode_change(self, mode):
        print(f"[AI] Mode switched: {self.current_mode} -> {mode}")
        self.current_mode = mode
        if mode != 'ai_tracking':
            print("[AI] Tracking stopped. Resetting tracker...")
            self.tracker.reset()
        
    def on_session_update(self, session_id, user_ids):
        print(f"[AI] Session updated: {session_id}")
        print(f"[AI] Tracking users: {user_ids}")
        self.recognizer.load_selected_users(user_ids)

    def on_user_register(self, payload):
        user_id = payload.get('user_id')
        username = payload.get('username')
        image_path = payload.get('image_path')
        print(f"[AI] New user registration: {username} ({user_id})")
        if not image_path: return
        try:
            self.recognizer.register_user(user_id, username, image_path)
        except Exception as e:
            print(f"[AI] Registration error: {e}")

    def on_user_update(self, payload):
        user_id = payload.get('user_id')
        username = payload.get('username')
        if user_id in self.recognizer.known_usernames:
            self.recognizer.known_usernames[user_id] = username

    def run(self):
        print("[AI] Service started")
        self.camera.start()
        
        # ✅ 2. 신뢰도 상향 (0.3 -> 0.5) : 불확실한 박스 원천 차단
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.5
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

                    # ✅ 3. NMS가 적용된 감지 함수 사용
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
                    
                    # 신원 확인 정보 전송
                    for face_id, user_id, confidence in newly_identified:
                        self.mqtt.publish_face_detected(user_id, confidence)
                    
                    # ✅ 4. 실시간 좌표 전송 (중복 User ID 필터링)
                    if current_time - self.last_position_time >= self.config.MQTT_SEND_INTERVAL:
                        session_id, selected_users = self.mqtt.get_current_session()
                        selected_faces = self.tracker.get_selected_faces(selected_users)
                        
                        # 안전장치: 혹시라도 같은 UserID가 2개라면 하나만 전송
                        unique_users = {}
                        for face_info in selected_faces:
                            unique_users[face_info['user_id']] = face_info
                        
                        for user_id, face_info in unique_users.items():
                            x, y = face_info['center']
                            self.mqtt.publish_face_position(user_id, x, y)
                        
                        self.last_position_time = current_time
                    
                    for lost_info in lost_faces:
                        self.mqtt.publish_face_lost(lost_info['user_id'], lost_info['duration'])
                        print(f"[AI] User lost: {lost_info['user_id']} (duration={lost_info['duration']:.1f}s)")
                    
                    # FPS 출력
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
                self.camera.stop()
                self.mqtt.stop()

    def _detect_faces(self, frame_processing, face_detection):
        rgb = cv2.cvtColor(frame_processing, cv2.COLOR_BGR2RGB)
        results = face_detection.process(rgb)
        
        detected = []
        if results.detections:
            boxes = []
            scores = []
            raw_detections = []

            # 1단계: 모든 박스 수집
            for detection in results.detections:
                score = detection.score[0]
                bbox = detection.location_data.relative_bounding_box
                
                # Processing 해상도 기준 좌표 (NMS용)
                x1 = int(bbox.xmin * self.config.PROCESSING_WIDTH)
                y1 = int(bbox.ymin * self.config.PROCESSING_HEIGHT)
                x2 = int((bbox.xmin + bbox.width) * self.config.PROCESSING_WIDTH)
                y2 = int((bbox.ymin + bbox.height) * self.config.PROCESSING_HEIGHT)
                
                boxes.append([x1, y1, x2, y2])
                scores.append(score)
                raw_detections.append(bbox)

            # 2단계: NMS로 중복 제거 (핵심)
            if len(boxes) > 0:
                boxes_np = np.array(boxes)
                scores_np = np.array(scores)
                
                # IoU 0.3 (30%) 이상 겹치면 중복으로 간주하고 제거
                picked_indices = non_max_suppression(boxes_np, scores_np, overlap_thresh=0.3)

                # 3단계: 살아남은 박스만 변환 후 리스트에 추가
                for i in picked_indices:
                    bbox_raw = raw_detections[i]
                    x1, y1, x2, y2 = boxes[i]

                    # FHD 좌표계 변환 (선풍기 제어용)
                    x_center_fhd = int((bbox_raw.xmin + bbox_raw.width / 2) * self.config.PROCESSING_WIDTH * self.scale_x)
                    y_center_fhd = int((bbox_raw.ymin + bbox_raw.height / 2) * self.config.PROCESSING_HEIGHT * self.scale_y)
                    
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