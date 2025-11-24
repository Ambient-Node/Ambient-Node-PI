# visualizer.py
"""얼굴 인식 시각화"""

import cv2
import numpy as np
from datetime import datetime


class FaceDetectionVisualizer:
    """얼굴 인식 결과를 화면에 실시간으로 표시"""
    
    def __init__(self, window_name="Ambient AI - Face Detection", enable_display=True):
        self.window_name = window_name
        self.enable_display = enable_display
        
        if self.enable_display:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.window_name, 1280, 720)
        
    def draw_face_boxes(self, frame, detections):
        """
        얼굴에 바운딩 박스와 정보 표시
        
        Args:
            frame: 원본 프레임
            detections: [{"bbox": (x, y, w, h), "user_id": "u123", "username": "홍길동", "confidence": 0.95}, ...]
        """
        if not self.enable_display:
            return frame
            
        display_frame = frame.copy()
        
        for det in detections:
            x, y, w, h = det['bbox']
            user_id = det.get('user_id')
            username = det.get('username', 'Unknown')
            confidence = det.get('confidence', 0.0)
            
            # 바운딩 박스 색상
            if user_id:
                color = (0, 255, 0)  # 초록 - 인식됨
                label = username
                conf_text = f"{confidence:.2%}"
            else:
                color = (0, 0, 255)  # 빨강 - 미인식
                label = "Unknown"
                conf_text = "N/A"
            
            # 바운딩 박스
            cv2.rectangle(display_frame, (x, y), (x + w, y + h), color, 3)
            
            # 좌표 표시 (좌상단)
            coord_text = f"({x}, {y})"
            cv2.putText(display_frame, coord_text, (x, y - 40), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            
            # 사용자 이름
            cv2.putText(display_frame, label, (x, y - 15), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            
            # 신뢰도
            cv2.putText(display_frame, conf_text, (x, y + h + 25), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
            # 중심점
            center_x, center_y = x + w // 2, y + h // 2
            cv2.circle(display_frame, (center_x, center_y), 6, color, -1)
            cv2.putText(display_frame, f"({center_x},{center_y})", 
                       (center_x + 10, center_y), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
            
            # 크기 정보
            size_text = f"W:{w} H:{h}"
            cv2.putText(display_frame, size_text, (x + w - 100, y + h + 25), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # 상단 정보 패널
        self._draw_info_panel(display_frame, len(detections))
        
        return display_frame
    
    def _draw_info_panel(self, frame, face_count):
        """화면 상단 정보 패널"""
        h, w = frame.shape[:2]
        
        # 반투명 배경
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 70), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
        
        # 시간
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        # 감지된 얼굴 수
        cv2.putText(frame, f"Tracking: {face_count}", (10, 60), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        
        # 프로젝트명
        cv2.putText(frame, "Ambient Node AI", (w - 250, 35), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 200, 255), 2)
        
        # 종료 안내
        cv2.putText(frame, "Press ESC to quit", (w - 250, 65), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    
    def show(self, frame):
        """프레임 표시"""
        if not self.enable_display:
            return -1
        cv2.imshow(self.window_name, frame)
        return cv2.waitKey(1) & 0xFF
    
    def close(self):
        """윈도우 닫기"""
        if self.enable_display:
            cv2.destroyAllWindows()
