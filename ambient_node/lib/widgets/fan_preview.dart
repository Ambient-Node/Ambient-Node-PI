import 'dart:math';
import 'package:flutter/material.dart';

class FanPreview extends StatelessWidget {
  final bool powerOn;
  final int speed;
  const FanPreview({super.key, required this.powerOn, required this.speed});
  @override
  Widget build(BuildContext context) {
    return SizedBox(
        height: 180,
        width: 180,
        child: Stack(alignment: Alignment.center, children: [
          Container(decoration: BoxDecoration(color: Colors.blueGrey[50], shape: BoxShape.circle)),
          for (var i = 0; i < 3; i++)
            Transform.rotate(
                angle: i * 2 * pi / 3,
                child: Container(
                    height: 70,
                    width: 12,
                    decoration: BoxDecoration(
                        color: Colors.blueGrey[200], borderRadius: BorderRadius.circular(6))))
          ,
          Container(
              height: 28,
              width: 28,
              decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle, boxShadow: [BoxShadow(blurRadius: 4, color: Colors.black12)])),
        ]));
  }
}
