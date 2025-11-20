"""얼굴 인식 모델 관리"""
import os
import cv2
import numpy as np
from tflite_runtime.interpreter import Interpreter

class FaceRecognizer:
    def __init__(self, model_path, face_dir, similarity_threshold=0.3):
        self.face_dir = face_dir
        self.threshold = similarity_threshold
        self.known_embeddings = []
        self.known_user_ids = []
        
        self.interpreter = Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        self.input_shape = self.input_details[0]['shape'][1:3]
        
        print(f"[FaceRec] Model loaded: {model_path}")
        print(f"[FaceRec] Input shape: {self.input_shape}")
        self.load_known_faces()
    
    def load_known_faces(self):
        """등록된 사용자 임베딩 로드 (재로드 가능)"""
        self.known_embeddings = []
        self.known_user_ids = []
        
        if not os.path.exists(self.face_dir):
            print(f"[FaceRec] Directory not found: {self.face_dir}")
            return
        
        for user_id in os.listdir(self.face_dir):
            user_path = os.path.join(self.face_dir, user_id)
            if not os.path.isdir(user_path):
                continue
            
            emb_file = os.path.join(user_path, f"{user_id}_embedding.npy")
            if os.path.exists(emb_file):
                try:
                    emb = np.load(emb_file)
                    self.known_embeddings.append(emb)
                    self.known_user_ids.append(user_id)
                except Exception as e:
                    print(f"[FaceRec] Load error {user_id}: {e}")
        
        print(f"[FaceRec] Loaded {len(self.known_user_ids)} users")

    def get_embedding(self, face_img):
        """얼굴 이미지 → 임베딩"""
        img = cv2.resize(face_img, tuple(self.input_shape))
        img = img.astype(np.float32)
        img = (img - 127.5) / 128.0
        img = np.expand_dims(img, axis=0)
        
        self.interpreter.set_tensor(self.input_details[0]['index'], img)
        self.interpreter.invoke()
        return self.interpreter.get_tensor(self.output_details[0]['index'])[0]
    
    def recognize(self, face_crop):
        """얼굴 인식 (user_id, confidence)"""
        if not self.known_embeddings:
            return None, 0.0
        
        embedding = self.get_embedding(face_crop)
        sims = [self._cosine_sim(embedding, k) for k in self.known_embeddings]
        best_idx = int(np.argmax(sims))
        best_sim = sims[best_idx]
        
        if best_sim > self.threshold:
            return self.known_user_ids[best_idx], best_sim
        return None, 0.0
    
    def reload_embeddings(self):
        """새 사용자 등록 시 임베딩 재로드"""
        print("[FaceRec] Reloading embeddings...")
        self.load_known_faces()
    
    @staticmethod
    def _cosine_sim(a, b):
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
