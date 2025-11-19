# mqtt_client.py
class MQTTClient:
    def __init__(self, broker, port):
        self.client = mqtt.Client(client_id="ai-service")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        
        self.current_session_id = None
        self.selected_user_ids = []
        self.lock = threading.Lock()
        
        # 콜백
        self.on_session_update = None
        
        self.client.connect(broker, port, 60)
        self.client.loop_start()
        print(f"[MQTT] Connected: {broker}:{port}")
    
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        # ambient/session/active 구독 (DB Service가 발행)
        client.subscribe("ambient/session/active")
        print("[MQTT] Subscribed to session/active")
    
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
            "session_id": session_id,  # ← DB Service가 보낸 session_id 사용
            "user_id": user_id,
            "confidence": round(confidence, 4),
            "x": int(x), "y": int(y),
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
            "x": int(x), "y": int(y),
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/ai/face-position", json.dumps(payload))
    
    def get_current_session(self):
        """현재 세션 정보 (스레드 안전)"""
        with self.lock:
            return self.current_session_id, self.selected_user_ids.copy()
