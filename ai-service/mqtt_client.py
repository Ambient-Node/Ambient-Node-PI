# mqtt_client.py
import json
import threading
from datetime import datetime
import paho.mqtt.client as mqtt


class MQTTClient:
    def __init__(self, broker, port):
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="ai-service"
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        
        self.current_session_id = None
        self.selected_user_ids = []
        self.lock = threading.Lock()
        
        # 콜백 (외부에서 설정)
        self.on_session_update = None
        self.on_user_register = None
        self.on_user_update = None
        
        self.client.connect(broker, port, 60)
        self.client.loop_start()
        print(f"[MQTT] Connected: {broker}:{port}")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT 연결 성공 시 호출"""
        if reason_code != 0:
            print(f"[MQTT] Connection failed: {reason_code}")
            return
        
        topics = [
            "ambient/user/register",
            "ambient/user/update",   
            "ambient/user/select",
            "ambient/session/active",
            "ambient/command/mode"
        ]
        
        for topic in topics:
            client.subscribe(topic)
        
        print(f"[MQTT] Subscribed to {len(topics)} topics")
        self._request_active_session()

    def _request_active_session(self):
        """DB에 현재 활성 세션 요청"""
        payload = {
            "requester": "ai-service",
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/session/request", json.dumps(payload), qos=1)
        print("[MQTT] 📤 Session request sent to DB")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            
            if msg.topic == "ambient/session/active":
                session_id = payload.get('session_id')
                user_list = payload.get('user_list', [])
                
                with self.lock:
                    self.current_session_id = session_id
                    self.selected_user_ids = [u['user_id'] for u in user_list]
                
                if self.on_session_update:
                    self.on_session_update(session_id, self.selected_user_ids)
            
            elif msg.topic == "ambient/user/select":
                session_id = payload.get('session_id')
                user_list = payload.get('user_list', [])
                
                with self.lock:
                    self.current_session_id = session_id
                    self.selected_user_ids = [u['user_id'] for u in user_list]
                
                if self.on_session_update:
                    self.on_session_update(session_id, self.selected_user_ids)
            
            elif msg.topic == "ambient/user/register":
                user_id = payload.get('user_id')
                username = payload.get('username')
                print(f"[MQTT] New user registered: {username} ({user_id})")
                
                if self.on_user_register:
                    self.on_user_register(payload)
                else:
                    print("[MQTT] on_user_register callback not set")
            
            elif msg.topic == "ambient/user/update":
                user_id = payload.get('user_id')
                username = payload.get('username')
                print(f"[MQTT] User updated: {user_id} → {username}")
                
                if self.on_user_update:
                    self.on_user_update(payload)
                else:
                    print("[MQTT] on_user_update callback not set")
            
            elif msg.topic == "ambient/command/mode":
                mode = payload.get('mode')
                print(f"[MQTT] Mode changed: {mode}")
                if self.on_mode_change:
                    self.on_mode_change(mode)
                    
        except Exception as e:
            print(f"[MQTT] Error: {e}")

    def get_current_session(self):
        with self.lock:
            return self.current_session_id, self.selected_user_ids.copy()

    def publish_face_detected(self, user_id, confidence):
        """얼굴 인식 완료 → DB 저장용"""
        payload = {
            "user_id": user_id,
            "confidence": float(confidence),
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/ai/face-detected", json.dumps(payload), qos=1)
        print(f"[MQTT] face-detected: {user_id} (conf={confidence:.2f})")

    def publish_face_position(self, user_id, x, y):
        """실시간 얼굴 좌표 → Fan Service"""
        payload = {
            "user_id": user_id,
            "x": x,
            "y": y,
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/ai/face-position", json.dumps(payload), qos=0)

    def publish_face_lost(self, user_id, duration):
        """얼굴 추적 종료 → DB 저장용"""
        payload = {
            "user_id": user_id,
            "duration_seconds": duration,
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish("ambient/ai/face-lost", json.dumps(payload), qos=1)
        print(f"[MQTT] 📤 face-lost: {user_id} (duration={duration:.1f}s)")

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
