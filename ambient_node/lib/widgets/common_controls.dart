import 'package:flutter/material.dart';

class ControlCard extends StatelessWidget {
  final String title;
  final Widget child;
  const ControlCard({super.key, required this.title, required this.child});
  @override
  Widget build(BuildContext context) => Card(
      child: Padding(
          padding: const EdgeInsets.all(8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: const TextStyle(fontSize: 12, color: Colors.black54)),
            const SizedBox(height: 6),
            child
          ])));
}

class StatTile extends StatelessWidget {
  final String title;
  final String value;
  const StatTile({super.key, required this.title, required this.value});
  @override
  Widget build(BuildContext context) => Card(
      child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Text(title, style: const TextStyle(color: Colors.black54)),
            Text(value, style: const TextStyle(fontWeight: FontWeight.w600))
          ])));
}
