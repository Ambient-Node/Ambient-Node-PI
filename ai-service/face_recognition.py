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

        if not os.path.exists(self.face_dir):
            os.makedirs(self.face_dir, exist_ok=True)
            print(f"[FaceRec] Created directory: {self.face_dir}")

    def load_selected_users(self, user_ids):
        """세션에서 선택된 유저 임베딩만 메모리로 로드"""
        self.known_embeddings = []
        self.known_user_ids = []
        self.known_usernames = {}

        if not user_ids:
            print("[FaceRec] No users selected")
            return

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
                            metadata = json.load(f)
                            self.known_usernames[user_id] = metadata.get('username', user_id)
                    else:
                        self.known_usernames[user_id] = user_id
                except Exception as e:
                    print(f"[FaceRec] Load error {user_id}: {e}")
        print(f"[FaceRec] Loaded selected users: {self.known_user_ids}")

    def get_embedding(self, face_img):
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
        try:
            img = cv2.imread(image_path)
            if img is None:
                return False
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            l = clahe.apply(l)
            img = cv2.merge([l, a, b])
            img = cv2.cvtColor(img, cv2.COLOR_LAB2BGR)
            embedding = self.get_embedding(img)
            user_dir = os.path.join(self.face_dir, user_id)
            os.makedirs(user_dir, exist_ok=True)
            emb_path = os.path.join(user_dir, "embedding.npy")
            np.save(emb_path, embedding)
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
            # 메모리 추가하지 않음!
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
            if margin < 0.05:
                return None, 0.0
        if best_sim > self.threshold:
            return self.known_user_ids[best_idx], best_sim
        return None, 0.0

    @staticmethod
    def _cosine_sim(a, b):
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
