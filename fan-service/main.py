# main.py
#!/usr/bin/env python3
import signal
import time
import sys
from config import Config
from hardware import FanHardware
from mqtt_client import FanMQTTClient
from handlers import FanHandlers

_running = True
service = None

def signal_handler(sig, frame):
    global _running
    print("\n[FAN] 🛑 Shutting down...")
    _running = False

def main():
    global service
    print("=" * 60)
    print("Fan Service Starting...")
    print("=" * 60)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    cfg = Config()
    hw = FanHardware(cfg)
    handlers = FanHandlers(hw, None)  # mqtt는 나중에 주입

    # MQTT 클라이언트 생성 시 handlers.handle_mqtt_message를 넘겨줌
    mqtt_client = FanMQTTClient(cfg, handlers.handle_mqtt_message)
    # 순환 참조 끊기 위해 여기서 주입
    handlers.mqtt = mqtt_client

    print("[INFO] 🚀 Fan Service running... (Press Ctrl+C to stop)")
    try:
        while _running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] 👋 Interrupted by user")
    finally:
        hw.cleanup()
        mqtt_client.client.loop_stop()
        mqtt_client.client.disconnect()
        print("[INFO] 🏁 Fan Service stopped")

if __name__ == "__main__":
    main()
