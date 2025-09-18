import 'package:flutter/material.dart';
import '../models/face.dart';
import '../services/mock_ai_service.dart';
import '../widgets/joystick.dart';

class ControlScreen extends StatefulWidget {
  final MockAIService ai;
  final bool trackingOn;
  final void Function(bool) setTrackingOn;
  final String? selectedFaceId;
  final void Function(String?) selectFace;
  final void Function(Offset) manualMove;

  const ControlScreen(
      {super.key,
      required this.ai,
      required this.trackingOn,
      required this.setTrackingOn,
      required this.selectedFaceId,
      required this.selectFace,
      required this.manualMove});

  @override
  State<ControlScreen> createState() => _ControlScreenState();
}

class _ControlScreenState extends State<ControlScreen> {
  List<Face> faces = [];
  Offset? target;

  @override
  void initState() {
    super.initState();
    widget.ai.facesStream.listen((f) => setState(() => faces = f));
    widget.ai.targetStream.listen((t) => setState(() => target = t));
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(children: [
        Expanded(
            child: Row(children: [
          Expanded(
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('인식된 얼굴',
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                    const SizedBox(height: 12),
                    Expanded(
                      child: GridView.count(
                        crossAxisCount: 2,
                        childAspectRatio: 3,
                        children: faces.map((f) {
                          return GestureDetector(
                            onTap: () => widget.selectFace(f.id),
                            child: Container(
                              margin: const EdgeInsets.all(6),
                              padding: const EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(12),
                                border: Border.all(
                                  color: widget.selectedFaceId == f.id
                                      ? Colors.blue
                                      : Colors.grey.shade300,
                                ),
                                color: widget.selectedFaceId == f.id
                                    ? Colors.blue.shade50
                                    : null,
                              ),
                              child: Row(
                                children: [
                                  CircleAvatar(
                                      child: Text(f.name.split(' ').last)),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      mainAxisAlignment:
                                          MainAxisAlignment.center,
                                      children: [
                                        Text(f.name),
                                        Text(
                                          'conf: ${(f.confidence * 100).toStringAsFixed(0)}%',
                                          style: const TextStyle(
                                              fontSize: 12,
                                              color: Colors.black54),
                                        ),
                                      ],
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          );
                        }).toList(),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
              child: Card(
                  child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(children: [
                        Text('수동 조작 / 미리보기',
                            style: TextStyle(fontWeight: FontWeight.w600)),
                        const SizedBox(height: 12),
                        Expanded(
                            child: Column(children: [
                          Expanded(child: _CameraPreviewMock(target: target)),
                          const SizedBox(height: 12),
                          Joystick(onMove: (v) => widget.manualMove(v))
                        ]))
                      ]))))
        ]))
      ]),
    );
  }
}

class _CameraPreviewMock extends StatelessWidget {
  final Offset? target;
  const _CameraPreviewMock({this.target});
  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: 16 / 9,
      child: Stack(
        children: [
          Container(color: Colors.grey.shade100),
          Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: const [
                Icon(Icons.videocam, size: 48, color: Colors.grey),
                SizedBox(height: 6),
                Text('Camera preview (mock)',
                    style: TextStyle(color: Colors.grey)),
              ],
            ),
          ),
          if (target != null)
            Positioned(
              left: target!.dx * MediaQuery.of(context).size.width * 0.6,
              top: target!.dy * MediaQuery.of(context).size.height * 0.18,
              child: Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(24),
                  border: Border.all(color: Colors.blue),
                  color: Colors.blue.withValues(alpha: 0.14),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
