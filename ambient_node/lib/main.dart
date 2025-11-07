import 'dart:async';
import 'package:flutter/material.dart';
import 'package:ambient_node/screens/splash_screen.dart';
import 'package:ambient_node/screens/dashboard_screen.dart';
import 'package:ambient_node/screens/analytics_screen.dart';
import 'package:ambient_node/screens/control_screen.dart';
import 'package:ambient_node/screens/device_selection_screen.dart';
import 'package:ambient_node/services/analytics_service.dart';
import 'package:ambient_node/services/test_ble_service.dart';

class AiService {}

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Ambient Node',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),
        useMaterial3: true,
      ),
      home: const SplashWrapper(),
    );
  }
}

class SplashWrapper extends StatefulWidget {
  const SplashWrapper({super.key});

  @override
  State<SplashWrapper> createState() => _SplashWrapperState();
}

class _SplashWrapperState extends State<SplashWrapper> {
  bool _showMain = false;

  @override
  Widget build(BuildContext context) {
    if (_showMain) {
      return const MainShell();
    }

    return SplashScreen(
      onFinish: () {
        setState(() => _showMain = true);
      },
    );
  }
}

class MainShell extends StatefulWidget {
  const MainShell({super.key});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _index = 0;
  late final TestBleService ble;

  // 앱의 핵심 상태 변수
  bool connected = false; // 초기값 false로 변경
  String deviceName = 'Ambient';
  int speed = 0; // 0이면 전원 OFF와 동일
  bool trackingOn = false;
  // 사용자 선택 상태 (모든 스크린이 공유)
  String? selectedUserName;
  String? selectedUserImagePath;

  @override
  void initState() {
    super.initState();
    
    // BLE 서비스 초기화
    ble = TestBleService(
      namePrefix: 'Ambient',
      serviceUuid: null,
      writeCharUuid: null,
      notifyCharUuid: null,
    );
    
    // BLE 연결 상태 콜백 설정
    ble.onConnectionStateChanged = (isConnected) {
      print('🔵 [BLE] 연결 상태 변경: $isConnected');
      if (mounted) {
        setState(() {
          connected = isConnected;
          if (!isConnected) {
            speed = 0;
            trackingOn = false;
          }
        });
      }
    };
    
    // BLE 기기 이름 콜백 설정
    ble.onDeviceNameChanged = (name) {
      print('🔵 [BLE] 기기 이름: $name');
      if (mounted) {
        setState(() {
          deviceName = name;
        });
      }
    };
    
    // BLE Notification 수신 콜백
    ble.onPairingResponse = (response) {
      print('🔵 [BLE] Notification 수신: $response');
    };
    
    // 분석 서비스 초기화
    AnalyticsService.onUserChanged(selectedUserName);
  }

  @override
  void dispose() {
    ble.dispose();
    super.dispose();
  }

