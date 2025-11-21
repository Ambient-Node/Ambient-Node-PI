import time
import serial
import threading

class FanHardware:
    def __init__(self, config, on_status_received):
        self.config = config
        self.on_status_received = on_status_received
        self.ser = None
        self.running = False
        self._connect_serial()
    
    def _connect_serial(self):
        try:
            self.ser = serial.Serial(
                self.config.SERIAL_PORT,
                self.config.SERIAL_BAUDRATE,
                timeout=1
            )
            print(f"[UART] ✅ Connected to {self.config.SERIAL_PORT} @ {self.config.SERIAL_BAUDRATE}")
            time.sleep(2)
            self.running = True
            threading.Thread(target=self._read_loop, daemon=True).start()
        except Exception as e:
            print(f"[UART] ❌ Connection failed: {e}")
            self.ser = None
    
    def _read_loop(self):
        while self.running and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting > 0:
                    line = self.ser.readline().decode('utf-8').strip()
                    if line:
                        print(f"[UART] ⬅️ {line}")
                        self.on_status_received(line)
            except Exception as e:
                print(f"[UART] ❌ Read error: {e}")
                time.sleep(1)
    
    def send_command(self, cmd: str):
        if not self.ser or not self.ser.is_open:
            print("[UART] ⚠️ Serial not open")
            return
        try:
            line = (cmd.strip() + "\n").encode("utf-8")
            self.ser.write(line)
            self.ser.flush()
            print(f"[UART] ➡️ {cmd}")
        except Exception as e:
            print(f"[UART] ❌ Write failed: {e}")
    
    def cleanup(self):
        self.running = False
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
                print("[UART] 🔌 Disconnected")
            except Exception:
                pass
