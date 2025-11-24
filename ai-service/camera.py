import cv2
import numpy as np
import socket
import threading
import time
from collections import deque

class CameraStream:
    def __init__(self, config):
        self.config = config
        self.frame_queue = deque(maxlen=1)
        self.lock = threading.Lock()
        self.running = False
        self.cap = None  # 웹캠용

    def start(self):
        """카메라 스트림 시작"""
        self.running = True
        
        if self.config.CAMERA_MODE == 'webcam':
            print(f"[Camera] Using webcam (index: {self.config.WEBCAM_INDEX})")
            threading.Thread(target=self._webcam_stream, daemon=True).start()
        else:  # tcp
            print(f"[Camera] Using TCP stream at {self.config.TCP_IP}:{self.config.TCP_PORT}")
            threading.Thread(target=self._receive_stream, daemon=True).start()

    def _webcam_stream(self):
        """웹캠에서 프레임 읽기"""
        self.cap = cv2.VideoCapture(self.config.WEBCAM_INDEX)
        
        # 해상도 설정 시도
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.CAMERA_HEIGHT)
        
        # 실제 해상도 확인
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[Camera] ✅ Webcam opened: {actual_width}x{actual_height}")
        
        if not self.cap.isOpened():
            print("[Camera] ❌ Failed to open webcam")
            self.running = False
            return
        
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                print("[Camera] ❌ Failed to read frame")
                time.sleep(0.1)
                continue
            
            # 해상도가 다르면 리사이즈
            if frame.shape[1] != self.config.CAMERA_WIDTH or frame.shape[0] != self.config.CAMERA_HEIGHT:
                frame = cv2.resize(frame, (self.config.CAMERA_WIDTH, self.config.CAMERA_HEIGHT))
            
            with self.lock:
                self.frame_queue.append(frame)
            
            time.sleep(0.001)  # CPU 사용률 조절
        
        self.cap.release()
        print("[Camera] Webcam released")

    def _receive_stream(self):
        """TCP 스트림 수신 (라즈베리파이용)"""
        max_retries = 10
        retry_delay = 3
        
        for attempt in range(max_retries):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(5)
                sock.connect((self.config.TCP_IP, self.config.TCP_PORT))
                print(f"[Camera] ✅ Connected to {self.config.TCP_IP}:{self.config.TCP_PORT}")
                break
            except (ConnectionRefusedError, socket.timeout) as e:
                print(f"[Camera] ⚠️ Connection failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    print(f"[Camera] 🔄 Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print("[Camera] ❌ Max retries reached, stream unavailable")
                    self.running = False
                    return
        
        sock.settimeout(None)
        buffer = b""
        frame_size = self.config.CAMERA_WIDTH * self.config.CAMERA_HEIGHT * 3 // 2
        
        while self.running:
            try:
                chunk = sock.recv(131072)
                if not chunk:
                    print("[Camera] Stream ended")
                    self.running = False
                    break
                
                buffer += chunk
                
                while len(buffer) >= frame_size:
                    frame_data = buffer[:frame_size]
                    buffer = buffer[frame_size:]
                    
                    try:
                        yuv = np.frombuffer(frame_data, dtype=np.uint8).reshape(
                            (self.config.CAMERA_HEIGHT * 3 // 2, self.config.CAMERA_WIDTH)
                        )
                        bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
                        
                        with self.lock:
                            self.frame_queue.append(bgr)
                    except Exception:
                        continue
            
            except Exception as e:
                print(f"[Camera] ❌ Frame receive error: {e}")
                break
        
        sock.close()
        print("[Camera] TCP receiver stopped")

    def get_frame(self):
        """가장 최근 프레임 반환"""
        with self.lock:
            if self.frame_queue:
                return self.frame_queue[-1]
        return None

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
