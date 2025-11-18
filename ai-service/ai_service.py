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
    # 도커/비인터랙티브 환경에서 기본값: HEADLESS
    HEADLESS_MODE = True
    print("[INFO] No display mode argument given, defaulting to HEADLESS mode")

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

MQTT_SEND_INTERVAL = 0.1          # 10Hz (face-position)
FACE_IDENTIFICATION_INTERVAL = 1.0
MIN_FACE_SIZE = 800
FACE_LOST_GRACE_PERIOD = 5.0      # seconds

frame_count = 0
mp_face_detection = mp.solutions.face_detection

save_dir = "/var/lib/ambient-node/captures"
face_dir = "/var/lib/ambient-node/users"
os.makedirs(save_dir, exist_ok=True)
os.makedirs(face_dir, exist_ok=True)

BROKER = os.getenv('MQTT_BROKER', 'localhost')
PORT = int(os.getenv('MQTT_PORT', 1883))

# MQTT 토픽
TOPIC_FACE_DETECTED        = "ambient/ai/face-detected"
TOPIC_FACE_POSITION        = "ambient/ai/face-position"
TOPIC_FACE_LOST            = "ambient/ai/face-lost"
TOPIC_USER_SELECT          = "ambient/user/select"
TOPIC_USER_DESELECT        = "ambient/user/deselect"
TOPIC_USER_EMBEDDING_READY = "ambient/user/embedding-ready"
TOPIC_USER_REGISTER        = "ambient/user/register"
TOPIC_CONTROL_MANUAL       = "ambient/control/manual"
TOPIC_DB_LOG_EVENT         = "ambient/db/log-event"

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
        # 'idle', 'tracking', 'paused'
        self.state = 'idle'
        self.current_user_id = None
        self.current_event_id = None
        self.paused_at = None
        self.last_detection = {}  # {user_id: last_timestamp}
        self.lock = threading.Lock()

    def start_tracking(self, user_id, center, session_id):
        with self.lock:
            self.state = 'tracking'
            self.current_user_id = user_id
            # 이벤트 ID는 세션 + 타임스탬프로 생성
            self.current_event_id = f"{session_id}_{int(time.time())}" if session_id else None
            self.last_detection[user_id] = time.time()
            print(f"[TRACKING] START for user {user_id} (session={session_id})")

            # DB 로그
            event = {
                "event_type": "tracking_started",
                "event_id": self.current_event_id,
                "user_id": user_id,
                "x": center[0],
                "y": center[1],
                "timestamp": datetime.now().isoformat()
            }
            client.publish(TOPIC_DB_LOG_EVENT, json.dumps(event))

    def end_tracking(self, reason):
        with self.lock:
            if self.state != 'tracking':
                return
            user_id = self.current_user_id
            event_id = self.current_event_id
            self.state = 'idle'
            self.current_user_id = None
            self.current_event_id = None
            print(f"[TRACKING] END for user {user_id} (reason={reason})")

            # DB 로그
            event = {
                "event_type": "tracking_finished",
                "event_id": event_id,
                "user_id": user_id,
                "reason": reason,
                "timestamp": datetime.now().isoformat()
            }
            client.publish(TOPIC_DB_LOG_EVENT, json.dumps(event))

    def update_detection(self, user_id):
        with self.lock:
            self.last_detection[user_id] = time.time()

    def check_face_lost(self, user_id):
        with self.lock:
            if self.state != 'tracking':
                return False
            last = self.last_detection.get(user_id)
            if last is None:
                return False
            return (time.time() - last) > FACE_LOST_GRACE_PERIOD

    def get_current_user(self):
        with self.lock:
            return self.current_user_id

    def pause(self):
        with self.lock:
            if self.state == 'tracking':
                self.state = 'paused'
                self.paused_at = time.time()
                print("[TRACKING] Paused by manual control")

    def resume(self):
        with self.lock:
            if self.state == 'paused':
                self.state = 'tracking'
                print("[TRACKING] Resumed by manual control")

    def is_tracking(self):
        with self.lock:
            return self.state == 'tracking'

    def is_paused(self):
        with self.lock:
            return self.state == 'paused'

tracking_state = FaceTrackingState()

# -----------------------
# 얼굴 임베딩 관련
# -----------------------
def cosine_similarity(a, b):
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

print("[INFO] Loading TFLite model...")
TFLITE_MODEL_PATH_ENV = os.getenv('TFLITE_MODEL_PATH', '/app/facenet.tflite')
interpreter = Interpreter(model_path=TFLITE_MODEL_PATH_ENV)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
input_shape = input_details[0]['shape'][1:3]
print("[OK] TFLite model loaded")

known_embeddings = []
known_names = []

