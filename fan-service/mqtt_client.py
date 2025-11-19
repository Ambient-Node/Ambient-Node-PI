# mqtt_client.py
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
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                print(f"[NETWORK] ✅ {host}:{port} is reachable")
                return True
            else:
                print(f"[NETWORK] ⏳ Waiting... ({int(time.time() - start_time)}s)")
                time.sleep(2)
        except socket.gaierror:
            print(f"[NETWORK] ⚠️ DNS resolution failed for {host}")
            time.sleep(3)
        except Exception as e:
            print(f"[NETWORK] ⚠️ Connection check error: {e}")
            time.sleep(2)
    print(f"[NETWORK] ❌ Timeout waiting for {host}:{port}")
    return False

class FanMQTTClient:
    def __init__(self, config, message_handler):
        self.config = config
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.config.MQTT_CLIENT_ID
        )
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        self.message_handler = message_handler  # handlers.handle_mqtt_message 같은 함수

        if not wait_for_network(self.config.MQTT_BROKER, self.config.MQTT_PORT, timeout=30):
            raise ConnectionError(f"Cannot reach MQTT broker at {self.config.MQTT_BROKER}:{self.config.MQTT_PORT}")

        self.connect()

    def connect(self):
        max_retries = 5
        retry_delay = 5
        for attempt in range(max_retries):
            try:
                print(f"[MQTT] 🔄 Connecting to {self.config.MQTT_BROKER}:{self.config.MQTT_PORT} "
                      f"(attempt {attempt + 1}/{max_retries})...")
                self.client.connect(self.config.MQTT_BROKER, self.config.MQTT_PORT, 60)
                self.client.loop_start()

                connected = False
                for _ in range(10):
                    if self.client.is_connected():
                        connected = True
                        break
                    time.sleep(1)

                if connected:
                    print("[MQTT] ✅ Connected successfully")
                    return
                else:
                    print("[MQTT] ⚠️ Connection timeout")
                    self.client.loop_stop()
            except Exception as e:
                print(f"[MQTT] ⚠️ Connection failed: {e}")
                if attempt < max_retries - 1:
                    print(f"[MQTT] 🔄 Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)

        raise ConnectionError("Failed to connect to MQTT broker")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            print("[MQTT] 📡 Connected")
            topics = [
                "ambient/command/#",          # 팬 제어 명령 (speed/angle/mode 등)
                "ambient/ai/face-detected",   # AI에서 얼굴 각도 줄 수도 있으니 유지
                "ambient/user/register",      # 필요 시 사용자 등록 관련 처리
            ]
            for t in topics:
                result = client.subscribe(t)
                print(f"[MQTT] 📬 Subscribed to {t} (result: {result})")
        else:
            print(f"[MQTT] ❌ Connection failed: {reason_code}")

    def on_disconnect(self, client, userdata, rc, properties=None):
        print(f"[MQTT] ⚠️ Disconnected (rc={rc})")
        # 자동 재연결 로직을 넣고 싶으면 여기서 self.connect() 호출 고려

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            # 중앙 handler에 토픽+payload 전달
            self.message_handler(msg.topic, payload)
        except Exception as e:
            print(f"[MQTT] ❌ Message error: {e}")

    def publish_status(self, topic_suffix, data: dict):
        topic = f"ambient/fan001/status/{topic_suffix}"
        payload = {
            **data,
            "timestamp": datetime.now().isoformat(),
        }
        self.client.publish(topic, json.dumps(payload))
