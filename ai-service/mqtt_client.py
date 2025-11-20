# mqtt_client.py
import json
import threading
from datetime import datetime
import paho.mqtt.client as mqtt

class MQTTClient:
    def __init__(self, broker, port):
        self.client = mqtt.Client(client_id="ai-service")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        
        self.current_session_id = None
        self.selected_user_ids = []
        self.lock = threading.Lock()
        
        # 콜백 (외부에서 설정)
        self.on_session_update = None
        self.on_user_register = None  # ← 초기화 추가!
        
        self.client.connect(broker, port, 60)
        self.client.loop_start()
        print(f"[MQTT] Connected: {broker}:{port}")
    
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.subscribe([
            ("ambient/session/active", 0),
            ("ambient/user/register", 0),
        ])
        print("[MQTT] Subscribed to session/active, user/register")
    
    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            
            if msg.topic == "ambient/session/active":
                session_id = payload.get('session_id')
                user_list = payload.get('user_list', [])
                
                with self.lock:
                    self.current_session_id = session_id
                    self.selected_user_ids = [u['user_id'] for u in user_list]
                
                print(f"[MQTT] Session updated: {session_id}")
                print(f"[MQTT] Tracking: {self.selected_user_ids}")
                
                if self.on_session_update:
                    self.on_session_update(session_id, self.selected_user_ids)
            
            elif msg.topic == "ambient/user/register":
                # 새 사용자 등록 시 임베딩 재로드
                user_id = payload.get('user_id')
                username = payload.get('username')
                print(f"[MQTT] New user registered: {username} ({user_id})")
                
                if self.on_user_register:
                    self.on_user_register(payload)  # ← 콜백 실행
                else:
                    print("[MQTT] ⚠️ on_user_register callback not set")
        
        except Exception as e:
            print(f"[MQTT] Message error: {e}")
    
    def publish_face_detected(self, user_id, confidence, x, y):
        """얼굴 인식 이벤트"""
        with self.lock:
            session_id = self.current_session_id
        
        if not session_id:
            print("[MQTT] No active session, skipping face_detected")
            return
        
        payload = {
            "event_type": "face_detected",
            "session_id": session_id,
            "user_id": user_id,
            "confidence": round(confidence, 4),
            "x": int(x),
            "y": int(y),
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/ai/face-detected", json.dumps(payload))
    
    def publish_face_position(self, user_id, x, y):
        """얼굴 좌표 추적"""
        with self.lock:
            session_id = self.current_session_id
        
        if not session_id:
            return
        
        payload = {
            "event_type": "face_position",
            "session_id": session_id,
            "user_id": user_id,
            "x": int(x),
            "y": int(y),
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/ai/face-position", json.dumps(payload))
    
    def publish_face_lost(self, user_id, duration):
        """얼굴 추적 종료"""
        with self.lock:
            session_id = self.current_session_id
        
        if not session_id:
            return
        
        payload = {
            "event_type": "face_lost",
            "session_id": session_id,
            "user_id": user_id,
            "duration_seconds": round(duration, 1),
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/ai/face-lost", json.dumps(payload))
    
    def get_current_session(self):
        """현재 세션 정보 (스레드 안전)"""
        with self.lock:
            return self.current_session_id, self.selected_user_ids.copy()
    
    def stop(self):
        """MQTT 연결 종료"""
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT] Disconnected")
