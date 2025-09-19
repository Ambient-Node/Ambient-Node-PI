// main.dart
// Flutter prototype for 'Circulator' app
// - Dashboard, Face Select & Manual Control, Analytics screens
// - Mock AI / BLE services; replace with real implementations when available

import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:ambient_node/services/ble_service.dart';
import 'package:ambient_node/services/mock_ai_service.dart';
import 'package:ambient_node/screens/dashboard_screen.dart';
import 'package:ambient_node/screens/control_screen.dart';
import 'package:ambient_node/screens/analytics_screen.dart';

void main() {
  runApp(const CirculatorApp());
}

class CirculatorApp extends StatelessWidget {
  const CirculatorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Circulator',
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),
      ),
      home: const MainShell(),
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
  final ble = BleService(
    namePrefix: 'Ambient',
    serviceUuid: Guid('12345678-1234-5678-1234-56789abcdef0'),
    writeCharUuid: Guid('12345678-1234-5678-1234-56789abcdef1'),
  );
  final ai = MockAIService();

  bool connected = false;
  bool powerOn = true;
  int speed = 60;
  bool trackingOn = true;
  String? selectedFaceId;

  @override
  void initState() {
    super.initState();
    ai.start();

    // BLE 연결 상태 모니터링 설정
    ble.onConnectionStateChanged = (isConnected) {
      if (mounted) {
        setState(() => connected = isConnected);
      }
    };
  }

  @override
  void dispose() {
    ai.dispose();
    ble.dispose();
    super.dispose();
  }

  Future<void> handleConnect() async {
    await ble.connect();
    // 연결 상태는 onConnectionStateChanged 콜백에서 처리됨
  }

  void sendState() {
    ble.send({
      'powerOn': powerOn,
      'speed': speed,
      'trackingOn': trackingOn,
      'selectedFaceId': selectedFaceId,
    });
  }

  @override
  Widget build(BuildContext context) {
    WidgetsBinding.instance.addPostFrameCallback((_) => sendState());

    final screens = [
      DashboardScreen(
        connected: connected,
        onConnect: handleConnect,
        powerOn: powerOn,
        setPowerOn: (v) => setState(() => powerOn = v),
        speed: speed,
        setSpeed: (v) => setState(() => speed = v),
        trackingOn: trackingOn,
        setTrackingOn: (v) => setState(() => trackingOn = v),
        openControl: () => setState(() => _index = 1),
      ),
      ControlScreen(
        ai: ai,
        trackingOn: trackingOn,
        setTrackingOn: (v) => setState(() => trackingOn = v),
        selectedFaceId: selectedFaceId,
        selectFace: (id) {
          setState(() => selectedFaceId = id);
          ai.select(id);
        },
        manualMove: (vec) => ble.send({
          'manual': {'x': vec.dx, 'y': vec.dy}
        }),
      ),
      const AnalyticsScreen(),
    ];

    return Scaffold(
      body: SafeArea(child: IndexedStack(index: _index, children: screens)),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _index,
        onTap: (i) => setState(() => _index = i),
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home), label: '대시보드'),
          BottomNavigationBarItem(icon: Icon(Icons.person_search), label: '제어'),
          BottomNavigationBarItem(icon: Icon(Icons.analytics), label: '분석'),
        ],
      ),
    );
  }
}
