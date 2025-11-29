# ai-service/mqtt_client.py

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
        
        # 콜백 초기화
        self.on_session_update = None
        self.on_user_register = None
        self.on_user_update = None
        self.on_mode_change = None 
        
        self.client.connect(broker, port, 60)
        self.client.loop_start()
        print(f"[MQTT] Connected: {broker}:{port}")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code != 0: return
        topics = [
            "ambient/user/register",
            "ambient/user/update",   
            "ambient/user/select",
            "ambient/session/active",
            "ambient/command/mode"
        ]
        for topic in topics: client.subscribe(topic)
        self._request_active_session()

    def _request_active_session(self):
        payload = {"requester": "ai-service", "timestamp": datetime.now().isoformat()}
        self.client.publish("ambient/session/request", json.dumps(payload), qos=1)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            
            # [핵심 수정 부분] 모드 변경 명령 처리
            if msg.topic == "ambient/command/mode":
                cmd_type = payload.get("type", "motor")
                
                # 🛑 중요: type이 'motor'가 아니면(예: wind) AI는 이 메시지를 무시해야 함.
                # 그렇지 않으면 current_mode가 'natural_wind' 등으로 바뀌어 트래킹이 멈춤.
                if cmd_type != "motor":
                    # print(f"[AI] Ignoring non-motor command: {cmd_type}")
                    return 

                # type이 motor일 때만 상태 변경 진행
                if self.on_mode_change:
                    self.on_mode_change(payload.get('mode'))

            elif msg.topic == "ambient/session/active":
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
                if self.on_user_register: self.on_user_register(payload)
            
            elif msg.topic == "ambient/user/update":
                if self.on_user_update: self.on_user_update(payload)
                    
        except Exception as e:
            print(f"[MQTT] Error: {e}")

    # ... (이하 get_current_session, publish 함수들은 기존 유지) ...
    def get_current_session(self):
        with self.lock: return self.current_session_id, self.selected_user_ids.copy()

    def publish_face_detected(self, user_id, confidence):
        payload = {"user_id": user_id, "confidence": float(confidence), "timestamp": datetime.now().isoformat()}
        self.client.publish("ambient/ai/face-detected", json.dumps(payload), qos=1)

    def publish_face_position(self, user_id, x, y):
        payload = {"user_id": user_id, "x": x, "y": y, "timestamp": datetime.now().isoformat()}
        self.client.publish("ambient/ai/face-position", json.dumps(payload), qos=0)

    def publish_face_lost(self, user_id, duration):
        payload = {"user_id": user_id, "duration_seconds": duration, "timestamp": datetime.now().isoformat()}
        self.client.publish("ambient/ai/face-lost", json.dumps(payload), qos=1)

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()