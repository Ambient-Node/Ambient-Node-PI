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


    def start(self):
        """카메라 스트림 시작"""
        print(f"[Camera] Using external rpicam-vid at tcp://{self.config.TCP_IP}:{self.config.TCP_PORT}")
        self.running = True
        threading.Thread(target=self._receive_stream, daemon=True).start()


    def _receive_stream(self):
        """TCP 스트림 수신 (최적화)"""
        max_retries = 10
        retry_delay = 3
        
        for attempt in range(max_retries):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)  # 2MB 버퍼
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # 지연 최소화
                
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
        
        sock.settimeout(None)  # 블로킹 모드
        
        buffer = b""
        frame_size = self.config.CAMERA_WIDTH * self.config.CAMERA_HEIGHT * 3 // 2  # YUV420


        while self.running:
            try:
                # ✅ 128KB씩 수신 (원본과 동일)
                chunk = sock.recv(131072)
                if not chunk:
                    print("[Camera] Stream ended")
                    self.running = False
                    break
                
                buffer += chunk
                
                # 프레임 완성 체크
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
        print("[Camera] Receiver stopped")


    def get_frame(self):
        """가장 최근 프레임 반환 (복사 없음)"""
        with self.lock:
            if self.frame_queue:
                return self.frame_queue[-1]  # ✅ copy() 제거
        return None


    def stop(self):
        self.running = False
