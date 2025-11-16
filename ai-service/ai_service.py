#!/usr/bin/env python3
"""
AI Service - Face Recognition & Tracking (COMPLETE VERSION)
- MQTT 기반 사용자 선택 관리
- 얼굴 인식 및 위치 추적
- face-position 실시간 발행 (10Hz)
- 수동 조작 우선순위 처리
- DB Service 연동
"""

import cv2
import mediapipe as mp
import numpy as np
import os
import time
import socket
import threading
import subprocess
import argparse
import json
from tflite_runtime.interpreter import Interpreter
import paho.mqtt.client as mqtt
from datetime import datetime
from collections import deque

# -----------------------
# 명령줄 인자 파싱
# -----------------------
parser = argparse.ArgumentParser(description='Face Recognition System')
parser.add_argument('--headless', action='store_true', help='Run in headless mode')
parser.add_argument('--display', action='store_true', help='Run with display')
args = parser.parse_args()

if args.headless:
    HEADLESS_MODE = True
elif args.display:
    HEADLESS_MODE = False
else:
    print("\n=== Face Recognition System ===")
    print("Select display mode:")
    print("  0 = Show display window")
    print("  1 = Headless mode")
    while True:
        try:
            mode = int(input("Enter mode (0 or 1): ").strip())
            if mode in [0, 1]:
                HEADLESS_MODE = (mode == 1)
                break
            else:
                print("[ERROR] Please enter 0 or 1")
        except ValueError:
            print("[ERROR] Please enter a valid number")

print(f"[OK] Running in {'HEADLESS' if HEADLESS_MODE else 'DISPLAY'} mode\n")

# -----------------------
# 설정
# -----------------------
TCP_IP = '127.0.0.1'
TCP_PORT = 8888
CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1080
DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 1080
PROCESSING_WIDTH = 640
PROCESSING_HEIGHT = 360
MQTT_SEND_INTERVAL = 0.1  # 10Hz (face-position)
FACE_IDENTIFICATION_INTERVAL = 1.0
MIN_FACE_SIZE = 800
FACE_LOST_GRACE_PERIOD = 5.0

mp_face_detection = mp.solutions.face_detection

save_dir = "/var/lib/ambient-node/captures"
face_dir = "/var/lib/ambient-node/users"
os.makedirs(save_dir, exist_ok=True)
os.makedirs(face_dir, exist_ok=True)

BROKER = os.getenv("MQTT_BROKER", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))

# MQTT 토픽
TOPIC_FACE_DETECTED = "ambient/ai/face-detected"
TOPIC_FACE_POSITION = "ambient/ai/face-position"
TOPIC_FACE_LOST = "ambient/ai/face-lost"
TOPIC_USER_SELECT = "ambient/user/select"
TOPIC_USER_DESELECT = "ambient/user/deselect"
TOPIC_USER_EMBEDDING_READY = "ambient/user/embedding-ready"
TOPIC_USER_REGISTER = "ambient/user/register"
TOPIC_CONTROL_MANUAL = "ambient/control/manual"
TOPIC_DB_LOG_EVENT = "ambient/db/log-event"

# 선택된 사용자 관리
selected_users = []
selected_user_lock = threading.Lock()

# 세션 관리
current_session_id = None
session_lock = threading.Lock()

# MQTT 클라이언트
client = mqtt.Client(client_id="ai-service")

