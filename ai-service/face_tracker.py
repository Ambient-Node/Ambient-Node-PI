"""얼굴 추적 관리"""

import threading
import numpy as np

class FaceTracker:
    def __init__(self, max_distance=300, lost_timeout=8.0, enable_display=True):
        self.tracked_faces = {}
        self.next_id = 0
        self.max_distance = max_distance
        self.lost_timeout = lost_timeout
        self.lock = threading.Lock()
            
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

    # face_tracker.py - identify_faces() 메서드 수정
    def identify_faces(self, recognizer, frame, current_time, interval, force_all=False):
        """얼굴 신원 확인 (신뢰도 누적)"""
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
                
                history = finfo.get('conf_history', [])
                
                user_id, confidence = recognizer.recognize(face_crop, track_history=history)
                
                if user_id:
                    history.append(confidence)
                    if len(history) > 10:
                        history = history[-10:]
                    finfo['conf_history'] = history
                    
                    if len(history) >= 3:
                        confidence = 0.7 * confidence + 0.3 * np.mean(history[-3:])
                    
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