import 'dart:async';
import 'package:flutter/material.dart';
import '../widgets/fan_preview.dart';
import '../widgets/common_controls.dart';

class DashboardScreen extends StatelessWidget {
  final bool connected;
  final FutureOr<void> Function() onConnect;
  final bool powerOn;
  final void Function(bool) setPowerOn;
  final int speed;
  final void Function(int) setSpeed;
  final bool trackingOn;
  final void Function(bool) setTrackingOn;
  final VoidCallback openControl;

  const DashboardScreen(
      {super.key,
      required this.connected,
      required this.onConnect,
      required this.powerOn,
      required this.setPowerOn,
      required this.speed,
      required this.setSpeed,
      required this.trackingOn,
      required this.setTrackingOn,
      required this.openControl});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Row(children: [
            const Icon(Icons.air),
            const SizedBox(width: 8),
            const Text('Circulator', style: TextStyle(fontWeight: FontWeight.w600))
          ]),
          Row(children: [
            Text(connected ? 'Connected' : 'Offline'),
            const SizedBox(width: 8),
            ElevatedButton(onPressed: () => onConnect(), child: const Text('Pair'))
          ])
        ]),
        const SizedBox(height: 16),
        Center(child: FanPreview(powerOn: powerOn, speed: speed)),
        const SizedBox(height: 16),
        Row(children: [
          Expanded(child: ControlCard(title: '전원', child: Switch(value: powerOn, onChanged: setPowerOn))),
          const SizedBox(width: 8),
          Expanded(
              child: ControlCard(
                  title: '풍량',
                  child: Column(children: [
                    Slider(value: speed.toDouble(), min: 0, max: 100, onChanged: (v) => setSpeed(v.toInt())),
                    Text('$speed%')
                  ]))),
          const SizedBox(width: 8),
          Expanded(child: ControlCard(title: '얼굴 추적', child: Switch(value: trackingOn, onChanged: setTrackingOn))),
        ]),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(child: ElevatedButton(onPressed: openControl, child: const Text('얼굴 선택 & 수동 조작'))),
          const SizedBox(width: 8),
          Expanded(child: OutlinedButton(onPressed: () {}, child: const Text('데이터 분석 보기')))
        ]),
        const SizedBox(height: 16),
        GridView.count(
            crossAxisCount: 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            childAspectRatio: 3,
            children: const [
              StatTile(title: '오늘 사용', value: '3.2h'),
              StatTile(title: '얼굴 추적', value: '17회'),
              StatTile(title: '에너지 절약', value: '18%'),
              StatTile(title: '연속 가동', value: '1.1h'),
            ])
      ]),
    );
  }
}
