"""얼굴 추적 관리"""

import threading

class FaceTracker:
    def __init__(self, max_distance=300, lost_timeout=8.0, enable_display=True):
        self.tracked_faces = {}
        self.next_id = 0
        self.max_distance = max_distance
        self.lost_timeout = lost_timeout
        self.lock = threading.Lock()
        
        # 시각화 설정
        self.enable_display = enable_display
        if self.enable_display:
            self.window_name = "Ambient AI - Face Detection"
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.window_name, 1280, 720)
            
    def reset(self):
        """추적 정보 초기화 (모드 변경 시 호출)"""
        with self.lock:
            self.tracked_faces.clear()
            self.next_id = 0
            print("[Tracker] Memory cleared (Reset)")

    def update(self, detected_positions, current_time):
        """감지된 얼굴로 추적 업데이트"""
        with self.lock:
            updated_ids = set()
            
            for pos in detected_positions:
                center = pos['center']
                closest_id = self._find_closest(center)
                
                if closest_id is not None:
                    self.tracked_faces[closest_id].update({
                        'center': center,
                        'bbox': pos['bbox'],
                        'last_seen': current_time,
                    })
                    updated_ids.add(closest_id)
                else:
                    self.tracked_faces[self.next_id] = {
                        'user_id': None,
                        'center': center,
                        'bbox': pos['bbox'],
                        'last_seen': current_time,
                        'last_identified': 0.0,
                    }
                    updated_ids.add(self.next_id)
                    self.next_id += 1
            
            lost_faces = self._remove_expired(current_time, timeout=self.lost_timeout)
            return updated_ids, lost_faces

    def _find_closest(self, center):
        """가장 가까운 얼굴 찾기"""
        min_dist = float('inf')
        closest_id = None
        
        for fid, finfo in self.tracked_faces.items():
            old_center = finfo['center']
            dist = ((center[0] - old_center[0]) ** 2 +
                   (center[1] - old_center[1]) ** 2) ** 0.5
            if dist < min_dist and dist < self.max_distance:
                min_dist = dist
                closest_id = fid
        
        return closest_id

    def _remove_expired(self, current_time, timeout):
        """타임아웃된 얼굴 제거"""
        expired = [
            fid for fid, finfo in self.tracked_faces.items()
            if current_time - finfo['last_seen'] > timeout
        ]
        
        lost_faces = []
        for fid in expired:
            finfo = self.tracked_faces[fid]
            user_id = finfo.get('user_id')
            if user_id:
                first_seen = finfo.get('first_seen', finfo['last_seen'])
                duration = max(0.0, current_time - first_seen)
                lost_faces.append({
                    'user_id': user_id,
                    'duration': duration,
                })
            del self.tracked_faces[fid]
        
        return lost_faces

    def identify_faces(self, recognizer, frame, current_time, interval, force_all=False):
        """얼굴 신원 확인
        
        Args:
            force_all: True면 interval 무시하고 모든 얼굴 인식
        """
        with self.lock:
            newly_identified = []
            
            for fid, finfo in self.tracked_faces.items():
                if not force_all and current_time - finfo['last_identified'] < interval:
                    continue
                
                bbox = finfo['bbox']
                x1, y1, x2, y2 = bbox
                face_crop = frame[y1:y2, x1:x2]
                
                if face_crop.size == 0:
                    continue
                
                user_id, confidence = recognizer.recognize(face_crop)
                
                if user_id:
                    finfo['user_id'] = user_id
                    finfo['confidence'] = confidence
                    finfo['last_identified'] = current_time
                    if 'first_seen' not in finfo:
                        finfo['first_seen'] = current_time
                    newly_identified.append((fid, user_id, confidence))
            
            return newly_identified

    def get_selected_faces(self, selected_user_ids):
        """선택된 사용자 얼굴만"""
        with self.lock:
            return [
                {**finfo, 'face_id': fid}
                for fid, finfo in self.tracked_faces.items()
                if finfo.get('user_id') in selected_user_ids
            ]
            
    '''
    def draw_tracked_faces(self, frame, recognizer):
        """추적 중인 얼굴을 프레임에 그리기"""
        if not self.enable_display:
            return frame
        
        display_frame = frame.copy()
        
        with self.lock:
            for fid, finfo in self.tracked_faces.items():
                bbox = finfo['bbox']
                x1, y1, x2, y2 = bbox
                user_id = finfo.get('user_id')
                confidence = finfo.get('confidence', 0.0)

                if user_id:
                    color = (0, 255, 0)  # 초록
                    username = recognizer.known_usernames.get(user_id, user_id)
                    label = f"{username}"
                    conf_text = f"{confidence:.2%}"
                else:
                    color = (0, 0, 255)  # 빨강
                    label = f"Unknown #{fid}"
                    conf_text = "N/A"
                
                # 바운딩 박스
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 3)
                
                # 좌표 표시 (좌상단 위)
                coord_text = f"({x1}, {y1})"
                cv2.putText(display_frame, coord_text, (x1, y1 - 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
                # 사용자 이름
                cv2.putText(display_frame, label, (x1, y1 - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                
                # 신뢰도
                cv2.putText(display_frame, conf_text, (x1, y2 + 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                
                # 중심점
                center = finfo['center']
                cv2.circle(display_frame, center, 6, color, -1)
                cv2.putText(display_frame, f"{center}", (center[0] + 10, center[1]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
                
                # 크기 정보 (우하단)
                w, h = x2 - x1, y2 - y1
                size_text = f"W:{w} H:{h}"
                cv2.putText(display_frame, size_text, (x2 - 100, y2 + 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # 상단 정보 패널
        self._draw_info_panel(display_frame)
        
        return display_frame
    '''
    
    def _draw_info_panel(self, frame):
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
        
        # 추적 중인 얼굴 수
        face_count = len(self.tracked_faces)
        cv2.putText(frame, f"Tracking: {face_count}", (10, 60),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        
        # 프로젝트명
        cv2.putText(frame, "Ambient Node AI", (w - 250, 35),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 200, 255), 2)
        
        # 종료 안내
        cv2.putText(frame, "Press ESC to quit", (w - 250, 65),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    
    def show_frame(self, frame):
        """화면 표시 및 키 입력 받기"""
        if not self.enable_display:
            return -1
        
        cv2.imshow(self.window_name, frame)
        return cv2.waitKey(1) & 0xFF
    
    def close_display(self):
        """디스플레이 창 닫기"""
        if self.enable_display:
            cv2.destroyAllWindows()