def load_known_faces():
    """
    /var/lib/ambient-node/users/{user_id}/ 디렉토리에서
    {user_id}_embedding.npy 파일을 로드
    """
    global known_embeddings, known_names
    known_embeddings = []
    known_names = []

    if not os.path.exists(face_dir):
        print(f"[WARN] Face directory not found: {face_dir}")
        return [], []

    for user_id in os.listdir(face_dir):
        user_path = os.path.join(face_dir, user_id)
        if not os.path.isdir(user_path):
            continue

        embedding_file = os.path.join(user_path, f"{user_id}_embedding.npy")
        if os.path.exists(embedding_file):
            try:
                emb = np.load(embedding_file)
                known_embeddings.append(emb)
                known_names.append(user_id)
                print(f"[OK] Loaded embedding for user: {user_id}")
            except Exception as e:
                print(f"[ERROR] Failed to load {embedding_file}: {e}")
        else:
            print(f"[WARN] Embedding not found for user: {user_id}")

    print(f"[OK] Total registered faces: {len(known_names)} - {known_names}")
    return known_embeddings, known_names

def get_embedding(face_img):
    img = cv2.resize(face_img, tuple(input_shape))
    img = img.astype(np.float32)
    img = (img - 127.5) / 128.0
    img = np.expand_dims(img, axis=0)
    interpreter.set_tensor(input_details[0]['index'], img)
    interpreter.invoke()
    embedding = interpreter.get_tensor(output_details[0]['index'])[0]
    return embedding

load_known_faces()

# -----------------------
# 사용자 등록 처리 (임베딩 생성)
# -----------------------
def handle_user_register(payload):
    """
    payload 예시:
    {
      "user_id": "u001",
      "name": "Alice"
    }
    /var/lib/ambient-node/users/u001/u001.png 같은 얼굴 사진이 있다고 가정
    """
    try:
        data = json.loads(payload.decode('utf-8'))
    except Exception as e:
        print(f"[ERROR] Invalid register payload: {e}")
        return

    user_id = data.get("user_id")
    name = data.get("name") or user_id
    if not user_id:
        print("[ERROR] user_id is required for registration")
        return

    user_folder = os.path.join(face_dir, user_id)
    os.makedirs(user_folder, exist_ok=True)

    # 얼굴 이미지 경로 (필요 시 이 부분은 프로젝트에 맞게 수정)
    # 예: u001/u001.png 또는 u001/u001.jpg
    candidate_paths = [
        os.path.join(user_folder, f"{user_id}.png"),
        os.path.join(user_folder, f"{user_id}.jpg"),
        os.path.join(user_folder, f"{user_id}.jpeg"),
    ]
    image_path = None
    for p in candidate_paths:
        if os.path.exists(p):
            image_path = p
            break

    if image_path is None:
        print(f"[ERROR] No face image found for user {user_id} in {user_folder}")
        return

    print(f"[AI] Generating embedding for user {user_id} from {image_path}")

    try:
        img = cv2.imread(image_path)
        if img is None:
            raise RuntimeError("Failed to read image")

        # 중앙 얼굴 crop 용도로 전체 이미지를 그대로 사용 (필요시 개선)
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
        print(f"[ERROR] Embedding generation failed for {user_id}: {e}")
        client.publish(TOPIC_USER_EMBEDDING_READY, json.dumps({
            "user_id": user_id,
            "name": name,
            "status": "failed",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }))

# -----------------------
# MQTT 콜백
# -----------------------
def on_mqtt_connect(client_obj, userdata, flags, rc, properties=None):
    print(f"[OK] MQTT broker connected: {BROKER}:{PORT} (rc={rc})")
    client_obj.subscribe([
        (TOPIC_USER_SELECT, 0),
        (TOPIC_USER_DESELECT, 0),
        (TOPIC_USER_REGISTER, 0),
        (TOPIC_CONTROL_MANUAL, 0),
    ])
    print("[MQTT] Subscribed to user/control topics")

