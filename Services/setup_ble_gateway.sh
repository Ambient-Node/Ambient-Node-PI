#!/usr/bin/env bash
set -e

echo "[SETUP] BLE Gateway dependencies installing..."

# 1. 시스템 패키지
sudo apt-get update
sudo apt-get install -y bluez bluetooth python3-pip python3-gi python3-dbus
  # libdbus-1-dev \
  # libglib2.0-dev \
  # libbluetooth-dev \
  # libgirepository1.0-dev \
  # libcairo2-dev \
  # gir1.2-gtk-3.0 \

sudo python3.11 -m venv --system-site-packages .venv
source .venv/bin/activate

# 2. 파이썬 패키지 (시스템 전역 또는 venv 선택)
pip3 install --user paho-mqtt
pip3 install bluezero

# 4. systemd 서비스 유닛 설치
# sudo cp /home/pi/ambient-node/Services/ambient-ble-gateway.service /etc/systemd/system/
# sudo cp /home/pi/ambient-node/Services/rpicam-stream.service /etc/systemd/system/

# sudo systemctl daemon-reload
# sudo systemctl enable rpicam-stream.service
# sudo systemctl enable ambient-ble-gateway.service

echo "[SETUP] Done. Now start services:"
echo "  sudo systemctl start rpicam-stream.service"
echo "  sudo systemctl start ambient-ble-gateway.service"
