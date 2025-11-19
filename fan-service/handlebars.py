# handlers.py
from datetime import datetime

class FanHandlers:
    def __init__(self, hardware, mqtt_client):
        self.hw = hardware
        self.mqtt = mqtt_client

    # 중앙 진입점: mqtt_client가 여기로 위임
    def handle_mqtt_message(self, topic: str, payload: dict):
        print(f"[MQTT] 📥 {topic}: {payload}")

        if topic == "ambient/ai/face-detected":
            self.handle_face_detected(payload)
        elif topic.startswith("ambient/command/"):
            cmd = topic.split("/")[-1]
            self.handle_command(cmd, payload)
        elif topic == "ambient/user/register":
            self.handle_user_register(payload)
        else:
            print(f"[MQTT] ⚠️ Unhandled topic: {topic}")

    def handle_command(self, cmd: str, payload: dict):
        print(f"[CMD] 🎯 Command: {cmd}")

        if cmd == "speed":
            # 새 설계: speed_change로 통일했다면 여기서 매핑
            # payload: { "speed": 0~5 } 또는 { "level": 0~100 }
            level = payload.get("level")
            if level is None and "speed" in payload:
                # 0~5 → 0~100 변환 예시
                level = int(payload["speed"]) * 20
            self.set_fan_speed(level or 0)

        elif cmd == "angle":
            direction = payload.get("direction")
            self.handle_angle(direction)

        elif cmd == "mode":
            # AI/수동 모드 등 필요 시 처리
            mode = payload.get("mode")
            print(f"[CMD] Mode change (fan side): {mode}")
            # 실제 회전 패턴 등은 나중에 확장

    def set_fan_speed(self, level: int):
        power, speed = self.hw.set_fan_speed(level)
        # 상태 MQTT 발행 (DB/앱이 필요하다면 사용)
        self.mqtt.publish_status("power", {
            "state": "on" if power else "off"
        })
        self.mqtt.publish_status("speed", {
            "level": speed
        })

    def handle_angle(self, direction: str):
        from hardware import _current_angle_h, _current_angle_v  # 간단히 재사용

        step_angle = 5
        if direction == "left":
            target_h = max(0, _current_angle_h - step_angle)
            self.hw.rotate_motor_2axis("horizontal", target_h)
        elif direction == "right":
            target_h = min(180, _current_angle_h + step_angle)
            self.hw.rotate_motor_2axis("horizontal", target_h)
        elif direction == "up":
            target_v = max(0, _current_angle_v - step_angle)
            self.hw.rotate_motor_2axis("vertical", target_v)
        elif direction == "down":
            target_v = min(180, _current_angle_v + step_angle)
            self.hw.rotate_motor_2axis("vertical", target_v)

    def handle_face_detected(self, payload: dict):
        """AI가 각도를 직접 계산해서 보내려면 angle_h / angle_v 사용"""
        angle_h = payload.get("angle_h")
        angle_v = payload.get("angle_v")

        user_id = payload.get("user_id")
        print(f"[FACE] 👤 User {user_id}: H={angle_h}, V={angle_v}")

        if angle_h is not None:
            self.hw.rotate_motor_2axis("horizontal", angle_h)
        if angle_v is not None:
            self.hw.rotate_motor_2axis("vertical", angle_v)

    def handle_user_register(self, payload: dict):
        name = payload.get("name", "")
        user_id = payload.get("user_id") or name.lower().replace(" ", "_")
        print(f"[USER] ✅ Register request: {name} ({user_id})")
        # 실제 저장/처리는 DB Service가 담당 (fan은 알림만)
