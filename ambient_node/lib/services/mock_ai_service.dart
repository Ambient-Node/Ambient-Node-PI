import 'dart:async';
import 'dart:math';
import 'package:flutter/material.dart';
import '../models/face.dart';

class MockAIService {
  // emits a list of detected faces and (when target selected) normalized coordinates
  final _facesController = StreamController<List<Face>>.broadcast();
  final _targetController = StreamController<Offset?>.broadcast();
  Timer? _timer;
  String? _selectedId;

  Stream<List<Face>> get facesStream => _facesController.stream;
  Stream<Offset?> get targetStream => _targetController.stream;

  void start() {
    // initial faces
    final faces = List.generate(
        3,
        (i) => Face(
            id: 'f${i + 1}',
            name: 'Person ${i + 1}',
            confidence: 0.9 - i * 0.08));
    _facesController.add(faces);

    _timer = Timer.periodic(const Duration(milliseconds: 400), (_) {
      if (_selectedId == null) {
        _targetController.add(null);
      } else {
        final t = DateTime.now().millisecondsSinceEpoch / 1000.0;
        final x = 0.5 + 0.3 * sin(t / 1.7);
        final y = 0.5 + 0.25 * cos(t / 1.3);
        _targetController.add(Offset(x, y));
        // nudge confidences
        final updated = faces.map((f) {
          if (f.id == _selectedId) {
            return f.copyWith(confidence: min(0.99, f.confidence + 0.01));
          }
          return f.copyWith(confidence: max(0.6, f.confidence - 0.005));
        }).toList();
        _facesController.add(updated);
      }
    });
  }

  void select(String? id) {
    _selectedId = id;
  }

  void dispose() {
    _timer?.cancel();
    _facesController.close();
    _targetController.close();
  }
}
