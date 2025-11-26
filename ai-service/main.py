#!/usr/bin/env python3
"""AI Service - 640x480 최적화, 엄격한 감지, 유령 좌표 제거"""

import time
import cv2
import numpy as np
import mediapipe as mp
from config import Config
from camera import CameraStream
from face_recognition import FaceRecognizer
from face_tracker import FaceTracker
from mqtt_client import MQTTClient

# NMS 함수 (중복 박스 제거용)
def non_max_suppression(boxes, scores, overlap_thresh=0.3):
    if len(boxes) == 0: return []
    if boxes.dtype.kind == "i": boxes = boxes.astype("float")
    
    pick = []
    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    idxs = np.argsort(scores)

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
        idxs = np.delete(idxs, np.concatenate(([last], np.where(overlap > overlap_thresh)[0])))
    
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
        
        # 해상도 비율 (640->640 이므로 1.0)
        self.scale_x = config.CAMERA_WIDTH / config.PROCESSING_WIDTH
        self.scale_y = config.CAMERA_HEIGHT / config.PROCESSING_HEIGHT
        
        print(f"[AI] Settings: 640x480 Res, Conf=0.7, MQTT=4Hz")

    def on_mode_change(self, mode):
        print(f"[AI] Mode: {self.current_mode} -> {mode}")
        self.current_mode = mode
        if mode != 'ai_tracking':
            self.tracker.reset()
        
    def on_session_update(self, session_id, user_ids):
        print(f"[AI] Session Update: {user_ids}")
        self.recognizer.load_selected_users(user_ids)

    def on_user_register(self, payload):
        # 기존과 동일
        user_id = payload.get('user_id')
        image_path = payload.get('image_path')
        username = payload.get('username')
        if image_path:
            self.recognizer.register_user(user_id, username, image_path)

    def on_user_update(self, payload):
        user_id = payload.get('user_id')
        username = payload.get('username')
        if user_id in self.recognizer.known_usernames:
            self.recognizer.known_usernames[user_id] = username

    def run(self):
        print("[AI] Service started (640x480 Optimized)")
        self.camera.start()
        
        # ✅ 1초에 4번 전송 (0.25초)
        target_send_interval = 0.25

        # ✅ 감지 기준 상향: 0.3 -> 0.7 (유령 박스, 다중 인식 방지)
        with mp.solutions.face_detection.FaceDetection(
            model_selection=0, # 0: 근거리(2m이내, 640해상도 적합), 1: 원거리
            min_detection_confidence=0.7 
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
                    
                    # 640x480은 리사이즈 없이 바로 처리 가능 (빠름)
                    frame_processing = frame
                    if self.config.CAMERA_WIDTH != self.config.PROCESSING_WIDTH:
                        frame_processing = cv2.resize(frame, 
                            (self.config.PROCESSING_WIDTH, self.config.PROCESSING_HEIGHT))

                    # 1. 얼굴 감지 (NMS 적용)
                    detected_positions = self._detect_faces(frame_processing, face_detection)
                    
                    # 2. 트래커 업데이트
                    updated_ids, lost_faces = self.tracker.update(detected_positions, current_time)
                
                    # 3. 신원 확인
                    force_identify = (current_time - last_global_identify_time >= self.config.FACE_ID_INTERVAL)
                    newly_identified = self.tracker.identify_faces(
                        self.recognizer, frame_processing, current_time,
                        interval=self.config.FACE_ID_INTERVAL, force_all=force_identify
                    )
                    
                    if force_identify: last_global_identify_time = current_time
                    
                    for _, user_id, confidence in newly_identified:
                        self.mqtt.publish_face_detected(user_id, confidence)
                    
                    # ✅ 4. MQTT 좌표 전송 (엄격한 필터링 적용)
                    if current_time - self.last_position_time >= target_send_interval:
                        session_id, selected_users = self.mqtt.get_current_session()
                        
                        # 트래커에서 얼굴 정보를 가져오되...
                        tracked_faces = self.tracker.get_selected_faces(selected_users)
                        
                        unique_users = {}
                        for finfo in tracked_faces:
                            # [핵심] 유령 좌표 방지 로직
                            # 얼굴이 "최근 0.3초 이내"에 실제로 감지된 경우에만 전송
                            # 트래커 메모리에 있어도, 카메라에 안 보이면 전송 안 함
                            time_since_seen = current_time - finfo['last_seen']
                            if time_since_seen < 0.3:
                                unique_users[finfo['user_id']] = finfo
                        
                        for user_id, finfo in unique_users.items():
                            x, y = finfo['center']
                            self.mqtt.publish_face_position(user_id, x, y)
                        
                        self.last_position_time = current_time
                    
                    for lost_info in lost_faces:
                        self.mqtt.publish_face_lost(lost_info['user_id'], lost_info['duration'])
                    
                    # FPS
                    frame_count += 1
                    if frame_count % 30 == 0:
                        elapsed = time.time() - fps_start
                        fps = 30 / elapsed
                        fps_start = time.time()
                        print(f"[INFO] FPS: {fps:.1f} | Tracked: {len(self.tracker.tracked_faces)}")
                    
                    time.sleep(0.001)
            
            except KeyboardInterrupt:
                pass
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

            for detection in results.detections:
                score = detection.score[0]
                bbox = detection.location_data.relative_bounding_box
                
                # 좌표 계산
                x1 = int(bbox.xmin * self.config.PROCESSING_WIDTH)
                y1 = int(bbox.ymin * self.config.PROCESSING_HEIGHT)
                x2 = int((bbox.xmin + bbox.width) * self.config.PROCESSING_WIDTH)
                y2 = int((bbox.ymin + bbox.height) * self.config.PROCESSING_HEIGHT)
                
                boxes.append([x1, y1, x2, y2])
                scores.append(score)
                raw_detections.append(bbox)

            if len(boxes) > 0:
                boxes_np = np.array(boxes)
                scores_np = np.array(scores)
                
                # NMS 실행 (중복 제거)
                picked_indices = non_max_suppression(boxes_np, scores_np, overlap_thresh=0.3)

                for i in picked_indices:
                    bbox_raw = raw_detections[i]
                    x1, y1, x2, y2 = boxes[i]
                    
                    x_center = int((bbox_raw.xmin + bbox_raw.width / 2) * self.config.PROCESSING_WIDTH * self.scale_x)
                    y_center = int((bbox_raw.ymin + bbox_raw.height / 2) * self.config.PROCESSING_HEIGHT * self.scale_y)
                    
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