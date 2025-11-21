import json
import socket
import time
import paho.mqtt.client as mqtt
from datetime import datetime

def wait_for_network(host, port, timeout=60):
    print(f"[NETWORK] Waiting for {host}:{port}...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            if sock.connect_ex((host, port)) == 0:
                print(f"[NETWORK] ✅ {host}:{port} is reachable")
                sock.close()
                return True
            sock.close()
            time.sleep(2)
        except Exception as e:
            print(f"[NETWORK] ⚠️ {e}")
            time.sleep(2)
    return False

class FanMQTTClient:
    def __init__(self, config, message_handler):
        self.config = config
        self.message_handler = message_handler
        
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.config.MQTT_CLIENT_ID
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        if not wait_for_network(self.config.MQTT_BROKER, self.config.MQTT_PORT, timeout=30):
            raise ConnectionError("Cannot reach MQTT broker")
        
        self.connect()
    
    def connect(self):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                self.client.connect(self.config.MQTT_BROKER, self.config.MQTT_PORT, 60)
                self.client.loop_start()
                for _ in range(10):
                    if self.client.is_connected():
                        print("[MQTT] ✅ Connected")
                        return
                    time.sleep(1)
            except Exception as e:
                print(f"[MQTT] ⚠️ {e}, attempt {attempt + 1}")
                time.sleep(5)
        raise ConnectionError("Failed to connect to MQTT broker")
    
    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            topics = [
                "ambient/command/#",
                "ambient/ai/face-position",
                "ambient/ai/face-lost"
            ]
            for t in topics:
                client.subscribe(t)
                print(f"[MQTT] 📬 Subscribed: {t}")
        else:
            print(f"[MQTT] ❌ Connection failed: {reason_code}")
    
    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            self.message_handler(msg.topic, payload)
        except Exception as e:
            print(f"[MQTT] ❌ Message error: {e}")
    
    def publish_status(self, speed_level: int):
        topic = "ambient/fan/status"
        payload = {
            "speed": speed_level,
            "timestamp": datetime.now().isoformat()
        }
        try:
            self.client.publish(topic, json.dumps(payload), qos=1)
            print(f"[MQTT] 📤 Status published: speed={speed_level}")
        except Exception as e:
            print(f"[MQTT] ❌ Publish error: {e}")
    
    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
