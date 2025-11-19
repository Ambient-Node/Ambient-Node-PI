"""MQTT 클라이언트 관리"""
import json
import paho.mqtt.client as mqtt

class MQTTClient:
    def __init__(self, broker, port):
        self.client = mqtt.Client(client_id="db-service")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        
        # 메시지 핸들러 (외부에서 설정)
        self.message_handler = None
        
        self.client.connect(broker, port, 60)
        self.client.loop_start()
        print(f"[MQTT] Connected: {broker}:{port}")
    
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """MQTT 연결 시 구독"""
        topics = [
            "ambient/user/register",
            "ambient/user/select",
            "ambient/user/update",
            "ambient/command/speed",
            "ambient/command/angle",
            "ambient/command/mode",
            "ambient/ai/face-detected",
            "ambient/ai/face-position",
            "ambient/ai/face-lost",
            "ambient/stats/request",
        ]
        for topic in topics:
            client.subscribe(topic)
        print(f"[MQTT] Subscribed to {len(topics)} topics")
    
    def _on_message(self, client, userdata, msg):
        """MQTT 메시지 수신"""
        try:
            payload = json.loads(msg.payload.decode())
            
            if self.message_handler:
                self.message_handler(msg.topic, payload)
        
        except Exception as e:
            print(f"[MQTT] Message error: {e}")
    
    def publish(self, topic, payload):
        """MQTT 메시지 발행"""
        self.client.publish(topic, json.dumps(payload))
    
    def stop(self):
        """MQTT 연결 종료"""
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT] Disconnected")
