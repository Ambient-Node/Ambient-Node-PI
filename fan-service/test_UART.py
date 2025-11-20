#!/usr/bin/env python3
import serial
import time

def main():
    # 라즈베리파이 GPIO UART: 보통 /dev/serial0 로 매핑
    ser = serial.Serial(
        port="/dev/serial0",
        baudrate=9600,
        timeout=0.1,   # 100ms 단위로 폴링
    )

    # 보드 리셋/부트 시간 여유
    time.sleep(2)

    print("[UART] started on /dev/serial0 @ 9600")

    last_send = 0

    try:
        while True:
            now = time.time()

            # 2초마다 hello 전송
            if now - last_send >= 2.0:
                msg = "hello\n"
                ser.write(msg.encode("utf-8"))
                ser.flush()
                print(f"[TX] {msg.strip()}")
                last_send = now

            # 수신 데이터 있으면 한 줄씩 읽어서 출력
            if ser.in_waiting > 0:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    print(f"[RX] {line}")

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n[EXIT] stop")
    finally:
        ser.close()

if __name__ == "__main__":
    main()
