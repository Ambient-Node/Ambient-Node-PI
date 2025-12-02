# # chmod +x init_setting.sh

# # 블루투스 인터페이스 활성화
# sudo hciconfig hci0 up

# # 블루투스 완전히 재시작
# sudo systemctl stop ambient-ble-gateway
# sudo systemctl stop bluetooth
# sudo hciconfig hci0 down # 하드웨어 리셋
# sudo hciconfig hci0 up
# sudo systemctl start bluetooth
# sudo systemctl start ambient-ble-gateway

# # 기존 페어링 정보 삭제
# sudo systemctl stop bluetooth
# sudo rm -f /var/lib/bluetooth/*/*
# sudo systemctl start bluetooth

# # SSP 비활성화
# sudo hciconfig hci0 sspmode 0

sudo mkdir -p /var/lib/ambient-node/users
sudo chown -R pi:pi /var/lib/ambient-node
sudo chmod -R 755 /var/lib/ambient-node
