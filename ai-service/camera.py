"""카메라 스트림 관리"""
import cv2
import numpy as np
import socket
import threading
import subprocess
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
        cmd = [
            'rpicam-vid', '-t', '0',
            '--width', str(self.config.CAMERA_WIDTH),
            '--height', str(self.config.CAMERA_HEIGHT),
            '--codec', 'yuv420', '--inline', '--listen',
            '-o', f'tcp://{self.config.TCP_IP}:{self.config.TCP_PORT}',
            '--nopreview'
        ]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[Camera] rpicam-vid started")
        time.sleep(2)
        
        self.running = True
        threading.Thread(target=self._receive_stream, daemon=True).start()
    
    def _receive_stream(self):
        """TCP 스트림 수신"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.config.TCP_IP, self.config.TCP_PORT))
        print(f"[Camera] Connected to {self.config.TCP_IP}:{self.config.TCP_PORT}")
        
        frame_size = self.config.CAMERA_WIDTH * self.config.CAMERA_HEIGHT * 3 // 2
        buffer = b''
        
        while self.running:
            chunk = sock.recv(131072)
            if not chunk:
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
                except Exception as e:
                    print(f"[Camera] Decode error: {e}")
        
        sock.close()
    
    def get_frame(self):
        """최신 프레임 가져오기"""
        with self.lock:
            return self.frame_queue[0] if self.frame_queue else None
    
    def stop(self):
        """스트림 중지"""
        self.running = False
