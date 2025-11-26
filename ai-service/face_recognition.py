"""얼굴 인식 모델 관리 (FaceNet 전용 전처리 복구)"""
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
        
        print(f"[FaceRec] Model: {model_path} | Shape: {self.input_shape}")
        if not os.path.exists(self.face_dir):
            os.makedirs(self.face_dir, exist_ok=True)

    def load_selected_users(self, user_ids):
        """기존 코드 유지"""
        self.known_embeddings = []
        self.known_user_ids = []
        self.known_usernames = {}
        if not user_ids: return
        
        for user_id in user_ids:
            user_path = os.path.join(self.face_dir, user_id)
            emb_file = os.path.join(user_path, "embedding.npy")
            metadata_file = os.path.join(user_path, "metadata.json")
            
            if os.path.exists(emb_file):
                try:
                    emb = np.load(emb_file)
                    self.known_embeddings.append(emb)
                    self.known_user_ids.append(user_id)
                    if os.path.exists(metadata_file):
                        with open(metadata_file, 'r') as f:
                            data = json.load(f)
                            self.known_usernames[user_id] = data.get('username', user_id)
                    else:
                        self.known_usernames[user_id] = user_id
                except Exception:
                    pass

    def get_embedding(self, face_img):
        """✅ FaceNet 전용 전처리 (CLAHE + Kernel)"""
        if face_img is None or face_img.size == 0:
            raise ValueError("Input image is empty")
        
        # 1. LAB 색공간 변환 후 CLAHE 적용 (조명 보정)
        lab = cv2.cvtColor(face_img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        l = clahe.apply(l)
        face_img = cv2.merge([l, a, b])
        face_img = cv2.cvtColor(face_img, cv2.COLOR_LAB2BGR)
        
        # 2. 커널 필터 적용 (선명화)
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        face_img = cv2.filter2D(face_img, -1, kernel)
        
        # 3. 모델 입력 처리
        img = cv2.resize(face_img, tuple(self.input_shape))
        img = img.astype(np.float32)
        img = (img - 127.5) / 128.0
        img = np.expand_dims(img, axis=0)
        
        self.interpreter.set_tensor(self.input_details[0]['index'], img)
        self.interpreter.invoke()
        return self.interpreter.get_tensor(self.output_details[0]['index'])[0]

    def register_user(self, user_id, username, image_path):
        try:
            img = cv2.imread(image_path)
            if img is None: return False
            
            # 저장 시에도 동일한 전처리 적용
            embedding = self.get_embedding(img)
            
            user_dir = os.path.join(self.face_dir, user_id)
            os.makedirs(user_dir, exist_ok=True)
            np.save(os.path.join(user_dir, "embedding.npy"), embedding)
            
            with open(os.path.join(user_dir, "metadata.json"), 'w') as f:
                json.dump({
                    "user_id": user_id,
                    "username": username,
                    "created_at": datetime.now().isoformat(),
                    "image_path": image_path
                }, f, indent=2)
            return True
        except Exception as e:
            print(f"Reg Error: {e}")
            return False

    def recognize(self, face_crop):
        if not self.known_embeddings:
            return None, 0.0
        
        embedding = self.get_embedding(face_crop)
        sims = [self._cosine_sim(embedding, k) for k in self.known_embeddings]
        best_idx = int(np.argmax(sims))
        best_sim = sims[best_idx]
        
        if best_sim > self.threshold:
            return self.known_user_ids[best_idx], best_sim
        return None, 0.0

    @staticmethod
    def _cosine_sim(a, b):
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0: return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))