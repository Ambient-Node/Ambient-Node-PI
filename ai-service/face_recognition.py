"""얼굴 인식 모델 관리 (기준값 적용 확인)"""
import os
import cv2
import json
import numpy as np
from datetime import datetime
from tflite_runtime.interpreter import Interpreter

class FaceRecognizer:
    def __init__(self, model_path, face_dir, similarity_threshold=0.6): # 기본값도 0.6으로 명시
        self.face_dir = face_dir
        self.threshold = similarity_threshold # Config에서 받아온 0.6이 들어감
        self.known_embeddings = []
        self.known_user_ids = []
        self.known_usernames = {}
        
        self.interpreter = Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        self.input_shape = self.input_details[0]['shape'][1:3]
        
        print(f"[FaceRec] Model: {model_path} | Threshold: {self.threshold}")
        if not os.path.exists(self.face_dir):
            os.makedirs(self.face_dir, exist_ok=True)

    def load_selected_users(self, user_ids):
        """스레드 안전 로딩"""
        temp_embeddings = []
        temp_user_ids = []
        temp_usernames = {}
        
        if not user_ids:
            self.known_embeddings = []
            self.known_user_ids = []
            self.known_usernames = {}
            return
        
        for user_id in user_ids:
            user_path = os.path.join(self.face_dir, user_id)
            emb_file = os.path.join(user_path, "embedding.npy")
            metadata_file = os.path.join(user_path, "metadata.json")
            
            if os.path.exists(emb_file):
                try:
                    emb = np.load(emb_file)
                    temp_embeddings.append(emb)
                    temp_user_ids.append(user_id)
                    
                    if os.path.exists(metadata_file):
                        with open(metadata_file, 'r') as f:
                            data = json.load(f)
                            temp_usernames[user_id] = data.get('username', user_id)
                    else:
                        temp_usernames[user_id] = user_id
                except Exception:
                    pass

        self.known_embeddings = temp_embeddings
        self.known_user_ids = temp_user_ids
        self.known_usernames = temp_usernames

    def get_embedding(self, face_img):
        if face_img is None or face_img.size == 0:
            return None
        img = cv2.resize(face_img, tuple(self.input_shape))
        img = img.astype(np.float32)
        img = (img - 127.5) / 128.0
        img = np.expand_dims(img, axis=0)
        
        self.interpreter.set_tensor(self.input_details[0]['index'], img)
        self.interpreter.invoke()
        return self.interpreter.get_tensor(self.output_details[0]['index'])[0]

    def recognize(self, face_crop):
        if not self.known_embeddings:
            return None, 0.0
        
        embedding = self.get_embedding(face_crop)
        if embedding is None: return None, 0.0

        sims = [self._cosine_sim(embedding, k) for k in self.known_embeddings]
        
        if not sims: return None, 0.0

        best_idx = int(np.argmax(sims))
        best_sim = sims[best_idx]
        
        if best_sim > self.threshold:
            return self.known_user_ids[best_idx], best_sim
        
        return None, 0.0

    @staticmethod
    def _cosine_sim(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def register_user(self, user_id, username, image_path):
        try:
            img = cv2.imread(image_path)
            if img is None: return False
            embedding = self.get_embedding(img)
            if embedding is None: return False
            
            user_dir = os.path.join(self.face_dir, user_id)
            os.makedirs(user_dir, exist_ok=True)
            np.save(os.path.join(user_dir, "embedding.npy"), embedding)
            
            with open(os.path.join(user_dir, "metadata.json"), 'w') as f:
                json.dump({"user_id": user_id, "username": username}, f)
            return True
        except Exception: return False