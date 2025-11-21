# mqtt_client.py
import json
import socket
import time
import paho.mqtt.client as mqtt
from datetime import datetime


def wait_for_network(host, port, timeout=60):
    """네트워크 연결 대기"""
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
        self.message_handler = message_handler  # handlers.handle_mqtt_message
        
        # ✅ paho-mqtt 1.x: Client() 인자에 client_id만
        self.client = mqtt.Client(client_id=self.config.MQTT_CLIENT_ID)
        
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        
        # 네트워크 대기
        if not wait_for_network(self.config.MQTT_BROKER, self.config.MQTT_PORT, timeout=30):
            raise ConnectionError(f"Cannot reach MQTT broker at {self.config.MQTT_BROKER}:{self.config.MQTT_PORT}")
        
        # MQTT 연결 시도
        self.connect()

    def connect(self):
        """MQTT 브로커 연결 (재시도 로직 포함)"""
        max_retries = 5
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                print(f"[MQTT] 🔄 Connecting to {self.config.MQTT_BROKER}:{self.config.MQTT_PORT} "
                      f"(attempt {attempt + 1}/{max_retries})...")
                
                self.client.connect(self.config.MQTT_BROKER, self.config.MQTT_PORT, 60)
                self.client.loop_start()
                
                # 연결 확인 (최대 10초 대기)
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
        
        raise ConnectionError("Failed to connect to MQTT broker after all retries")

    # ✅ paho-mqtt 1.x: 4개 인자 (rc)
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("[MQTT] 📡 Connected to broker")
            
            # 구독 토픽
            topics = [
                "ambient/command/#",          # 팬 제어 명령 (speed/angle/mode 등)
                "ambient/ai/face-detected",   # AI 얼굴 감지
                "ambient/user/register",      # 사용자 등록
            ]
            
            for topic in topics:
                result = client.subscribe(topic)
                print(f"[MQTT] 📬 Subscribed to {topic} (result: {result})")
        else:
            print(f"[MQTT] ❌ Connection failed with code: {rc}")
            # rc 코드 의미:
            # 0: 성공
            # 1: 프로토콜 버전 오류
            # 2: 클라이언트 ID 거부
            # 3: 서버 사용 불가
            # 4: 사용자명/패스워드 오류
            # 5: 인증 실패

    # ✅ paho-mqtt 1.x: 3개 인자 (rc)
    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            print(f"[MQTT] ⚠️ Unexpected disconnect (rc={rc})")
            # 필요시 재연결 로직
            # self.connect()
        else:
            print("[MQTT] 🔌 Disconnected gracefully")

    # ✅ on_message는 1.x/2.x 동일
    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            print(f"[MQTT] 📥 Received on {msg.topic}")
            
            # 중앙 handler에 토픽+payload 전달
            self.message_handler(msg.topic, payload)
        
        except json.JSONDecodeError as e:
            print(f"[MQTT] ❌ JSON decode error: {e}")
        except Exception as e:
            print(f"[MQTT] ❌ Message handling error: {e}")

    def publish_status(self, topic_suffix, data: dict):
        """팬 상태 발행"""
        topic = f"ambient/fan/status/{topic_suffix}"
        payload = {
            **data,
            "timestamp": datetime.now().isoformat(),
        }
        
        try:
            result = self.client.publish(topic, json.dumps(payload), qos=1)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"[MQTT] 📤 Published to {topic}")
            else:
                print(f"[MQTT] ⚠️ Publish failed: {result.rc}")
        except Exception as e:
            print(f"[MQTT] ❌ Publish error: {e}")

    def publish(self, topic, payload: dict, qos=1):
        """범용 메시지 발행"""
        try:
            result = self.client.publish(topic, json.dumps(payload), qos=qos)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"[MQTT] 📤 Published to {topic}")
            else:
                print(f"[MQTT] ⚠️ Publish failed: {result.rc}")
        except Exception as e:
            print(f"[MQTT] ❌ Publish error: {e}")

    def disconnect(self):
        """MQTT 연결 종료"""
        try:
            self.client.loop_stop()
            self.client.disconnect()
            print("[MQTT] 🔌 Disconnected")
        except Exception as e:
            print(f"[MQTT] ❌ Disconnect error: {e}")
