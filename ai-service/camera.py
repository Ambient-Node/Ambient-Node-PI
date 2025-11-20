# camera.py

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
        """카메라 스트림 시작 (이미 rpicam-stream.service가 rpicam-vid를 실행 중이라고 가정)"""
        print(f"[Camera] Using external rpicam-vid at tcp://{self.config.TCP_IP}:{self.config.TCP_PORT}")
        self.running = True
        threading.Thread(target=self._receive_stream, daemon=True).start()

    def _receive_stream(self):
        """TCP 스트림 수신"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.config.TCP_IP, self.config.TCP_PORT))
        print(f"[Camera] Connected to {self.config.TCP_IP}:{self.config.TCP_PORT}")

        data = b""
        frame_size = self.config.CAMERA_WIDTH * self.config.CAMERA_HEIGHT * 3 // 2  # YUV420

        while self.running:
            while len(data) < frame_size:
                packet = sock.recv(4096)
                if not packet:
                    print("[Camera] Stream ended")
                    self.running = False
                    break
                data += packet

            if not self.running:
                break

            frame_data = data[:frame_size]
            data = data[frame_size:]

            yuv = np.frombuffer(frame_data, dtype=np.uint8).reshape(
                (self.config.CAMERA_HEIGHT * 3 // 2, self.config.CAMERA_WIDTH)
            )
            bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)

            with self.lock:
                self.frame_queue.append(bgr)

        sock.close()
        print("[Camera] Receiver stopped")

    def get_frame(self):
        """가장 최근 프레임 반환"""
        with self.lock:
            if self.frame_queue:
                return self.frame_queue[-1].copy()
        return None

    def stop(self):
        self.running = False
