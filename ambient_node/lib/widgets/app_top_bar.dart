import 'dart:io';
import 'package:flutter/material.dart';

/// 모든 화면에서 공통으로 사용하는 상단바 위젯
class AppTopBar extends StatelessWidget {
  final String deviceName;
  final String subtitle;
  final bool connected;
  final VoidCallback onConnectToggle;
  final String? userImagePath; // 선택된 사용자의 이미지 경로

  const AppTopBar({
    super.key,
    required this.deviceName,
    required this.subtitle,
    required this.connected,
    required this.onConnectToggle,
    this.userImagePath,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            children: [
              Container(
                width: 45,
                height: 45,
                decoration: const BoxDecoration(
                  color: Color(0xFFECF0F4),
                  shape: BoxShape.circle,
                ),
                child: ClipOval(
                  child: userImagePath != null
                      ? Image.file(
                          File(userImagePath!),
                          fit: BoxFit.cover,
                          width: 45,
                          height: 45,
                          errorBuilder: (context, error, stackTrace) {
                            // 이미지 로드 실패 시 기본 아이콘 표시
                            return const Center(
                              child: Icon(Icons.toys, color: Color(0xFF3A91FF), size: 24),
                            );
                          },
                        )
                      : const Center(
                          child: Icon(Icons.toys, color: Color(0xFF3A91FF), size: 24),
                        ),
                ),
              ),
              const SizedBox(width: 12),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    deviceName,
                    style: const TextStyle(
                      color: Color(0xFF1F2024),
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      fontFamily: 'Sen',
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    subtitle,
                    style: const TextStyle(
                      color: Color(0xFF676767),
                      fontSize: 12,
                      fontWeight: FontWeight.w400,
                      fontFamily: 'Sen',
                    ),
                  ),
                ],
              ),
            ],
          ),
          Row(
            children: [
              IconButton(
                icon: const Icon(Icons.bluetooth, color: Color(0xFF3A91FF)),
                onPressed: onConnectToggle,
              ),
              Switch(
                value: connected,
                onChanged: (_) => onConnectToggle(),
                activeColor: const Color(0xFF3A91FF),
                activeTrackColor: const Color(0xFF3A91FF).withOpacity(0.35),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
