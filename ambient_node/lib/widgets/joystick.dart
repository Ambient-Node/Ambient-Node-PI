import 'package:flutter/material.dart';

class Joystick extends StatefulWidget {
  final void Function(Offset) onMove;
  const Joystick({super.key, required this.onMove});
  @override
  State<Joystick> createState() => _JoystickState();
}

class _JoystickState extends State<Joystick> {
  Offset pos = Offset.zero;

  void _update(Offset local, Size size) {
    final dx = (local.dx / size.width).clamp(0.0, 1.0);
    final dy = (local.dy / size.height).clamp(0.0, 1.0);
    final centered = Offset((dx * 2 - 1), (1 - dy) * 2 - 1);
    setState(() => pos = centered);
    widget.onMove(centered);
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onPanDown: (e) => _update(e.localPosition, context.size!),
      onPanUpdate: (e) => _update(e.localPosition, context.size!),
      onPanEnd: (_) => setState(() => pos = Offset.zero),
      child: Container(
          height: 180,
          decoration: BoxDecoration(
              color: Colors.grey.shade100, borderRadius: BorderRadius.circular(12)),
          child: Stack(children: [
            Positioned(
                left: (pos.dx + 1) / 2 * (MediaQuery.of(context).size.width * 0.4 - 40) + 20,
                top: (1 - (pos.dy + 1) / 2) * (180 - 40),
                child: Container(
                    width: 40,
                    height: 40,
                    decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(20),
                        boxShadow: [BoxShadow(blurRadius: 6, color: Colors.black12)]))),
            Center(
                child: Text('x: ${pos.dx.toStringAsFixed(2)}, y: ${pos.dy.toStringAsFixed(2)}'))
          ])),
    );
  }
}