  // 블루투스 연결 화면을 띄우는 함수
  void handleConnect() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (context) => DeviceSelectionScreen(
          bleService: ble,
          onConnectionChanged: (isConnected) {
            print('🔵 [Main] 연결 상태 업데이트: $isConnected');
            if (mounted) {
              setState(() {
                connected = isConnected;
                if (isConnected) {
                  _showSnackBar('기기가 연결되었습니다.');
                  sendState();
                } else {
                  speed = 0;
                  trackingOn = false;
                  _showSnackBar('기기 연결이 해제되었습니다.');
                }
              });
            }
          },
          onDeviceNameChanged: (name) {
            print('🔵 [Main] 기기 이름 업데이트: $name');
            if (mounted) {
              setState(() => deviceName = name);
            }
          },
        ),
      ),
    );
  }
  
  void _showSnackBar(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  // 현재 상태를 블루투스로 전송하는 함수
  void sendState() {
    if (!connected) {
      print('⚠️ [BLE] 연결되지 않음 - 전송 취소');
      return;
    }
    
    final data = {
      'speed': speed, // 0이면 전원 OFF
      'trackingOn': speed > 0 ? trackingOn : false,
    };
    
    print('📤 [BLE] 데이터 전송: $data');
    
    try {
      ble.sendJson(data);
    } catch (e) {
      print('❌ [BLE] 전송 실패: $e');
      _showSnackBar('데이터 전송 실패');
    }
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      DashboardScreen(
        connected: connected,
        onConnect: handleConnect,
        speed: speed,
        setSpeed: (v) {
          setState(() => speed = v);
          sendState();
          // 속도 변경 시 분석 서비스에 알림 (안전하게 호출)
          try {
            AnalyticsService.onSpeedChanged(v);
          } catch (e) {
            print('❌ AnalyticsService.onSpeedChanged 오류: $e');
          }
        },
        trackingOn: trackingOn,
        setTrackingOn: (v) {
          setState(() => trackingOn = v);
          sendState();
          // 얼굴 추적 상태 변경 시 분석 서비스에 알림 (안전하게 호출)
          try {
            if (v) {
              AnalyticsService.onFaceTrackingStart();
            } else {
              AnalyticsService.onFaceTrackingStop();
            }
          } catch (e) {
            print('❌ AnalyticsService.onFaceTracking 오류: $e');
          }
        },
        openAnalytics: () => setState(() => _index = 2),
        deviceName: deviceName,
        selectedUserName: selectedUserName,
        selectedUserImagePath: selectedUserImagePath,
      ),
      ControlScreen(
        connected: connected,
        deviceName: deviceName,
        onConnect: handleConnect,
        selectedUserName: selectedUserName,
        onUserSelectionChanged: (userName, userImagePath) {
          setState(() {
            selectedUserName = userName;
            selectedUserImagePath = userImagePath;
          });
          // 사용자 변경 시 분석 서비스에 알림 (안전하게 호출)
          try {
            AnalyticsService.onUserChanged(userName);
          } catch (e) {
            print('❌ AnalyticsService.onUserChanged 오류: $e');
          }
        },
        onUserDataSend: (data) {
          // TODO: BLE를 통해 라즈베리파이로 사용자 데이터 전송
          // 실제 구현 시 이미지를 Base64로 인코딩하여 전송해야 함
          print('🔵 BLE 전송 준비: $data');
          ble.sendJson(data);
        },
      ),
      AnalyticsScreen(selectedUserName: selectedUserName),
    ];

    return Scaffold(
      body: SafeArea(
        child: IndexedStack(
          index: _index,
          children: screens,
        ),
      ),
      bottomNavigationBar: Container(
        height: 89,
        decoration: BoxDecoration(
          color: Colors.white,
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.05),
              blurRadius: 10,
              offset: const Offset(0, -2),
            ),
          ],
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceEvenly,
          children: [
            _buildNavItem(
              icon: Icons.dashboard_outlined,
              label: '대시보드',
              isSelected: _index == 0,
              onTap: () => setState(() => _index = 0),
            ),
            _buildNavItem(
              icon: Icons.control_camera,
              label: '제어',
              isSelected: _index == 1,
              onTap: () => setState(() => _index = 1),
            ),
            _buildNavItem(
              icon: Icons.analytics_outlined,
              label: '분석',
              isSelected: _index == 2,
              onTap: () => setState(() => _index = 2),
            ),
            _buildNavItem(
              icon: Icons.settings_outlined,
              label: '설정',
              isSelected: false,
              onTap: () {}, // 기능 미구현
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildNavItem({
    required IconData icon,
    required String label,
    required bool isSelected,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      child: Container(
        width: 60,
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              size: 24,
              color: isSelected
                  ? const Color(0xFF3A90FF)
                  : const Color(0xFF838799),
            ),
            const SizedBox(height: 5),
            Text(
              label,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: isSelected
                    ? const Color(0xFF3A90FF)
                    : const Color(0xFF838799),
                fontSize: 13,
                fontFamily: 'Sen',
                fontWeight: FontWeight.w400,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
