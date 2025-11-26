"""얼굴 인식 모델 관리"""

import os
import cv2
import json
import numpy as np
from datetime import datetime
from tflite_runtime.interpreter import Interpreter

class FaceRecognizer:
    def __init__(self, model_path, face_dir, similarity_threshold=0.3):
        self.face_dir = face_dir
        self.threshold = similarity_threshold
        self.known_embeddings = []
        self.known_user_ids = []
        self.known_usernames = {} 
        
        self.interpreter = Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        self.input_shape = self.input_details[0]['shape'][1:3]
        
        print(f"[FaceRec] Model loaded: {model_path}")
        print(f"[FaceRec] Input shape: {self.input_shape}")
        
        self.load_known_faces()

    def load_known_faces(self):
        """등록된 사용자 임베딩 로드 (user_id 기준)"""
        self.known_embeddings = []
        self.known_user_ids = []
        self.known_usernames = {}
        
        if not os.path.exists(self.face_dir):
            os.makedirs(self.face_dir, exist_ok=True) # 폴더가 없으면 생성하도록 수정
            print(f"[FaceRec] Created directory: {self.face_dir}")
            return
        
        for user_id in os.listdir(self.face_dir):
            user_path = os.path.join(self.face_dir, user_id)
            if not os.path.isdir(user_path):
                continue
            
            # user_id 기준 임베딩 파일
            emb_file = os.path.join(user_path, "embedding.npy")
            metadata_file = os.path.join(user_path, "metadata.json")
            
            if os.path.exists(emb_file):
                try:
                    emb = np.load(emb_file)
                    self.known_embeddings.append(emb)
                    self.known_user_ids.append(user_id)
                    
                    # 메타데이터에서 username 로드
                    if os.path.exists(metadata_file):
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                            self.known_usernames[user_id] = metadata.get('username', user_id)
                    else:
                        self.known_usernames[user_id] = user_id
                        
                except Exception as e:
                    print(f"[FaceRec] Load error {user_id}: {e}")
        
        print(f"[FaceRec] Loaded {len(self.known_user_ids)} users")

    def get_embedding(self, face_img):
        """얼굴 이미지 → 임베딩 (전처리 강화)"""
        if face_img is None or face_img.size == 0:
            raise ValueError("Input image is empty")
        
        lab = cv2.cvtColor(face_img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        l = clahe.apply(l)
        face_img = cv2.merge([l, a, b])
        face_img = cv2.cvtColor(face_img, cv2.COLOR_LAB2BGR)
        
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        face_img = cv2.filter2D(face_img, -1, kernel)
        
        img = cv2.resize(face_img, tuple(self.input_shape))
        img = img.astype(np.float32)
        img = (img - 127.5) / 128.0
        img = np.expand_dims(img, axis=0)
        
        self.interpreter.set_tensor(self.input_details[0]['index'], img)
        self.interpreter.invoke()
        
        return self.interpreter.get_tensor(self.output_details[0]['index'])[0]

    
    def register_user(self, user_id, username, image_path):
        """이미지 파일에서 임베딩을 추출하여 저장"""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return False
            
            # ✅ 등록 시에도 전처리 적용 (get_embedding과 동일)
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            l = clahe.apply(l)
            img = cv2.merge([l, a, b])
            img = cv2.cvtColor(img, cv2.COLOR_LAB2BGR)
            
            embedding = self.get_embedding(img)

            # 3. 폴더 생성 (ble_gateway가 만들었겠지만 확실하게)
            user_dir = os.path.join(self.face_dir, user_id)
            os.makedirs(user_dir, exist_ok=True)

            # 4. embedding.npy 저장
            emb_path = os.path.join(user_dir, "embedding.npy")
            np.save(emb_path, embedding)

            # 5. metadata.json 저장
            meta_path = os.path.join(user_dir, "metadata.json")
            metadata = {
                "user_id": user_id,
                "username": username,
                "created_at": datetime.now().isoformat(),
                "image_path": image_path
            }
            with open(meta_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            print(f"[FaceRec] Saved embedding and metadata for {user_id}")

            # 6. 메모리에 즉시 반영 (재시작 없이 인식 가능하도록)
            self.known_embeddings.append(embedding)
            self.known_user_ids.append(user_id)
            self.known_usernames[user_id] = username

            return True

        except Exception as e:
            print(f"[FaceRec] Registration failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
    def recognize(self, face_crop):
        if not self.known_embeddings:
            return None, 0.0
        
        embedding = self.get_embedding(face_crop)
        sims = [self._cosine_sim(embedding, k) for k in self.known_embeddings]
        best_idx = int(np.argmax(sims))
        best_sim = sims[best_idx]
        
        sorted_sims = sorted(sims, reverse=True)
        if len(sorted_sims) > 1:
            margin = sorted_sims[0] - sorted_sims[1]
            if margin < 0.05:  # 차이 5% 미만이면 불확실
                return None, 0.0
        
        if best_sim > self.threshold:
            return self.known_user_ids[best_idx], best_sim
        
        return None, 0.0

    
    def reload_embeddings(self):
        """새 사용자 등록 시 임베딩 재로드"""
        print("[FaceRec] Reloading embeddings...")
        self.load_known_faces()

    def update_username(self, user_id, new_username):
        """username 변경 (metadata.json + 메모리 갱신)"""
        user_path = os.path.join(self.face_dir, user_id)
        metadata_file = os.path.join(user_path, "metadata.json")
        
        if not os.path.exists(user_path):
            print(f"[FaceRec] User not found: {user_id}")
            return False
        
        try:
            # metadata.json 업데이트
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
            else:
                metadata = {"user_id": user_id}
            
            metadata['username'] = new_username
            metadata['updated_at'] = datetime.now().isoformat()
            
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # 메모리 갱신
            if user_id in self.known_user_ids:
                self.known_usernames[user_id] = new_username
                print(f"[FaceRec] Username updated: {user_id} → {new_username}")
            else:
                print(f"[FaceRec] User {user_id} not in memory (not registered yet?)")
            
            return True
            
        except Exception as e:
            print(f"[FaceRec] Update failed: {e}")
            return False

    @staticmethod
    def _cosine_sim(a, b):
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
