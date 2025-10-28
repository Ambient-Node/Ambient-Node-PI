import 'dart:io';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:ambient_node/widgets/app_top_bar.dart';
import 'package:ambient_node/widgets/remote_control_dpad.dart';
import 'package:ambient_node/screens/user_registration_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ControlScreen extends StatefulWidget {
  final bool connected;
  final String deviceName;
  final VoidCallback onConnect;
  final String? selectedUserName;
  final Function(String?, String?) onUserSelectionChanged; // (name, imagePath)
  final Function(Map<String, dynamic>)? onUserDataSend; // BLE 전송용 콜백

  const ControlScreen({
    super.key,
    required this.connected,
    required this.deviceName,
    required this.onConnect,
    this.selectedUserName,
    required this.onUserSelectionChanged,
    this.onUserDataSend,
  });

  @override
  State<ControlScreen> createState() => _ControlScreenState();
}

class _ControlScreenState extends State<ControlScreen> {
  List<UserProfile> users = [];
  int? selectedUserIndex;

  @override
  void initState() {
    super.initState();
    _loadUsers();
  }

  // 사용자 목록 불러오기
  Future<void> _loadUsers() async {
    final prefs = await SharedPreferences.getInstance();
    final usersJson = prefs.getStringList('users') ?? [];
    setState(() {
      users = usersJson
          .map((userStr) => UserProfile.fromJson(jsonDecode(userStr)))
          .toList();
    });
  }

  // 사용자 목록 저장하기
  Future<void> _saveUsers() async {
    final prefs = await SharedPreferences.getInstance();
    final usersJson = users.map((user) => jsonEncode(user.toJson())).toList();
    await prefs.setStringList('users', usersJson);
  }

  Future<void> _addUser() async {
    final result = await Navigator.push<Map<String, dynamic>>(
      context,
      MaterialPageRoute(
        builder: (context) => const UserRegistrationScreen(),
      ),
    );

    if (result != null && result['action'] == 'register') {
      final newUser = UserProfile(
        name: result['name']!,
        imagePath: result['imagePath'],
      );

      setState(() {
        users.add(newUser);
      });
      await _saveUsers();

      // BLE로 사용자 데이터 전송
      // TODO: 실제 구현 시 ImageHelper.encodeImageToBase64() 사용하여
      //       이미지를 Base64로 인코딩한 후 전송
      // 예시:
      // final base64Image = await ImageHelper.encodeImageToBase64(result['imagePath']);
      // widget.onUserDataSend?.call({
      //   'action': 'register_user',
      //   'name': result['name']!,
      //   'image_base64': base64Image,
      //   'timestamp': DateTime.now().toIso8601String(),
      // });

      widget.onUserDataSend?.call({
        'action': 'register_user',
        'name': result['name']!,
        'imagePath': result['imagePath'], // 테스트용 - 실제로는 Base64 전송
        'timestamp': DateTime.now().toIso8601String(),
      });
    }
  }

  Future<void> _editUser(int index) async {
    final user = users[index];
    final result = await Navigator.push<Map<String, dynamic>>(
      context,
      MaterialPageRoute(
        builder: (context) => UserRegistrationScreen(
          existingName: user.name,
          existingImagePath: user.imagePath,
          isEditMode: true,
        ),
      ),
    );

    if (result != null) {
      if (result['action'] == 'register') {
        final updatedUser = UserProfile(
          name: result['name']!,
          imagePath: result['imagePath'],
        );

        setState(() {
          users[index] = updatedUser;
        });
        await _saveUsers();

        // BLE로 사용자 수정 데이터 전송 (나중에 구현)
        widget.onUserDataSend?.call({
          'action': 'update_user',
          'index': index,
          'name': result['name']!,
          'imagePath': result['imagePath'],
          'timestamp': DateTime.now().toIso8601String(),
        });
      } else if (result['action'] == 'delete') {
        // BLE로 사용자 삭제 알림 (나중에 구현)
        widget.onUserDataSend?.call({
          'action': 'delete_user',
          'index': index,
          'name': users[index].name,
          'timestamp': DateTime.now().toIso8601String(),
        });
        _deleteUser(index);
      }
    }
  }

  Future<void> _deleteUser(int index) async {
    setState(() {
      if (selectedUserIndex == index) {
        selectedUserIndex = null;
        widget.onUserSelectionChanged(null, null);
      } else if (selectedUserIndex != null && selectedUserIndex! > index) {
        selectedUserIndex = selectedUserIndex! - 1;
      }
      users.removeAt(index);
    });
    await _saveUsers();
  }

