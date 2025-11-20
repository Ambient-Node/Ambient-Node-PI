#!/usr/bin/env bash
set -e

echo "[SETUP] BLE Gateway dependencies installing..."

# 1. 시스템 패키지
sudo apt-get update
sudo apt-get install -y \
  bluez \
  libdbus-1-dev \
  libglib2.0-dev \
  libbluetooth-dev \
  libgirepository1.0-dev \
  libcairo2-dev \
  gir1.2-gtk-3.0 \
  python3-gi \
  python3-dbus

# 2. 파이썬 패키지 (시스템 전역 또는 venv 선택)
sudo pip3 install --no-cache-dir \
  bluezero==0.8.0 \
  dbus-python==1.3.2 \
  PyGObject==3.48.2 \
  paho-mqtt==1.6.1

# 3. BLE Gateway 코드 배치 (선호 경로에 맞게 수정)
sudo mkdir -p /opt/ambient-node/BLE_gateway
sudo cp ble_gateway.py /opt/ambient-node/BLE_gateway/

# 4. systemd 서비스 유닛 설치
sudo cp ambient-ble-gateway.service /etc/systemd/system/
sudo cp rpicam-stream.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable rpicam-stream.service
sudo systemctl enable ambient-ble-gateway.service

echo "[SETUP] Done. Now start services:"
echo "  sudo systemctl start rpicam-stream.service"
echo "  sudo systemctl start ambient-ble-gateway.service"
