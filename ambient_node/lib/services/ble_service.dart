import 'dart:convert';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:permission_handler/permission_handler.dart';

class BleService {
  BluetoothDevice? _device;
  BluetoothCharacteristic? _txChar;

  // 필터: 기기 이름 또는 서비스 UUID로 찾기 (필요시 수정)
  final String
      namePrefix; // 기기 이름 접두사. ex) namePrefix = 'Ambient' 면 기기 이름이 'Ambient' 로 시작하는 기기를 찾음
  final Guid? serviceUuid;
  final Guid? writeCharUuid;

  BleService(
      {this.namePrefix = 'Ambient', this.serviceUuid, this.writeCharUuid});

  Future<bool> _ensurePermissions() async {
    // Android 12+: BLUETOOTH_SCAN/CONNECT, 그 외 위치 권한 필요
    final statuses = await [
      Permission.bluetoothScan,
      Permission.bluetoothConnect,
      Permission.locationWhenInUse,
    ].request();
    final ok = statuses.values.every((s) => s.isGranted);
    return ok;
  }

  Future<bool> connect(
      {Duration scanTimeout = const Duration(seconds: 8)}) async {
    final granted = await _ensurePermissions();
    if (!granted) return false;

    // Bluetooth 상태 확인
    if (await FlutterBluePlus.adapterState.firstWhere((s) => true) !=
        BluetoothAdapterState.on) {
      // 사용자가 직접 켜야 함
    }

    // 스캔 시작
    await FlutterBluePlus.startScan(timeout: scanTimeout);
    BluetoothDevice? found;

    await for (final scanRes in FlutterBluePlus.scanResults) {
      for (final r in scanRes) {
        final name = r.device.advName.isNotEmpty
            ? r.device.advName
            : r.device.platformName;
        final matchesName = name.isNotEmpty &&
            name.toLowerCase().startsWith(namePrefix.toLowerCase());
        final advUuids = r.advertisementData.serviceUuids
            .map((g) => g.str.toLowerCase())
            .toList();
        final matchesService = serviceUuid != null &&
            advUuids.contains(serviceUuid!.str.toLowerCase());
        if (matchesName || matchesService) {
          found = r.device;
          break;
        }
      }
      if (found != null) break;
    }
    await FlutterBluePlus.stopScan();

    found ??= (FlutterBluePlus.lastScanResults.isNotEmpty
        ? FlutterBluePlus.lastScanResults.first.device
        : null);
    if (found == null) return false;

    _device = found;

    // 연결
    try {
      await _device!.connect(autoConnect: false);
    } catch (error) {
      if (!(_device!.isConnected)) {
        return false;
      }
    }

    // 서비스/특성 탐색
    final services = await _device!.discoverServices();
    BluetoothCharacteristic? candidate;

    if (serviceUuid != null) {
      BluetoothService? svc;
      for (final s in services) {
        if (s.uuid == serviceUuid) {
          svc = s;
          break;
        }
      }
      if (svc != null && svc.characteristics.isNotEmpty) {
        candidate = _selectWritableCharacteristic(svc.characteristics);
      }
    }

    if (candidate == null) {
      for (final s in services) {
        final c = _selectWritableCharacteristic(s.characteristics);
        if (c != null) {
          candidate = c;
          break;
        }
      }
    }

    if (writeCharUuid != null) {
      for (final c in services.expand((s) => s.characteristics)) {
        if (c.uuid == writeCharUuid) {
          candidate = c;
          break;
        }
      }
    }

    _txChar = candidate;
    return true;
  }

  BluetoothCharacteristic? _selectWritableCharacteristic(
      List<BluetoothCharacteristic> chars) {
    try {
      return chars.firstWhere(
          (c) => c.properties.writeWithoutResponse || c.properties.write);
    } catch (_) {
      return null;
    }
  }

  Future<void> send(Map<String, dynamic> msg) async {
    if (_txChar == null) return;
    final data = utf8.encode(json.encode(msg));
    final canWnr = _txChar!.properties.writeWithoutResponse;
    await _txChar!.write(data, withoutResponse: canWnr);
  }
}