# -----------------------
# Face Tracking 상태 관리
# -----------------------
class FaceTrackingState:
    def __init__(self):
        self.state = 'idle'  # 'idle', 'tracking', 'paused'
        self.current_user_id = None
        self.current_event_id = None
        self.paused_at = None
        self.last_detection = {}
        self.lock = threading.Lock()
    
    def is_tracking(self):
        with self.lock:
            return self.state == 'tracking'
    
    def is_paused(self):
        with self.lock:
            return self.state == 'paused'
    
    def start_tracking(self, user_id, position, session_id):
        with self.lock:
            self.state = 'tracking'
            self.current_user_id = user_id
            self.current_event_id = int(time.time() * 1000)
            self.last_detection[user_id] = time.time()
        
        timestamp = datetime.now().isoformat()
        event = {
            "event_type": "face_tracking_start",
            "session_id": session_id,
            "user_id": user_id,
            "face_position_x": position[0] / DISPLAY_WIDTH,
            "face_position_y": position[1] / DISPLAY_HEIGHT,
            "timestamp": timestamp
        }
        client.publish(TOPIC_DB_LOG_EVENT, json.dumps(event))
        print(f"[TRACKING] Started for user {user_id}")
    
    def end_tracking(self, reason):
        with self.lock:
            if not self.current_event_id:
                return
            
            event_id = self.current_event_id
            user_id = self.current_user_id
            self.state = 'idle'
            self.current_event_id = None
            self.current_user_id = None
        
        timestamp = datetime.now().isoformat()
        event = {
            "event_type": "face_tracking_end",
            "event_id": event_id,
            "user_id": user_id,
            "end_reason": reason,
            "timestamp": timestamp
        }
        client.publish(TOPIC_DB_LOG_EVENT, json.dumps(event))
        print(f"[TRACKING] Ended for user {user_id}: {reason}")
    
    def pause_tracking(self):
        with self.lock:
            if self.state != 'tracking':
                return
            self.state = 'paused'
            self.paused_at = time.time()
        print(f"[TRACKING] Paused for manual override")
    
    def resume_tracking(self):
        with self.lock:
            if self.state != 'paused':
                return
            paused_duration = int(time.time() - self.paused_at)
            self.state = 'tracking'
            self.paused_at = None
        
        timestamp = datetime.now().isoformat()
        event = {
            "event_type": "face_tracking_resume",
            "event_id": self.current_event_id,
            "session_id": current_session_id,
            "user_id": self.current_user_id,
            "paused_duration_seconds": paused_duration,
            "timestamp": timestamp
        }
        client.publish(TOPIC_DB_LOG_EVENT, json.dumps(event))
        print(f"[TRACKING] Resumed after {paused_duration}s")
    
    def update_detection(self, user_id):
        with self.lock:
            self.last_detection[user_id] = time.time()
    
    def check_face_lost(self, user_id):
        with self.lock:
            if user_id not in self.last_detection:
                return True
            elapsed = time.time() - self.last_detection[user_id]
            return elapsed > FACE_LOST_GRACE_PERIOD
    
    def get_current_user(self):
        with self.lock:
            return self.current_user_id

tracking_state = FaceTrackingState()

# -----------------------
# MQTT 콜백
# -----------------------
def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[OK] MQTT broker connected: {BROKER}:{PORT}")
        client.subscribe(TOPIC_USER_SELECT)
        client.subscribe(TOPIC_USER_DESELECT)
        client.subscribe(TOPIC_USER_REGISTER)
        client.subscribe(TOPIC_CONTROL_MANUAL)
        print(f"[MQTT] Subscribed to: {TOPIC_USER_SELECT}, {TOPIC_USER_DESELECT}, {TOPIC_USER_REGISTER}, {TOPIC_CONTROL_MANUAL}")
    else:
        print(f"[ERROR] MQTT connection failed: {rc}")

def on_mqtt_message(client, userdata, msg):
    global selected_users, current_session_id
    
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        
        if msg.topic == TOPIC_USER_SELECT:
            user_list = payload.get('user_list', [])
            session_id = payload.get('session_id')
            
            with selected_user_lock:
                selected_users = [user['user_id'] for user in user_list if 'user_id' in user]
            
            with session_lock:
                current_session_id = session_id
            
            print(f"[MQTT] Selected users: {selected_users} (Session: {session_id})")
        
        elif msg.topic == TOPIC_USER_DESELECT:
            with selected_user_lock:
                selected_users = []
            
            if tracking_state.is_tracking():
                tracking_state.end_tracking('session_ended')
            
            print(f"[MQTT] All users deselected")
        
        elif msg.topic == TOPIC_USER_REGISTER:
            handle_user_registration(payload)
        
        elif msg.topic == TOPIC_CONTROL_MANUAL:
            action = payload.get('action')
            if action == 'start':
                handle_manual_override_start(payload)
            elif action == 'end':
                handle_manual_override_end(payload)
    
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse JSON: {e}")
    except Exception as e:
        print(f"[ERROR] MQTT message processing error: {e}")

