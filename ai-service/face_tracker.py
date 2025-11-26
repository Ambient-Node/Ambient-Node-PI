"""얼굴 추적 관리 (1:1 매칭 강화)"""

import threading

class FaceTracker:
    def __init__(self, max_distance=300, lost_timeout=8.0, enable_display=True):
        self.tracked_faces = {}
        self.next_id = 0
        self.max_distance = max_distance
        self.lost_timeout = lost_timeout
        self.lock = threading.Lock()
            
    def reset(self):
        with self.lock:
            self.tracked_faces.clear()
            self.next_id = 0
            print("[Tracker] Memory cleared (Reset)")

    def update(self, detected_positions, current_time):
        """감지된 얼굴로 추적 업데이트 (Greedy 1:1 Matching)"""
        with self.lock:
            updated_ids = set()
            
            # 1. 모든 감지된 박스와 기존 트래커 간의 거리 계산
            # 형식: (거리, track_id, detection_index)
            matches = []
            
            for det_idx, pos in enumerate(detected_positions):
                center = pos['center']
                for fid, finfo in self.tracked_faces.items():
                    old_center = finfo['center']
                    dist = ((center[0] - old_center[0]) ** 2 +
                           (center[1] - old_center[1]) ** 2) ** 0.5
                    
                    if dist < self.max_distance:
                        matches.append((dist, fid, det_idx))
            
            # 2. 거리순으로 정렬 (가장 가까운 것부터 우선 매칭)
            matches.sort(key=lambda x: x[0])
            
            used_track_ids = set()
            used_det_indices = set()
            
            # 3. 매칭 실행 (이미 매칭된 ID나 박스는 건너뜀)
            for dist, fid, det_idx in matches:
                if fid in used_track_ids or det_idx in used_det_indices:
                    continue
                
                # 매칭 성공 -> 정보 업데이트
                self.tracked_faces[fid].update({
                    'center': detected_positions[det_idx]['center'],
                    'bbox': detected_positions[det_idx]['bbox'],
                    'last_seen': current_time,
                })
                updated_ids.add(fid)
                used_track_ids.add(fid)
                used_det_indices.add(det_idx)
            
            # 4. 매칭되지 않은(남은) 박스는 새로운 얼굴로 등록
            for det_idx, pos in enumerate(detected_positions):
                if det_idx not in used_det_indices:
                    # [추가 안전장치] 혹시나 기존 트래커와 너무 가까우면(NMS 뚫림 대비) 생성 안 함
                    is_too_close = False
                    for fid, finfo in self.tracked_faces.items():
                        old_center = finfo['center']
                        dist = ((pos['center'][0] - old_center[0]) ** 2 +
                                (pos['center'][1] - old_center[1]) ** 2) ** 0.5
                        if dist < self.max_distance * 0.5: # 50% 이내 거리면 무시
                            is_too_close = True
                            break
                    
                    if not is_too_close:
                        self.tracked_faces[self.next_id] = {
                            'user_id': None,
                            'center': pos['center'],
                            'bbox': pos['bbox'],
                            'last_seen': current_time,
                            'last_identified': 0.0,
                        }
                        updated_ids.add(self.next_id)
                        self.next_id += 1
            
            # 5. 타임아웃 처리
            lost_faces = self._remove_expired(current_time, timeout=self.lost_timeout)
            return updated_ids, lost_faces

    def _remove_expired(self, current_time, timeout):
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
        """얼굴 신원 확인"""
        with self.lock:
            newly_identified = []
            
            # 한 프레임 내에서 같은 User ID 중복 방지용
            identified_users_this_frame = set()

            for fid, finfo in self.tracked_faces.items():
                if not force_all and current_time - finfo['last_identified'] < interval:
                    continue
                
                bbox = finfo['bbox']
                x1, y1, x2, y2 = bbox
                
                # 이미지 경계 체크
                h, w = frame.shape[:2]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                
                face_crop = frame[y1:y2, x1:x2]
                if face_crop.size == 0:
                    continue
                
                user_id, confidence = recognizer.recognize(face_crop)
                
                if user_id:
                    # 이번 프레임에 이미 이 사람이 인식되었다면, 중복 처리 (Confidence 비교 생략하고 일단 통과)
                    if user_id in identified_users_this_frame:
                        continue 

                    # 연속 인식 시 신뢰도 보정
                    prev_user = finfo.get('user_id')
                    if prev_user == user_id:
                        confidence = min(0.95, confidence + 0.05)
                    
                    finfo['user_id'] = user_id
                    finfo['confidence'] = confidence
                    finfo['last_identified'] = current_time
                    if 'first_seen' not in finfo:
                        finfo['first_seen'] = current_time
                    
                    newly_identified.append((fid, user_id, confidence))
                    identified_users_this_frame.add(user_id)
            
            return newly_identified

    def get_selected_faces(self, selected_user_ids):
        with self.lock:
            return [
                {**finfo, 'face_id': fid}
                for fid, finfo in self.tracked_faces.items()
                if finfo.get('user_id') in selected_user_ids
            ]