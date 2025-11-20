# handlers.py

from datetime import datetime
from hardware import _current_angle_h, _current_angle_v  # 현재 각도 참조

class FanHandlers:
    def __init__(self, hardware, mqtt_client):
        self.hw = hardware          # FanHardware 인스턴스
        self.mqtt = mqtt_client     # FanMQTTClient 인스턴스

    # 중앙 진입점: mqtt_client가 여기로 위임
    def handle_mqtt_message(self, topic: str, payload: dict):
        print(f"[MQTT] 📥 {topic}: {payload}")

        if topic == "ambient/ai/face-detected":
            # (지금은 angle_h / angle_v가 없으니 사실상 로그만 남음)
            self.handle_face_detected(payload)

        elif topic.startswith("ambient/command/"):
            cmd = topic.split("/")[-1]   # speed / angle / mode
            self.handle_command(cmd, payload)

        elif topic == "ambient/user/register":
            self.handle_user_register(payload)

        else:
            print(f"[MQTT] ⚠️ Unhandled topic: {topic}")

    # --------------------------------------------------
    # 명령 처리 (speed / angle / mode)
    # --------------------------------------------------
    def handle_command(self, cmd: str, payload: dict):
        print(f"[CMD] 🎯 Command: {cmd}")

        if cmd == "speed":
            """
            BLE Gateway → MQTT: ambient/command/speed
            payload 예시:
            {
              "event_type": "speed_change",
              "speed": 0~5,
              "timestamp": "..."
            }
            """
            speed_level = payload.get("speed", 0)
            try:
                speed_level = int(speed_level)
            except Exception:
                speed_level = 0

            # 0~5 → 0~100 매핑 (단계별로 명시)
            SPEED_MAP = {
                0: 0,    # OFF
                1: 20,   # 약
                2: 40,   # 중약
                3: 60,   # 중
                4: 80,   # 중강
                5: 100,  # 강
            }
            level = SPEED_MAP.get(speed_level, 0)
            self.set_fan_speed(level)

        elif cmd == "angle":
            """
            BLE Gateway / AI → MQTT: ambient/command/angle
            payload 예시:
            {
              "event_type": "angle_change",
              "direction": "left" | "right" | "up" | "down" | "center",
              "angle": 45 (선택, 절대각)
            }
            """
            direction = payload.get("direction")
            angle = payload.get("angle")  # 절대각(0~180)이면 우선 사용
            self.handle_angle(direction, angle)

        elif cmd == "mode":
            """
            BLE Gateway → MQTT: ambient/command/mode
            payload 예시:
            {
              "event_type": "mode_change",
              "mode": "manual" | "ai",
              "timestamp": "..."
            }
            """
            mode = payload.get("mode")
            print(f"[CMD] Mode change (fan side): {mode}")
            # 지금 단계에서는 팬은 모드 정보를 주로 로그용으로만 사용
            # (필요해지면 여기서 회전 패턴 등을 구현)

    # --------------------------------------------------
    # 속도 제어 + 상태 발행
    # --------------------------------------------------
    def set_fan_speed(self, level: int):
        """
        level: 0~100 (PWM duty)
        """
        power, speed = self.hw.set_fan_speed(level)

        # 상태 MQTT 발행 (DB/모니터링 용도, 선택적)
        if self.mqtt:
            self.mqtt.publish_status("power", {
                "state": "on" if power else "off"
            })
            self.mqtt.publish_status("speed", {
                "level": speed
            })

    # --------------------------------------------------
    # 각도 제어
    # --------------------------------------------------
    def handle_angle(self, direction: str, absolute_angle: int | None):
        """
        direction: left/right/up/down/center
        absolute_angle: 수평 기준 절대 각도(0~180)일 경우, direction 무시하고 적용
        """
        step_angle = 5

        # 수평(좌/우) 절대각이 온 경우
        if absolute_angle is not None:
            try:
                target = max(0, min(180, int(absolute_angle)))
            except Exception:
                target = 90
            print(f"[ANGLE] 🎯 Absolute H angle → {target}°")
            self.hw.rotate_motor_2axis("horizontal", target)
            return

        # direction 기반 상대 이동
        global _current_angle_h, _current_angle_v

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

        elif direction == "center":
            # 가운데(정면)으로 복귀
            self.hw.rotate_motor_2axis("horizontal", 90)
            self.hw.rotate_motor_2axis("vertical", 90)

        else:
            print(f"[ANGLE] ⚠️ Unknown direction: {direction}")

    # --------------------------------------------------
    # AI 얼굴 이벤트 (향후 확장용)
    # --------------------------------------------------
    def handle_face_detected(self, payload: dict):
        """
        AI Service → MQTT: ambient/ai/face-detected
        현재 페이로드:
        {
          "event_type": "face_detected",
          "session_id": "...",
          "user_id": "user_001",
          "confidence": 0.87,
          "x": 1024,
          "y": 320,
          "timestamp": "..."
        }

        지금은 각도 정보가 없으니, 단순 로그만 남기고 동작은 하지 않는다.
        나중에 AI가 angle_h/angle_v를 넣어주면 여기서 사용.
        """
        user_id = payload.get("user_id")
        x = payload.get("x")
        y = payload.get("y")
        print(f"[FACE] 👤 Detected user={user_id}, pos=({x}, {y})")
        # 향후: x,y → angle_h, angle_v 계산해서 rotate_motor_2axis 호출 가능

    # --------------------------------------------------
    # 기타 (현재는 알림만)
    # --------------------------------------------------
    def handle_user_register(self, payload: dict):
        name = payload.get("name", "")
        user_id = payload.get("user_id") or name.lower().replace(" ", "_")
        print(f"[USER] ✅ Register request observed by fan: {name} ({user_id})")
        # 실제 저장/처리는 DB Service가 담당 (fan은 알림만)
