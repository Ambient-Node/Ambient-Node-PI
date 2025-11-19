# hardware.py
import time

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    print(f"[WARN] GPIO not available: {e}")
    GPIO_AVAILABLE = False
    GPIO = None

_current_speed = 0
_current_angle_h = 90
_current_angle_v = 90
_pwm = None

class FanHardware:
    def __init__(self, config):
        self.config = config
        if GPIO_AVAILABLE:
            self._init_gpio()
        else:
            print("[GPIO] ⚠️ Running in simulation mode")

    def _init_gpio(self):
        global _pwm
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        try:
            GPIO.cleanup()
        except Exception:
            pass

        GPIO.setup(self.config.FAN_PWM_PIN, GPIO.OUT)
        GPIO.setup(self.config.MOTOR_STEP_PIN_H, GPIO.OUT)
        GPIO.setup(self.config.MOTOR_DIR_PIN_H, GPIO.OUT)
        GPIO.setup(self.config.MOTOR_STEP_PIN_V, GPIO.OUT)
        GPIO.setup(self.config.MOTOR_DIR_PIN_V, GPIO.OUT)

        _pwm = GPIO.PWM(self.config.FAN_PWM_PIN, 1000)
        _pwm.start(0)
        print("[GPIO] ✅ Initialized")

    def set_fan_speed(self, speed: int):
        """팬 속도 설정 (0~100), 0이면 OFF"""
        global _current_speed, _pwm
        speed = max(0, min(100, int(speed)))

        if GPIO_AVAILABLE and _pwm:
            _pwm.ChangeDutyCycle(speed)

        _current_speed = speed
        power = speed > 0
        print(f"[FAN] 🌀 Speed: {speed}%, Power: {'ON' if power else 'OFF'}")
        return power, speed

    def rotate_motor_2axis(self, axis: str, target_angle: int):
        """2축 모터 제어 (0~180도)"""
        global _current_angle_h, _current_angle_v

        target_angle = max(0, min(180, int(target_angle)))

        if not GPIO_AVAILABLE:
            if axis == "horizontal":
                _current_angle_h = target_angle
            elif axis == "vertical":
                _current_angle_v = target_angle
            print(f"[MOTOR] 🔧 Simulated {axis} → {target_angle}°")
            return

        if axis == "horizontal":
            current = _current_angle_h
            step_pin = self.config.MOTOR_STEP_PIN_H
            dir_pin = self.config.MOTOR_DIR_PIN_H
        elif axis == "vertical":
            current = _current_angle_v
            step_pin = self.config.MOTOR_STEP_PIN_V
            dir_pin = self.config.MOTOR_DIR_PIN_V
        else:
            return

        direction = 1 if target_angle > current else 0
        GPIO.output(dir_pin, direction)
        steps = abs(int((target_angle - current) * 10))  # 1도=10스텝 기준

        for _ in range(steps):
            GPIO.output(step_pin, GPIO.HIGH)
            time.sleep(0.001)
            GPIO.output(step_pin, GPIO.LOW)
            time.sleep(0.001)

        if axis == "horizontal":
            _current_angle_h = target_angle
        else:
            _current_angle_v = target_angle

        print(f"[MOTOR] ✅ {axis.capitalize()} → {target_angle}°")

    def cleanup(self):
        global _pwm
        print("[HARDWARE] 🧹 Cleaning up GPIO...")
        if GPIO_AVAILABLE:
            if _pwm:
                _pwm.stop()
            GPIO.cleanup()
