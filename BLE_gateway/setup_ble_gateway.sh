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
    bluetooth \
    bluez

# 2. 가상환경 설치 python version 3.11.2여야 dbus 실행할 수 있음.
sudo python3.11 -m venv --system-site-packages .venv
source .venv/bin/activate

# 2. Python 패키지 설치
echo ""
echo "[2/5] Python 패키지 설치 중..."
pip3 install --user paho-mqtt
pip3 install bluezero

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

# # 4. systemd 서비스 설치
# echo ""
# echo "[4/5] systemd 서비스 설치 중..."

# # systemd 리로드
# sudo systemctl daemon-reload

# # 서비스 활성화 및 시작
# sudo systemctl enable ambient-ble-gateway.service
# sudo systemctl start ambient-ble-gateway.service

# # 5. 상태 확인
# echo ""
# echo "[5/5] 설치 완료!"
# echo ""
# echo "=========================================="
# echo "BLE Gateway 상태 확인"
# echo "=========================================="
# sudo systemctl status ambient-ble-gateway.service --no-pager

# echo ""
# echo "=========================================="
# echo "유용한 명령어"
# echo "=========================================="
# echo "서비스 상태 확인:  sudo systemctl status ambient-ble-gateway"
# echo "서비스 중지:       sudo systemctl stop ambient-ble-gateway"
# echo "서비스 시작:       sudo systemctl start ambient-ble-gateway"
# echo "서비스 재시작:     sudo systemctl restart ambient-ble-gateway"
# echo "로그 확인:         sudo journalctl -u ambient-ble-gateway -f  || sudo journalctl -u ambient-ble-gateway -o cat"
# echo "=========================================="


# # 사용자 폴더 생성을 위한 권한 설정
# ls -ld /var/lib/ambient-node /var/lib/ambient-node/users
# sudo chown -R $(whoami):$(whoami) /var/lib/ambient-node
# sudo chmod -R u+rwX /var/lib/ambient-node