  void _selectUser(int index) {
    setState(() {
      selectedUserIndex = (selectedUserIndex == index) ? null : index;
      // 부모 위젯(MainShell)에 선택된 사용자 이름과 이미지 경로 전달
      if (selectedUserIndex != null) {
        widget.onUserSelectionChanged(
          users[selectedUserIndex!].name,
          users[selectedUserIndex!].imagePath,
        );
      } else {
        widget.onUserSelectionChanged(null, null);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF6F7F8),
      body: SafeArea(
        child: Column(
          children: [
            // 공통 상단바
            AppTopBar(
              deviceName: widget.deviceName,
              subtitle: selectedUserIndex != null
                  ? '${users[selectedUserIndex!].name} 선택 중'
                  : 'Lab Fan',
              connected: widget.connected,
              onConnectToggle: widget.onConnect,
              userImagePath: selectedUserIndex != null
                  ? users[selectedUserIndex!].imagePath
                  : null,
            ),

            const SizedBox(height: 16),

            // 편집 버튼
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: selectedUserIndex != null
                      ? () => _editUser(selectedUserIndex!)
                      : null,
                  icon: Icon(
                    Icons.edit_outlined,
                    size: 18,
                    color: selectedUserIndex != null
                        ? const Color(0xFF3A90FF)
                        : Colors.grey,
                  ),
                  label: Text(
                    '편집',
                    style: TextStyle(
                      fontFamily: 'Sen',
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: selectedUserIndex != null
                          ? const Color(0xFF3A90FF)
                          : Colors.grey,
                    ),
                  ),
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 6,
                    ),
                    backgroundColor: selectedUserIndex != null
                        ? const Color(0xFF3A90FF).withOpacity(0.1)
                        : Colors.grey.withOpacity(0.1),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                ),
              ),
            ),

            const SizedBox(height: 12),

            // 사용자 프로필 가로 스크롤
            SizedBox(
              height: 110,
              child: ListView.builder(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 24),
                itemCount: users.length + 1, // +1 for add button
                itemBuilder: (context, index) {
                  if (index == 0) {
                    // 첫 번째: 사용자 추가 버튼
                    return _AddUserCard(onTap: _addUser);
                  }
                  final userIndex = index - 1;
                  return _UserCard(
                    user: users[userIndex],
                    isSelected: selectedUserIndex == userIndex,
                    onTap: () => _selectUser(userIndex),
                  );
                },
              ),
            ),

            const SizedBox(height: 40),

            // 리모콘
            Expanded(
              child: Center(
                child: RemoteControlDpad(
                  size: 280,
                  onUp: () => _sendCommand('up'),
                  onDown: () => _sendCommand('down'),
                  onLeft: () => _sendCommand('left'),
                  onRight: () => _sendCommand('right'),
                  onCenter: () => _sendCommand('center'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _sendCommand(String direction) {
    // 수동 조작이므로 사용자 선택 여부와 관계없이 작동
    if (selectedUserIndex != null) {
      print('🎮 수동 제어: $direction (사용자: ${users[selectedUserIndex!].name})');
    } else {
      print('🎮 수동 제어: $direction (사용자 선택 없음)');
    }
    // TODO: BLE 명령 전송 로직
    // 실제 구현 시:
    // widget.onUserDataSend?.call({
    //   'action': 'manual_control',
    //   'direction': direction,
    //   'user': selectedUserIndex != null ? users[selectedUserIndex!].name : null,
    //   'timestamp': DateTime.now().toIso8601String(),
    // });
  }
}

class UserProfile {
  final String name;
  final String? avatarUrl;
  final String? imagePath;

  UserProfile({
    required this.name,
    this.avatarUrl,
    this.imagePath,
  });

  // JSON 직렬화
  Map<String, dynamic> toJson() => {
        'name': name,
        'avatarUrl': avatarUrl,
        'imagePath': imagePath,
      };

  // JSON 역직렬화
  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
        name: json['name'] as String,
        avatarUrl: json['avatarUrl'] as String?,
        imagePath: json['imagePath'] as String?,
      );
}

class _AddUserCard extends StatelessWidget {
  final VoidCallback onTap;

  const _AddUserCard({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 90,
        height: 90,
        margin: const EdgeInsets.only(right: 10),
        padding: const EdgeInsets.all(15),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(15),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.05),
              blurRadius: 10,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 50,
              height: 50,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: const Color(0xFF437EFF).withOpacity(0.1),
              ),
              child: const Icon(
                Icons.add,
                color: Color(0xFF437EFF),
                size: 30,
              ),
            ),
            const SizedBox(height: 4),
            const Text(
              '추가',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: Color(0xFF282840),
                fontFamily: 'Sen',
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _UserCard extends StatelessWidget {
  final UserProfile user;
  final bool isSelected;
  final VoidCallback onTap;

  const _UserCard({
    required this.user,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 90,
        height: 90,
        margin: const EdgeInsets.only(right: 10),
        padding: const EdgeInsets.all(15),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(15),
          border: isSelected
              ? Border.all(color: const Color(0xFF437EFF), width: 3)
              : null,
          boxShadow: [
            BoxShadow(
              color: isSelected
                  ? const Color(0xFF437EFF).withOpacity(0.2)
                  : Colors.black.withOpacity(0.05),
              blurRadius: 10,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 50,
              height: 50,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: const Color(0xFFECF0F4),
              ),
              child: ClipOval(
                child: user.imagePath != null
                    ? Image.file(
                        File(user.imagePath!),
                        fit: BoxFit.cover,
                        width: 50,
                        height: 50,
                      )
                    : user.avatarUrl != null
                        ? Image.network(
                            user.avatarUrl!,
                            fit: BoxFit.cover,
                            width: 50,
                            height: 50,
                          )
                        : Icon(
                            Icons.person,
                            size: 30,
                            color: Colors.grey.shade400,
                          ),
              ),
            ),
            const SizedBox(height: 4),
            Text(
              user.name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: Color(0xFF282840),
                fontFamily: 'Sen',
              ),
            ),
          ],
        ),
      ),
    );
  }
}
