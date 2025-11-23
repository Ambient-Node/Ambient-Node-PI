"""얼굴 추적 관리"""
import threading


class FaceTracker:
    def __init__(self, max_distance=300, lost_timeout=8.0):
        self.tracked_faces = {}
        self.next_id = 0
        self.max_distance = max_distance
        self.lost_timeout = lost_timeout  # Config에서 주입받음
        self.lock = threading.Lock()

    def update(self, detected_positions, current_time):
        """감지된 얼굴로 추적 업데이트

        Returns:
            updated_ids: 이번 프레임에서 갱신된 face_id 집합
            lost_faces:  타임아웃으로 사라진 얼굴 정보 리스트
                         [{'user_id': str, 'duration': float}, ...]
        """
        with self.lock:
            updated_ids = set()

            # 새로 감지된/기존 얼굴 위치 업데이트
            for pos in detected_positions:
                center = pos['center']
                closest_id = self._find_closest(center)

                if closest_id is not None:
                    # 기존 얼굴 업데이트
                    self.tracked_faces[closest_id].update({
                        'center': center,
                        'bbox': pos['bbox'],
                        'last_seen': current_time,
                    })
                    updated_ids.add(closest_id)
                else:
                    # 새 얼굴 추가
                    self.tracked_faces[self.next_id] = {
                        'user_id': None,
                        'center': center,
                        'bbox': pos['bbox'],
                        'last_seen': current_time,
                        'last_identified': 0.0,
                    }
                    updated_ids.add(self.next_id)
                    self.next_id += 1

            # 오래된 얼굴 제거 + lost 목록 획득
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
        """타임아웃된 얼굴 제거 + lost 정보 반환

        Returns:
            lost_faces: [{'user_id': str, 'duration': float}, ...]
        """
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

    def identify_faces(self, recognizer, frame, current_time, interval):
        """얼굴 신원 확인
        
        ⚠️ frame은 PROCESSING_WIDTH × PROCESSING_HEIGHT 크기여야 함!
        """
        with self.lock:
            newly_identified = []
            
            for fid, finfo in self.tracked_faces.items():
                if current_time - finfo['last_identified'] < interval:
                    continue
                
                # bbox는 processing 해상도 좌표
                bbox = finfo['bbox']
                x1, y1, x2, y2 = bbox
                
                # ⚠️ frame이 FHD면 문제! processing 해상도 frame 전달 필요
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
