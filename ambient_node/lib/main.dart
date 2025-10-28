import 'dart:async';
import 'package:flutter/material.dart';
import 'package:ambient_node/screens/splash_screen.dart';
import 'package:ambient_node/screens/dashboard_screen.dart';
import 'package:ambient_node/screens/analytics_screen.dart';
import 'package:ambient_node/screens/control_screen.dart';

class AiService {}

class BleService {
  Future<void> sendJson(Map<String, dynamic> data) async {
    print('BLE Service: Sending JSON: $data');
  }
}

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
  final ble = BleService();

  // 앱의 핵심 상태 변수
  bool connected = true;
  String deviceName = 'Ambient';
  int speed = 0; // 0이면 전원 OFF와 동일
  bool trackingOn = false;
  // 사용자 선택 상태 (모든 스크린이 공유)
  String? selectedUserName;
  String? selectedUserImagePath;

  @override
  void initState() {
    super.initState();
  }

  @override
  void dispose() {
    super.dispose();
  }

  // 블루투스 연결 화면을 띄우는 함수
  void handleConnect() {
    // Navigator.of(context).push(
    //   MaterialPageRoute(
    //     builder: (context) => DeviceSelectionScreen(
    //       bleService: TestBleService(
    //         namePrefix: 'Ambient',
    //         serviceUuid: null,
    //         writeCharUuid: null,
    //         notifyCharUuid: null,
    //       ),
    //       onDeviceNameChanged: (name) {
    //         setState(() => deviceName = name);
    //       },
    //       onConnectionChanged: (isConnected) {
    //         setState(() {
    //           connected = isConnected;
    //           if (isConnected) {
    //             powerOn = true;
    //             _showSnackBar('기기가 연결되었습니다.');
    //           } else {
    //             powerOn = false;
    //             _showSnackBar('기기 연결이 해제되었습니다.');
    //           }
    //           sendState();
    //         });
    //       },
    //     ),
    //   ),
    // );
  }

  // 현재 상태를 블루투스로 전송하는 함수
  void sendState() {
    if (!connected) return;
    ble.sendJson({
      'speed': speed, // 0이면 전원 OFF
      'trackingOn': speed > 0 ? trackingOn : false,
    });
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
        },
        trackingOn: trackingOn,
        setTrackingOn: (v) {
          setState(() => trackingOn = v);
          sendState();
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
        },
        onUserDataSend: (data) {
          // TODO: BLE를 통해 라즈베리파이로 사용자 데이터 전송
          // 실제 구현 시 이미지를 Base64로 인코딩하여 전송해야 함
          print('🔵 BLE 전송 준비: $data');
          ble.sendJson(data);
        },
      ),
      const AnalyticsScreen(),
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
