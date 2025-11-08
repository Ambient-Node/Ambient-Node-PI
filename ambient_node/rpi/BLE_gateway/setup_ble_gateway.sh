#!/bin/bash

# BLE Gateway 설치 스크립트
# 라즈베리파이 호스트에서 실행

set -e

echo "=========================================="
echo "Ambient Node BLE Gateway 설치"
echo "=========================================="

# 1. 필요한 패키지 설치
echo ""
echo "[1/5] 시스템 패키지 설치 중..."
sudo apt update
sudo apt install -y \
    python3-pip \
    python3-dbus \
    python3-gi \
    python3-bluezero \
    bluetooth \
    bluez

# 2. Python 패키지 설치
echo ""
echo "[2/5] Python 패키지 설치 중..."
pip3 install --user paho-mqtt

# 3. Bluetooth 설정
echo ""
echo "[3/5] Bluetooth 설정 중..."
sudo systemctl enable bluetooth
sudo systemctl start bluetooth

# Bluetooth를 pairable 및 discoverable로 설정
sudo bluetoothctl <<EOF
power on
pairable on
discoverable on
exit
EOF

# 4. systemd 서비스 설치
echo ""
echo "[4/5] systemd 서비스 설치 중..."

# 현재 디렉토리 확인
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 서비스 파일 복사
sudo cp "$SCRIPT_DIR/ambient-ble-gateway.service" /etc/systemd/system/

# 서비스 파일에서 경로 업데이트 (현재 디렉토리 기준)
sudo sed -i "s|/home/pi/ambient-node/rpi|$SCRIPT_DIR|g" /etc/systemd/system/ambient-ble-gateway.service

# systemd 리로드
sudo systemctl daemon-reload

# 서비스 활성화 및 시작
sudo systemctl enable ambient-ble-gateway.service
sudo systemctl start ambient-ble-gateway.service

# 5. 상태 확인
echo ""
echo "[5/5] 설치 완료!"
echo ""
echo "=========================================="
echo "BLE Gateway 상태 확인"
echo "=========================================="
sudo systemctl status ambient-ble-gateway.service --no-pager

echo ""
echo "=========================================="
echo "유용한 명령어"
echo "=========================================="
echo "서비스 상태 확인:  sudo systemctl status ambient-ble-gateway"
echo "서비스 중지:       sudo systemctl stop ambient-ble-gateway"
echo "서비스 시작:       sudo systemctl start ambient-ble-gateway"
echo "서비스 재시작:     sudo systemctl restart ambient-ble-gateway"
echo "로그 확인:         sudo journalctl -u ambient-ble-gateway -f"
echo "=========================================="
