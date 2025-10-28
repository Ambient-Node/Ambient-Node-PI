import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

class UserRegistrationScreen extends StatefulWidget {
  final String? existingName;
  final String? existingImagePath;
  final bool isEditMode;

  const UserRegistrationScreen({
    super.key,
    this.existingName,
    this.existingImagePath,
    this.isEditMode = false,
  });

  @override
  State<UserRegistrationScreen> createState() => _UserRegistrationScreenState();
}

class _UserRegistrationScreenState extends State<UserRegistrationScreen> {
  final TextEditingController _nameController = TextEditingController();
  final ImagePicker _picker = ImagePicker();
  XFile? _imageFile;

  @override
  void initState() {
    super.initState();
    if (widget.isEditMode) {
      _nameController.text = widget.existingName ?? '';
      if (widget.existingImagePath != null) {
        _imageFile = XFile(widget.existingImagePath!);
      }
    }
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  Future<void> _pickImageFromCamera() async {
    try {
      final XFile? image = await _picker.pickImage(
        source: ImageSource.camera,
        maxWidth: 800,
        maxHeight: 800,
        imageQuality: 85,
      );
      if (image != null) {
        setState(() {
          _imageFile = image;
        });
      }
    } catch (e) {
      _showErrorSnackBar('카메라 접근 권한이 필요합니다');
    }
  }

  Future<void> _pickImageFromGallery() async {
    try {
      final XFile? image = await _picker.pickImage(
        source: ImageSource.gallery,
        maxWidth: 800,
        maxHeight: 800,
        imageQuality: 85,
      );
      if (image != null) {
        setState(() {
          _imageFile = image;
        });
      }
    } catch (e) {
      _showErrorSnackBar('갤러리 접근 권한이 필요합니다');
    }
  }

  void _showImageSourceDialog() {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (context) => Container(
        decoration: const BoxDecoration(
          color: Color(0xFF2B2D42),
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        child: SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(height: 20),
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.3),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(height: 20),
              _buildImageSourceOption(
                icon: Icons.camera_alt_rounded,
                label: '카메라로 촬영',
                onTap: () {
                  Navigator.pop(context);
                  _pickImageFromCamera();
                },
              ),
              _buildImageSourceOption(
                icon: Icons.photo_library_rounded,
                label: '앨범에서 선택',
                onTap: () {
                  Navigator.pop(context);
                  _pickImageFromGallery();
                },
              ),
              const SizedBox(height: 20),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildImageSourceOption({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 24),
        child: Row(
          children: [
            Icon(icon, color: const Color(0xFF5AB0FF), size: 28),
            const SizedBox(width: 16),
            Text(
              label,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 16,
                fontFamily: 'Sen',
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _showErrorSnackBar(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.red.shade400,
        duration: const Duration(milliseconds: 1500), // 1.5초로 단축
      ),
    );
  }

  void _handleRegister() {
    if (_imageFile == null) {
      _showErrorSnackBar('얼굴 사진을 등록해주세요');
      return;
    }
    if (_nameController.text.trim().isEmpty) {
      _showErrorSnackBar('이름을 입력해주세요');
      return;
    }

    // 사용자 데이터를 반환하고 화면 닫기
    Navigator.pop(context, {
      'action': 'register',
      'name': _nameController.text.trim(),
      'imagePath': _imageFile!.path,
    });
  }

  void _handleDelete() {
    if (!widget.isEditMode) {
      _showErrorSnackBar('등록된 사용자가 아닙니다');
      return;
    }

    // 삭제 확인 다이얼로그
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF2B2D42),
        title: const Text(
          '사용자 삭제',
          style: TextStyle(color: Colors.white, fontFamily: 'Sen'),
        ),
        content: Text(
          '${widget.existingName}을(를) 삭제하시겠습니까?',
          style: const TextStyle(color: Colors.white70, fontFamily: 'Sen'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text(
              '취소',
              style: TextStyle(color: Color(0xFF5AB0FF), fontFamily: 'Sen'),
            ),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context); // 다이얼로그 닫기
              Navigator.pop(context, {'action': 'delete'}); // 등록 화면 닫기
            },
            child: const Text(
              '삭제',
              style: TextStyle(color: Colors.red, fontFamily: 'Sen'),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF2B2D42),
      body: SafeArea(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const SizedBox(height: 20),
                // 뒤로가기 버튼
                IconButton(
                  icon: const Icon(Icons.arrow_back_ios, color: Colors.white),
                  onPressed: () => Navigator.pop(context),
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(),
                ),
                const SizedBox(height: 60),

                // 제목
                const Text(
                  '사용자 등록',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 36,
                    fontFamily: 'Sen',
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 50),

                // 얼굴 사진 등록
                Center(
                  child: GestureDetector(
                    onTap: _showImageSourceDialog,
                    child: Stack(
                      children: [
                        Container(
                          width: 140,
                          height: 140,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: const Color(0xFF3D4054),
                            border: Border.all(
                              color: const Color(0xFF5AB0FF).withOpacity(0.3),
                              width: 3,
                            ),
                            boxShadow: [
                              BoxShadow(
                                color: Colors.black.withOpacity(0.3),
                                blurRadius: 15,
                                offset: const Offset(0, 5),
                              ),
                            ],
                          ),
                          child: _imageFile == null
                              ? Icon(
                                  Icons.person_outline,
                                  size: 60,
                                  color: Colors.white.withOpacity(0.3),
                                )
                              : ClipOval(
                                  child: Image.file(
                                    File(_imageFile!.path),
                                    fit: BoxFit.cover,
                                    width: 140,
                                    height: 140,
                                  ),
                                ),
                        ),
                        Positioned(
                          right: 0,
                          bottom: 0,
                          child: Container(
                            width: 40,
                            height: 40,
                            decoration: const BoxDecoration(
                              shape: BoxShape.circle,
                              color: Color(0xFF5AB0FF),
                            ),
                            child: const Icon(
                              Icons.camera_alt_rounded,
                              color: Colors.white,
                              size: 20,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 40),

                // 이름 입력
                const Text(
                  'Your Name',
                  style: TextStyle(
                    color: Color(0xFF9DA4B4),
                    fontSize: 14,
                    fontFamily: 'Sen',
                    fontWeight: FontWeight.w400,
                  ),
                ),
                const SizedBox(height: 10),
                Container(
                  decoration: BoxDecoration(
                    color: const Color(0xFF3D4054),
                    borderRadius: BorderRadius.circular(12),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withOpacity(0.2),
                        blurRadius: 10,
                        offset: const Offset(0, 3),
                      ),
                    ],
                  ),
                  child: TextField(
                    controller: _nameController,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontFamily: 'Sen',
                      fontWeight: FontWeight.w400,
                    ),
                    decoration: InputDecoration(
                      hintText: 'Enter your name',
                      hintStyle: TextStyle(
                        color: Colors.white.withOpacity(0.3),
                        fontFamily: 'Sen',
                      ),
                      prefixIcon: Icon(
                        Icons.person_outline,
                        color: const Color(0xFF5AB0FF).withOpacity(0.7),
                      ),
                      border: InputBorder.none,
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 20,
                        vertical: 18,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 60),

                // 등록 및 삭제 버튼
                Row(
                  children: [
                    // 등록 버튼
                    Expanded(
                      child: GestureDetector(
                        onTap: _handleRegister,
                        child: Container(
                          height: 60,
                          decoration: BoxDecoration(
                            gradient: const LinearGradient(
                              colors: [Color(0xFF5AB0FF), Color(0xFF3A90FF)],
                              begin: Alignment.topLeft,
                              end: Alignment.bottomRight,
                            ),
                            borderRadius: BorderRadius.circular(12),
                            boxShadow: [
                              BoxShadow(
                                color: const Color(0xFF3A90FF).withOpacity(0.4),
                                blurRadius: 15,
                                offset: const Offset(0, 5),
                              ),
                            ],
                          ),
                          child: const Center(
                            child: Text(
                              '등록',
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 16,
                                fontFamily: 'Sen',
                                fontWeight: FontWeight.w700,
                                letterSpacing: 1.2,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    // 삭제 버튼
                    Expanded(
                      child: GestureDetector(
                        onTap: _handleDelete,
                        child: Container(
                          height: 60,
                          decoration: BoxDecoration(
                            color: const Color(0xFF3D4054),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                              color: Colors.red.withOpacity(0.5),
                              width: 2,
                            ),
                            boxShadow: [
                              BoxShadow(
                                color: Colors.black.withOpacity(0.2),
                                blurRadius: 10,
                                offset: const Offset(0, 3),
                              ),
                            ],
                          ),
                          child: const Center(
                            child: Text(
                              '삭제',
                              style: TextStyle(
                                color: Colors.red,
                                fontSize: 16,
                                fontFamily: 'Sen',
                                fontWeight: FontWeight.w700,
                                letterSpacing: 1.2,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 30),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