def handle_manual_override_start(payload):
    if not tracking_state.is_tracking():
        return
    
    rotation_angle = payload.get('rotation_angle', 0)
    user_id = payload.get('user_id')
    
    tracking_state.pause_tracking()
    
    timestamp = datetime.now().isoformat()
    event = {
        "event_type": "manual_override_start",
        "session_id": current_session_id,
        "user_id": user_id,
        "interrupted_tracking_event_id": tracking_state.current_event_id,
        "rotation_angle": rotation_angle,
        "timestamp": timestamp
    }
    client.publish(TOPIC_DB_LOG_EVENT, json.dumps(event))
    print(f"[MANUAL] Override started - tracking paused")

def handle_manual_override_end(payload):
    if not tracking_state.is_paused():
        return
    
    override_id = payload.get('override_id')
    duration = payload.get('duration_seconds', 0)
    
    tracking_state.resume_tracking()
    
    timestamp = datetime.now().isoformat()
    event = {
        "event_type": "manual_override_end",
        "override_id": override_id,
        "session_id": current_session_id,
        "user_id": payload.get('user_id'),
        "duration_seconds": duration,
        "timestamp": timestamp
    }
    client.publish(TOPIC_DB_LOG_EVENT, json.dumps(event))
    print(f"[MANUAL] Override ended - tracking resumed")

def handle_user_registration(payload):
    user_id = payload.get('user_id')
    name = payload.get('name')
    image_path = payload.get('image_path')
    
    if not user_id or not image_path:
        print(f"[WARN] User registration missing user_id or image_path")
        return
    
    print(f"[AI] Processing user registration: {name} ({user_id})")
    
    user_folder = os.path.join(face_dir, user_id)
    
    if os.path.exists(image_path):
        try:
            img = cv2.imread(image_path)
            if img is None:
                print(f"[ERROR] Failed to load image: {image_path}")
                return
            
            embedding = get_embedding(img)
            
            embedding_path = os.path.join(user_folder, f"{user_id}_embedding.npy")
            np.save(embedding_path, embedding)
            print(f"[AI] Embedding saved: {embedding_path}")
            
            timestamp = datetime.now().isoformat()
            client.publish(TOPIC_USER_EMBEDDING_READY, json.dumps({
                "user_id": user_id,
                "name": name,
                "embedding_path": embedding_path,
                "status": "ready",
                "timestamp": timestamp
            }))
            print(f"[MQTT] Published embedding-ready for {name}")
            
            load_known_faces()
            
        except Exception as e:
            print(f"[ERROR] Embedding generation failed: {e}")
    else:
        print(f"[WARN] Image not found: {image_path}")

client.on_connect = on_mqtt_connect
client.on_message = on_mqtt_message

try:
    client.connect(BROKER, PORT, 60)
    client.loop_start()
except Exception as e:
    print(f"[ERROR] MQTT connection failed: {e}")

# -----------------------
# 프레임 처리
# -----------------------
frame_queue = deque(maxlen=1)
queue_lock = threading.Lock()

def start_rpicam_stream():
    cmd = [
        'rpicam-vid',
        '-t', '0',
        '--width', str(CAMERA_WIDTH),
        '--height', str(CAMERA_HEIGHT),
        '--codec', 'yuv420',
        '--inline',
        '--listen',
        '-o', f'tcp://{TCP_IP}:{TCP_PORT}',
        '--nopreview'
    ]
    print(f"[INFO] Starting rpicam-vid stream...")
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[OK] rpicam-vid started (PID: {process.pid})")
        return process
    except Exception as e:
        print(f"[ERROR] Failed to start rpicam-vid: {e}")
        return None