def on_mqtt_message(client_obj, userdata, msg):
    global selected_users, current_session_id

    try:
        payload = msg.payload.decode('utf-8')
    except Exception:
        payload = msg.payload

    # 사용자 선택
    if msg.topic == TOPIC_USER_SELECT:
        try:
            data = json.loads(payload)
            user_list = data.get("user_list", [])
            session_id = data.get("session_id")
            with selected_user_lock:
                selected_users = [u["user_id"] for u in user_list if "user_id" in u]
            with session_lock:
                current_session_id = session_id
            print(f"[MQTT] Selected users: {selected_users} (session={session_id})")
        except Exception as e:
            print(f"[ERROR] Failed to handle user-select: {e}")

    # 사용자 선택 해제
    elif msg.topic == TOPIC_USER_DESELECT:
        with selected_user_lock:
            selected_users = []
        tracking_state.end_tracking('user_deselected')
        print("[MQTT] All users deselected")

    # 사용자 등록 (임베딩 생성)
    elif msg.topic == TOPIC_USER_REGISTER:
        handle_user_register(msg.payload)

    # 수동 제어 (일시정지/재개 등)
    elif msg.topic == TOPIC_CONTROL_MANUAL:
        try:
            data = json.loads(payload)
            action = data.get("action")
            if action == "pause":
                tracking_state.pause()
            elif action == "resume":
                tracking_state.resume()
        except Exception as e:
            print(f"[ERROR] Failed to handle manual control: {e}")

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
    global frame_count

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
            print(f"[INFO] Retry {retry_count}/{max_retries}... ({e})")
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
                print("[WARN] TCP stream closed by peer")
                break

            buffer += chunk

            while len(buffer) >= frame_size:
                frame_data = buffer[:frame_size]
                buffer = buffer[frame_size:]

                try:
                    yuv_frame = np.frombuffer(
                        frame_data,
                        dtype=np.uint8
                    ).reshape((CAMERA_HEIGHT * 3 // 2, CAMERA_WIDTH))

                    bgr_frame = cv2.cvtColor(
                        yuv_frame,
                        cv2.COLOR_YUV2BGR_I420
                    )

                    with queue_lock:
                        frame_queue.append(bgr_frame)

                    frame_count += 1
                    # if frame_count % 30 == 0:
                        # print(f"[DEBUG] Received {frame_count} frames from TCP")

                except Exception as e:
                    print(f"[WARN] Frame decode error: {e}")
                    continue

        except Exception as e:
            print(f"[ERROR] TCP receive error: {e}")
            break

    sock.close()
    print("[INFO] TCP receiver stopped")

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

            client.publish(TOPIC_FACE_LOST, json.dumps({
                "user_id": current_user,
                "timestamp": timestamp
            }))

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

with mp_face_detection.FaceDetection(
    model_selection=1,
    min_detection_confidence=0.3
) as face_detection:
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
                    center_x_fhd = x_min_fhd + box_width_fhd // 2
                    center_y_fhd = y_min_fhd + box_height_fhd // 2

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
                    distance = ((center[0] - old_center[0]) ** 2 +
                                (center[1] - old_center[1]) ** 2) ** 0.5
                    if distance < min_distance and distance < 300:
                        min_distance = distance
                        closest_id = face_id

                if closest_id is not None:
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
            expired_ids = [
                fid for fid, finfo in tracked_faces.items()
                if current_time - finfo["last_seen"] > 2.0
            ]
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
                        best_idx = int(np.argmax(sims))
                        best_sim = sims[best_idx]
                        best_name = known_names[best_idx]
                        print(f"[SIM] best={best_sim:.3f} for user {best_name}")

                        # 테스트용으로 threshold를 0.3으로 약간 낮춰봄
                        if best_sim > 0.3:
                            name = best_name
                            user_id = best_name
                            confidence = best_sim

                    tracked_faces[face_id]["name"] = name
                    tracked_faces[face_id]["user_id"] = user_id
                    tracked_faces[face_id]["confidence"] = confidence
                    tracked_faces[face_id]["last_identified"] = current_time

                    if name not in ("Unknown", "Unidentified"):
                        print(f"[RECOG] name={name}, user_id={user_id}, conf={confidence:.3f}")
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
                        face_info["name"] not in ("Unknown", "Unidentified")):

                        tracking_state.update_detection(face_info["user_id"])

                        selected_face_infos.append({
                            "user_id": face_info["user_id"],
                            "name": face_info["name"],
                            "confidence": face_info["confidence"],
                            "x": face_info["center"][0],
                            "y": face_info["center"][1]
                        })

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

                    cv2.rectangle(
                        frame_display,
                        (x_min, y_min),
                        (x_min + box_width, y_min + box_height),
                        status_color,
                        3
                    )
                    cv2.circle(frame_display, (center_x, center_y), 8, (0, 0, 255), -1)
                    cv2.putText(
                        frame_display,
                        label,
                        (x_min, y_min - 15),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.0,
                        status_color,
                        2
                    )

                tracking_status = ("TRACKING" if tracking_state.is_tracking()
                                   else ("PAUSED" if tracking_state.is_paused() else "IDLE"))
                status_text = (f"FPS: {fps:.1f} | Tracked: {len(tracked_faces)} | "
                               f"Selected: {len(selected_face_infos)} | State: {tracking_status}")
                cv2.putText(
                    frame_display,
                    status_text,
                    (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.2,
                    (255, 255, 0),
                    3
                )
                cv2.imshow(window_name, frame_display)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break

            # MQTT 위치 전송 (10Hz, 추적 중일 때만)
            if (time.time() - last_send_time >= MQTT_SEND_INTERVAL and
                selected_face_infos and
                tracking_state.is_tracking()):

                timestamp = datetime.now().isoformat()
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
                fps = 30.0 / max(elapsed, 1e-6)
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
