import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

class AnalyticsScreen extends StatelessWidget {
  const AnalyticsScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final usage = [1.2, 0.8, 2.1, 1.6, 3.0, 4.2, 2.4];
    final modes = [12.0, 34.0, 28.0, 9.0];
    return SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(children: [
          Card(
              child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(children: [
                    Text('주간 사용 시간',
                        style: TextStyle(fontWeight: FontWeight.w600)),
                    SizedBox(
                        height: 200,
                        child: LineChart(LineChartData(lineBarsData: [
                          LineChartBarData(
                              spots: List.generate(usage.length,
                                  (i) => FlSpot(i.toDouble(), usage[i])),
                              isCurved: true)
                        ])))
                  ]))),
          const SizedBox(height: 12),
          Card(
              child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(children: [
                    Text('풍량 모드 사용 비율',
                        style: TextStyle(fontWeight: FontWeight.w600)),
                    SizedBox(
                        height: 200,
                        child: BarChart(BarChartData(
                            barGroups: List.generate(
                                modes.length,
                                (i) => BarChartGroupData(x: i, barRods: [
                                      BarChartRodData(toY: modes[i])
                                    ])))))
                  ]))),
          const SizedBox(height: 12),
          Card(
              child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('사용자 패턴 분석',
                            style: TextStyle(fontWeight: FontWeight.w600)),
                        const SizedBox(height: 8),
                        Text('• 매일 14:00에 켜고 17:00에 종료 (평균 2.8h)'),
                        Text('• 얼굴 추적 평균 63% 사용'),
                        Text('• 수동 조작 가장 자주 사용한 방향: 우측 20°')
                      ]))),
        ]));
  }
}