def tcp_receiver():
    print(f"[INFO] Trying to connect TCP stream: {TCP_IP}:{TCP_PORT}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    retry_count = 0
    max_retries = 10
    while retry_count < max_retries:
        try:
            sock.connect((TCP_IP, TCP_PORT))
            print("[OK] TCP stream connected")
            break
        except Exception as e:
            retry_count += 1
            print(f"[INFO] Retry {retry_count}/{max_retries}...")
            time.sleep(1)
    if retry_count >= max_retries:
        print("[ERROR] Failed to connect TCP stream after retries")
        return
    frame_size = CAMERA_WIDTH * CAMERA_HEIGHT * 3 // 2
    buffer = b''
    while True:
        try:
            chunk = sock.recv(131072)
            if not chunk:
                break
            buffer += chunk
            while len(buffer) >= frame_size:
                frame_data = buffer[:frame_size]
                buffer = buffer[frame_size:]
                try:
                    yuv_frame = np.frombuffer(frame_data, dtype=np.uint8).reshape((CAMERA_HEIGHT * 3 // 2, CAMERA_WIDTH))
                    bgr_frame = cv2.cvtColor(yuv_frame, cv2.COLOR_YUV2BGR_I420)
                    with queue_lock:
                        frame_queue.append(bgr_frame)
                except Exception:
                    continue
        except Exception as e:
            print(f"[ERROR] TCP receive error: {e}")
            break
    sock.close()

# -----------------------
# 얼굴 인식 모델
# -----------------------
def cosine_similarity(a, b):
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return 0
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

print("[INFO] Loading TFLite model...")
interpreter = Interpreter(model_path="/app/facenet.tflite")
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
input_shape = input_details[0]['shape'][1:3]
print("[OK] TFLite model loaded")

def load_known_faces():
    global known_embeddings, known_names
    known_embeddings = []
    known_names = []
    
    for user_folder in os.listdir(face_dir):
        user_path = os.path.join(face_dir, user_folder)
        if os.path.isdir(user_path):
            embedding_file = os.path.join(user_path, f"{user_folder}_embedding.npy")
            if os.path.exists(embedding_file):
                emb = np.load(embedding_file)
                known_embeddings.append(emb)
                known_names.append(user_folder)
    
    print(f"[OK] Loaded {len(known_names)} registered faces: {known_names}")
    return known_embeddings, known_names

known_embeddings, known_names = load_known_faces()

def get_embedding(face_img):
    img = cv2.resize(face_img, tuple(input_shape))
    img = img.astype(np.float32)
    img = (img - 127.5) / 128.0
    img = np.expand_dims(img, axis=0)
    interpreter.set_tensor(input_details[0]['index'], img)
    interpreter.invoke()
    embedding = interpreter.get_tensor(output_details[0]['index'])[0]
    return embedding

# -----------------------
# Face Lost 모니터링
# -----------------------
def face_lost_monitor():
    while True:
        time.sleep(1)
        
        if not tracking_state.is_tracking():
            continue
        
        current_user = tracking_state.get_current_user()
        if current_user and tracking_state.check_face_lost(current_user):
            timestamp = datetime.now().isoformat()
            
            # MQTT 발행
            client.publish(TOPIC_FACE_LOST, json.dumps({
                "user_id": current_user,
                "timestamp": timestamp
            }))
            
            # DB 로그
            event = {
                "event_type": "face_lost",
                "event_id": tracking_state.current_event_id,
                "user_id": current_user,
                "timestamp": timestamp
            }
            client.publish(TOPIC_DB_LOG_EVENT, json.dumps(event))
            print(f"[TRACKING] Face lost for user {current_user}")
            
            tracking_state.end_tracking('face_lost')

face_lost_thread = threading.Thread(target=face_lost_monitor, daemon=True)
face_lost_thread.start()

# -----------------------
# 메인 루프
# -----------------------
rpicam_process = start_rpicam_stream()
time.sleep(2)

tcp_thread = threading.Thread(target=tcp_receiver, daemon=True)
tcp_thread.start()
time.sleep(2)

print(f"[INFO] Starting face detection ({'headless' if HEADLESS_MODE else 'with display'})...")

tracked_faces = {}
next_face_id = 0

with mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.3) as face_detection:
    last_send_time = time.time()
    last_identification_time = time.time()
    frame_count = 0
    fps_start = time.time()
    fps = 0.0
    
    scale_x = DISPLAY_WIDTH / PROCESSING_WIDTH
    scale_y = DISPLAY_HEIGHT / PROCESSING_HEIGHT

    if not HEADLESS_MODE:
        window_name = "AI Service - Face Recognition (FHD)"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

    print("[INFO] Waiting for frames...")

    try:
        while True:
            with queue_lock:
                if not frame_queue:
                    time.sleep(0.001)
                    continue
                frame = frame_queue[0]

            frame_display = frame.copy() if not HEADLESS_MODE else None
            frame_processing = cv2.resize(frame, (PROCESSING_WIDTH, PROCESSING_HEIGHT))
            image_rgb = cv2.cvtColor(frame_processing, cv2.COLOR_BGR2RGB)
            results = face_detection.process(image_rgb)

            current_time = time.time()
            detected_face_positions = []
            
            # 1. 얼굴 감지
            if results.detections:
                h, w, _ = frame_processing.shape
                for detection in results.detections:
                    bboxC = detection.location_data.relative_bounding_box
                    x_min = int(bboxC.xmin * w)
                    y_min = int(bboxC.ymin * h)
                    box_width = int(bboxC.width * w)
                    box_height = int(bboxC.height * h)

                    face_area = box_width * box_height
                    if face_area < MIN_FACE_SIZE:
                        continue

                    x_min_fhd = int(x_min * scale_x)
                    y_min_fhd = int(y_min * scale_y)
                    box_width_fhd = int(box_width * scale_x)
                    box_height_fhd = int(box_height * scale_y)
                    center_x_fhd = x_min_fhd + box_width_fhd//2
                    center_y_fhd = y_min_fhd + box_height_fhd//2

                    detected_face_positions.append({
                        "bbox": (x_min, y_min, box_width, box_height),
                        "bbox_fhd": (x_min_fhd, y_min_fhd, box_width_fhd, box_height_fhd),
                        "center": (center_x_fhd, center_y_fhd)
                    })

            # 2. 얼굴 추적
            updated_face_ids = set()
            for face_pos in detected_face_positions:
                center = face_pos["center"]
                closest_id = None
                min_distance = float('inf')
                
                for face_id, face_info in tracked_faces.items():
                    old_center = face_info["center"]
                    distance = ((center[0] - old_center[0])**2 + (center[1] - old_center[1])**2)**0.5
                    if distance < min_distance and distance < 300:
                        min_distance = distance
                        closest_id = face_id
                
                if closest_id:
                    tracked_faces[closest_id]["bbox_fhd"] = face_pos["bbox_fhd"]
                    tracked_faces[closest_id]["center"] = face_pos["center"]
                    tracked_faces[closest_id]["last_seen"] = current_time
                    tracked_faces[closest_id]["bbox_processing"] = face_pos["bbox"]
                    updated_face_ids.add(closest_id)
                else:
                    tracked_faces[next_face_id] = {
                        "name": "Unidentified",
                        "user_id": None,
                        "confidence": 0.0,
                        "bbox_fhd": face_pos["bbox_fhd"],
                        "center": face_pos["center"],
                        "last_seen": current_time,
                        "last_identified": 0.0,
                        "bbox_processing": face_pos["bbox"]
                    }
                    updated_face_ids.add(next_face_id)
                    next_face_id += 1

            # 오래된 얼굴 제거
            expired_ids = [fid for fid, finfo in tracked_faces.items() 
                          if current_time - finfo["last_seen"] > 2.0]
            for fid in expired_ids:
                del tracked_faces[fid]

            # 3. 얼굴 신원 확인 (1초마다)
            if current_time - last_identification_time >= FACE_IDENTIFICATION_INTERVAL:
                for face_id in updated_face_ids:
                    if face_id not in tracked_faces:
                        continue
                    
                    face_info = tracked_faces[face_id]
                    x_min, y_min, box_width, box_height = face_info["bbox_processing"]
                    
                    face_crop = frame_processing[
                        max(0, y_min):min(PROCESSING_HEIGHT, y_min + box_height),
                        max(0, x_min):min(PROCESSING_WIDTH, x_min + box_width)
                    ]

                    if face_crop.size == 0:
                        continue

                    embedding = get_embedding(face_crop)
                    name = "Unknown"
                    user_id = None
                    confidence = 0.0
                    
                    if known_embeddings:
                        sims = [cosine_similarity(embedding, k_emb) for k_emb in known_embeddings]
                        best_idx = np.argmax(sims)
                        if sims[best_idx] > 0.4:
                            name = known_names[best_idx]
                            user_id = known_names[best_idx]
                            confidence = sims[best_idx]
                    
                    tracked_faces[face_id]["name"] = name
                    tracked_faces[face_id]["user_id"] = user_id
                    tracked_faces[face_id]["confidence"] = confidence
                    tracked_faces[face_id]["last_identified"] = current_time
                    
                    # 얼굴 인식 시 MQTT 발행
                    if name != "Unknown" and name != "Unidentified":
                        timestamp = datetime.now().isoformat()
                        client.publish(TOPIC_FACE_DETECTED, json.dumps({
                            "user_id": user_id,
                            "name": name,
                            "confidence": float(confidence),
                            "timestamp": timestamp
                        }))
                
                last_identification_time = current_time

            # 4. 선택된 사용자 필터링 및 추적 상태 관리
            with selected_user_lock:
                selected_face_infos = []
                
                for face_id, face_info in tracked_faces.items():
                    if (face_info["user_id"] in selected_users and 
                        face_info["name"] != "Unknown" and 
                        face_info["name"] != "Unidentified"):
                        
                        tracking_state.update_detection(face_info["user_id"])
                        
                        selected_face_infos.append({
                            "user_id": face_info["user_id"],
                            "name": face_info["name"],
                            "confidence": face_info["confidence"],
                            "x": face_info["center"][0],
                            "y": face_info["center"][1]
                        })
                
                # 추적 상태 전환 로직
                if selected_face_infos and not tracking_state.is_paused():
                    if not tracking_state.is_tracking():
                        first_user = selected_face_infos[0]
                        tracking_state.start_tracking(
                            first_user["user_id"],
                            (first_user["x"], first_user["y"]),
                            current_session_id
                        )
                    else:
                        current_user = tracking_state.get_current_user()
                        detected_users = [f["user_id"] for f in selected_face_infos]
                        
                        if current_user not in detected_users:
                            tracking_state.end_tracking('switched_user')
                            next_user = selected_face_infos[0]
                            tracking_state.start_tracking(
                                next_user["user_id"],
                                (next_user["x"], next_user["y"]),
                                current_session_id
                            )

            # 화면 표시
            if not HEADLESS_MODE:
                for face_id, face_info in tracked_faces.items():
                    x_min, y_min, box_width, box_height = face_info["bbox_fhd"]
                    center_x, center_y = face_info["center"]
                    
                    if tracking_state.is_paused():
                        status_color = (128, 128, 128)
                        status_text = "PAUSED"
                    elif face_info["user_id"] in selected_users:
                        if tracking_state.get_current_user() == face_info["user_id"]:
                            status_color = (0, 255, 0)
                            status_text = "TRACKING"
                        else:
                            status_color = (0, 255, 255)
                            status_text = "SELECTED"
                    elif face_info["name"] == "Unidentified":
                        continue
                    elif face_info["name"] == "Unknown":
                        status_color = (0, 165, 255)
                        status_text = "UNKNOWN"
                    else:
                        status_color = (255, 255, 0)
                        status_text = "DETECTED"
                    
                    label = f"{face_info['name']} ({status_text}) {face_info['confidence']*100:.1f}%"
                    
                    cv2.rectangle(frame_display, (x_min, y_min), (x_min+box_width, y_min+box_height), status_color, 3)
                    cv2.circle(frame_display, (center_x, center_y), 8, (0, 0, 255), -1)
                    cv2.putText(frame_display, label, (x_min, y_min-15), cv2.FONT_HERSHEY_SIMPLEX, 1.0, status_color, 2)

                tracking_status = "TRACKING" if tracking_state.is_tracking() else ("PAUSED" if tracking_state.is_paused() else "IDLE")
                status_text = f"FPS: {fps:.1f} | Tracked: {len(tracked_faces)} | Selected: {len(selected_face_infos)} | State: {tracking_status}"
                cv2.putText(frame_display, status_text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 0), 3)
                cv2.imshow(window_name, frame_display)
                key = cv2.waitKey(1) & 0xFF
                
                if key == ord('q'):
                    break

            # MQTT 위치 전송 (10Hz, 추적 중일 때만)
            if (time.time() - last_send_time >= MQTT_SEND_INTERVAL and 
                selected_face_infos and 
                tracking_state.is_tracking()):
                
                timestamp = datetime.now().isoformat()
                
                # face-position 발행 (10Hz)
                for info in selected_face_infos:
                    client.publish(TOPIC_FACE_POSITION, json.dumps({
                        "user_id": info["user_id"],
                        "x": info["x"],
                        "y": info["y"],
                        "timestamp": timestamp
                    }))
                
                last_send_time = time.time()

            frame_count += 1
            if frame_count % 30 == 0:
                elapsed = time.time() - fps_start
                fps = 30 / elapsed
                fps_start = time.time()

    except KeyboardInterrupt:
        print("\n[INFO] Terminating program...")
    finally:
        if not HEADLESS_MODE:
            cv2.destroyAllWindows()
        if rpicam_process:
            rpicam_process.terminate()
        client.loop_stop()
        client.disconnect()
        print("[INFO] Program terminated")
