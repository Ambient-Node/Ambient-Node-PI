"""MQTT 통신 관리"""
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
        
        # 콜백
        self.on_user_select = None
        
        self.client.connect(broker, port, 60)
        self.client.loop_start()
        print(f"[MQTT] Connected: {broker}:{port}")
    
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.subscribe("ambient/user/select")  # ← deselect 제거
        print("[MQTT] Subscribed")
    
    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            
            if msg.topic == "ambient/user/select":
                user_list = payload.get('user_list', [])
                session_id = payload.get('session_id')
                
                with self.lock:
                    self.selected_user_ids = [u['user_id'] for u in user_list]
                    self.current_session_id = session_id
                
                print(f"[MQTT] Selected: {self.selected_user_ids}")
                
                if self.on_user_select:
                    self.on_user_select(self.selected_user_ids, session_id)
        
        except Exception as e:
            print(f"[MQTT] Message error: {e}")
    
    def publish_face_detected(self, session_id, user_id, confidence, x, y):
        payload = {
            "event_type": "face_detected",
            "session_id": session_id,
            "user_id": user_id,
            "confidence": round(confidence, 4),
            "x": int(x), "y": int(y),
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/ai/face-detected", json.dumps(payload))
    
    def publish_face_position(self, session_id, user_id, x, y):
        payload = {
            "event_type": "face_position",
            "session_id": session_id,
            "user_id": user_id,
            "x": int(x), "y": int(y),
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/ai/face-position", json.dumps(payload))
    
    def publish_face_lost(self, session_id, user_id, duration):
        payload = {
            "event_type": "face_lost",
            "session_id": session_id,
            "user_id": user_id,
            "duration_seconds": round(duration, 1),
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/ai/face-lost", json.dumps(payload))
    
    def get_current_session(self):
        with self.lock:
            return self.current_session_id, self.selected_user_ids.copy()
