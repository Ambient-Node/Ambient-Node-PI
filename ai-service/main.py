#!/usr/bin/env python3
"""
AI Service - 카메라 180도 회전 적용 및 성능 최적화
"""

import time
import cv2
import numpy as np
import mediapipe as mp
import os
import json
import threading
from datetime import datetime
from tflite_runtime.interpreter import Interpreter
from config import Config
from camera import CameraStream
from mqtt_client import MQTTClient

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

class FaceRecognizer:
    def __init__(self, model_path, face_dir, similarity_threshold=0.4):
        self.face_dir = face_dir
        self.threshold = similarity_threshold
        self.known_embeddings = []
        self.known_user_ids = []
        
        self.interpreter = Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        self.input_shape = self.input_details[0]['shape'][1:3]
        
        print(f"[FaceRec] Model: {model_path} | Input: {self.input_shape}")
        if not os.path.exists(self.face_dir):
            os.makedirs(self.face_dir, exist_ok=True)

    def load_selected_users(self, user_ids):
        self.known_embeddings = []
        self.known_user_ids = []
        if not user_ids: return
        
        for user_id in user_ids:
            user_path = os.path.join(self.face_dir, user_id)
            emb_file = os.path.join(user_path, "embedding.npy")
            if os.path.exists(emb_file):
                try:
                    emb = np.load(emb_file)
                    self.known_embeddings.append(emb)
                    self.known_user_ids.append(user_id)
                except Exception: pass
        print(f"[FaceRec] Loaded {len(self.known_user_ids)} users")

    def get_embedding(self, face_img):
        """
        단순 전처리: Resize -> Normalize
        (이미지는 ai_service 루프에서 미리 180도 회전되어 들어옴)
        """
        if face_img is None or face_img.size == 0:
            return None
            
        img = cv2.resize(face_img, tuple(self.input_shape))
        img = img.astype(np.float32)
        
        img = (img - 127.5) / 128.0
        img = np.expand_dims(img, axis=0)
        
        self.interpreter.set_tensor(self.input_details[0]['index'], img)
        self.interpreter.invoke()
        return self.interpreter.get_tensor(self.output_details[0]['index'])[0]

    def recognize(self, face_crop):
        if not self.known_embeddings:
            return None, 0.0
        
        embedding = self.get_embedding(face_crop)
        if embedding is None: return None, 0.0

        sims = [self._cosine_sim(embedding, k) for k in self.known_embeddings]
        best_idx = int(np.argmax(sims))
        best_sim = sims[best_idx]
        
        if best_sim > self.threshold:
            return self.known_user_ids[best_idx], best_sim
        return None, 0.0

    @staticmethod
    def _cosine_sim(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def register_user(self, user_id, username, image_path):
        try:
            img = cv2.imread(image_path)
            if img is None: return False
            embedding = self.get_embedding(img)
            if embedding is None: return False
            
            user_dir = os.path.join(self.face_dir, user_id)
            os.makedirs(user_dir, exist_ok=True)
            np.save(os.path.join(user_dir, "embedding.npy"), embedding)
            
            with open(os.path.join(user_dir, "metadata.json"), 'w') as f:
                json.dump({"user_id": user_id, "username": username}, f)
            return True
        except Exception: return False

class AIService:
    def __init__(self, config):
        self.config = config
        self.camera = CameraStream(config)
        self.recognizer = FaceRecognizer(config.MODEL_PATH, config.FACE_DIR)
        self.mqtt = MQTTClient(config.BROKER, config.PORT)
        
        # 트래킹 변수
        self.tracked_faces = {}
        self.next_id = 0
        
        # 콜백 연결
        self.mqtt.on_session_update = lambda sid, uids: self.recognizer.load_selected_users(uids)
        self.mqtt.on_user_register = lambda pl: self.recognizer.register_user(pl['user_id'], pl['username'], pl['image_path'])
        
        self.current_mode = "manual_control"
        self.mqtt.on_mode_change = self.set_mode
        self.last_mqtt_time = 0

    def set_mode(self, mode):
        print(f"[AI] Mode: {mode}")
        self.current_mode = mode
        if mode != 'ai_tracking':
            self.tracked_faces.clear()

    def run(self):
        print("[AI] Service Started (Camera Rotated 180)")
        self.camera.start()
        
        mqtt_interval = 0.25
        
        with mp.solutions.face_detection.FaceDetection(
            model_selection=0, 
            min_detection_confidence=0.5
        ) as face_detection:
            
            fps_start = time.time()
            frame_count = 0
            
            try:
                while True:
                    if self.current_mode != 'ai_tracking':
                        time.sleep(1.0)
                        continue

                    frame = self.camera.get_frame()
                    if frame is None:
                        time.sleep(0.001)
                        continue

                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                    
                    current_time = time.time()

                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = face_detection.process(frame_rgb)
                    
                    detected_list = []
                    if results.detections:
                        boxes = []
                        scores = []
                        
                        h, w, _ = frame.shape
                        
                        for detection in results.detections:
                            score = detection.score[0]
                            bbox = detection.location_data.relative_bounding_box
                            
                            x1 = int(bbox.xmin * w)
                            y1 = int(bbox.ymin * h)
                            x2 = int((bbox.xmin + bbox.width) * w)
                            y2 = int((bbox.ymin + bbox.height) * h)
                            
                            boxes.append([x1, y1, x2, y2])
                            scores.append(score)
                        
                        if boxes:
                            pick = non_max_suppression(np.array(boxes), np.array(scores), 0.3)
                            for i in pick:
                                detected_list.append({
                                    'bbox': boxes[i], 
                                    'score': scores[i]
                                })

                    active_ids = set()
                    
                    for det in detected_list:
                        dx1, dy1, dx2, dy2 = det['bbox']
                        center = ((dx1 + dx2)//2, (dy1 + dy2)//2)
                        
                        # 매칭
                        best_id = None
                        min_dist = 100 # 매칭 거리 (해상도에 따라 조절)
                        
                        for fid, info in self.tracked_faces.items():
                            ox, oy = info['center']
                            dist = ((center[0]-ox)**2 + (center[1]-oy)**2)**0.5
                            if dist < min_dist:
                                min_dist = dist
                                best_id = fid
                        
                        if best_id is not None:
                            self.tracked_faces[best_id].update({
                                'bbox': det['bbox'],
                                'center': center,
                                'last_seen': current_time
                            })
                            active_ids.add(best_id)
                        else:
                            self.tracked_faces[self.next_id] = {
                                'bbox': det['bbox'],
                                'center': center,
                                'user_id': None,
                                'last_seen': current_time,
                                'last_id_time': 0
                            }
                            active_ids.add(self.next_id)
                            self.next_id += 1
                    
                    expired = [fid for fid, info in self.tracked_faces.items() 
                              if current_time - info['last_seen'] > 0.5]
                    for fid in expired:
                        uid = self.tracked_faces[fid]['user_id']
                        if uid: self.mqtt.publish_face_lost(uid, 0)
                        del self.tracked_faces[fid]

                    for fid in active_ids:
                        info = self.tracked_faces[fid]
                        if current_time - info['last_id_time'] > 0.5:
                            x1, y1, x2, y2 = info['bbox']
                            h, w, _ = frame.shape
                            x1, y1 = max(0, x1), max(0, y1)
                            x2, y2 = min(w, x2), min(h, y2)
                            
                            face_crop = frame[y1:y2, x1:x2]
                            
                            uid, conf = self.recognizer.recognize(face_crop)
                            
                            if uid:
                                if info['user_id'] == uid:
                                    conf = min(0.95, conf + 0.1) 
                                info['user_id'] = uid
                                self.mqtt.publish_face_detected(uid, conf)
                            
                            info['last_id_time'] = current_time

                    # 6. MQTT 좌표 전송
                    if current_time - self.last_mqtt_time >= mqtt_interval:
                        session_id, selected_users = self.mqtt.get_current_session()
                        
                        valid_faces = {}
                        for fid, info in self.tracked_faces.items():
                            if info['user_id'] in selected_users:
                                if current_time - info['last_seen'] < 0.2:
                                    valid_faces[info['user_id']] = info
                        
                        for uid, info in valid_faces.items():
                            x, y = info['center']
                            self.mqtt.publish_face_position(uid, x, y)
                        
                        self.last_mqtt_time = current_time

                    # FPS
                    frame_count += 1
                    if frame_count % 30 == 0:
                        print(f"[INFO] FPS: {30/(time.time()-fps_start):.1f} | Tracked: {len(self.tracked_faces)}")
                        fps_start = time.time()
                    
                    time.sleep(0.001)

            except KeyboardInterrupt:
                pass
            finally:
                self.camera.stop()
                self.mqtt.stop()

def main():
    config = Config()
    config.CAMERA_WIDTH = 640
    config.CAMERA_HEIGHT = 480
    config.PROCESSING_WIDTH = 640
    config.PROCESSING_HEIGHT = 480
    
    service = AIService(config)
    service.run()

if __name__ == '__main__':
    main()