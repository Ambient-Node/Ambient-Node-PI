"""얼굴 추적 관리"""
import threading

class FaceTracker:
    def __init__(self, max_distance=300):
        self.tracked_faces = {}
        self.next_id = 0
        self.max_distance = max_distance
        self.lock = threading.Lock()
    
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
                        'last_seen': current_time
                    })
                    updated_ids.add(closest_id)
                else:
                    self.tracked_faces[self.next_id] = {
                        'user_id': None,
                        'center': center,
                        'bbox': pos['bbox'],
                        'last_seen': current_time,
                        'last_identified': 0.0
                    }
                    updated_ids.add(self.next_id)
                    self.next_id += 1
            
            self._remove_expired(current_time, timeout=2.0)
            return updated_ids
    
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
        expired = [fid for fid, finfo in self.tracked_faces.items()
                   if current_time - finfo['last_seen'] > timeout]
        for fid in expired:
            del self.tracked_faces[fid]
    
    def identify_faces(self, recognizer, frame, current_time, interval):
        """얼굴 신원 확인"""
        with self.lock:
            identified = []
            for fid, finfo in self.tracked_faces.items():
                if current_time - finfo['last_identified'] < interval:
                    continue
                
                x, y, w, h = finfo['bbox']
                face_crop = frame[y:y+h, x:x+w]
                if face_crop.size == 0:
                    continue
                
                user_id, confidence = recognizer.recognize(face_crop)
                if user_id:
                    finfo['user_id'] = user_id
                    finfo['confidence'] = confidence
                    finfo['last_identified'] = current_time
                    identified.append((fid, user_id, confidence))
            return identified
    
    def get_selected_faces(self, selected_user_ids):
        """선택된 사용자 얼굴만"""
        with self.lock:
            return [finfo for finfo in self.tracked_faces.values()
                    if finfo['user_id'] in selected_user_ids]
