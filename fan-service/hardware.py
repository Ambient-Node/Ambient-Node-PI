# hardware.py

import time
import serial  # pip install pyserial

_current_speed = 0
_current_angle_h = 90
_current_angle_v = 90

class FanHardware:
    """
    Raspberry Pi ↔ Arduino 간 UART 어댑터.
    GPIO 대신 직렬 포트로 명령을 보낸다.
    """

    def __init__(self, config):
        self.config = config
        self.ser = None
        self._connect_serial()

    def _connect_serial(self):
        """UART 포트 연결"""
        try:
            self.ser = serial.Serial(
                self.config.SERIAL_PORT,
                self.config.SERIAL_BAUDRATE,
                timeout=1
            )
            print(f"[UART] Connected to {self.config.SERIAL_PORT} @ {self.config.SERIAL_BAUDRATE}")
            # 아두이노 리셋 시간 고려
            time.sleep(2)
        except Exception as e:
            print(f"[UART] Serial connect failed: {e}")
            self.ser = None

    def _send_command(self, cmd: str):
        """아두이노로 한 줄 명령 전송 (예: 'SPEED 60')"""
        if not self.ser or not self.ser.is_open:
            print("[UART] Serial not open, trying to reconnect...")
            self._connect_serial()
            if not self.ser:
                print("[UART] Cannot send command, serial unavailable")
                return

        try:
            line = (cmd.strip() + "\n").encode("utf-8")
            self.ser.write(line)
            self.ser.flush()
            print(f"[UART] ➡️ {cmd}")
        except Exception as e:
            print(f"[UART] Write failed: {e}")
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def set_fan_speed(self, speed: int):
        """팬 속도 설정 (0~5), 0이면 OFF"""
        global _current_speed

        # 0~5 범위
        speed = max(0, min(5, int(speed)))

        # UART로 그대로 보냄
        self._send_command(f"SPEED {speed}")

        _current_speed = speed
        power = speed > 0
        print(f"[FAN] Speed level: {speed}, Power: {'ON' if power else 'OFF'}")
        return power, speed


    def rotate_motor_2axis(self, axis: str, target_angle: int):
        """
        2축 모터 제어 (0~180도)
        axis: "horizontal" | "vertical"
        """
        global _current_angle_h, _current_angle_v

        target_angle = max(0, min(180, int(target_angle)))

        if axis == "horizontal":
            axis_flag = "H"
            _current_angle_h = target_angle
        elif axis == "vertical":
            axis_flag = "V"
            _current_angle_v = target_angle
        else:
            print(f"[MOTOR] Unknown axis: {axis}")
            return

        self._send_command(f"ANGLE {axis_flag} {target_angle}")
        print(f"[MOTOR] {axis.capitalize()} → {target_angle}°")

    def cleanup(self):
        print("[HARDWARE] Cleaning up UART...")
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
            print("[UART] 🔌 Disconnected")
