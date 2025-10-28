import 'dart:io';
import 'dart:convert';

/// 이미지 파일을 Base64 문자열로 인코딩하는 헬퍼 함수
/// BLE를 통해 라즈베리파이로 전송할 때 사용
class ImageHelper {
  /// 이미지 파일을 Base64로 인코딩
  ///
  /// 사용 예시:
  /// ```dart
  /// final base64Image = await ImageHelper.encodeImageToBase64('/path/to/image.jpg');
  /// ble.sendJson({
  ///   'action': 'register_user',
  ///   'name': 'John Doe',
  ///   'image': base64Image,
  /// });
  /// ```
  static Future<String?> encodeImageToBase64(String imagePath) async {
    try {
      final file = File(imagePath);
      if (!await file.exists()) {
        return null;
      }

      final bytes = await file.readAsBytes();
      return base64Encode(bytes);
    } catch (e) {
      print('이미지 인코딩 실패: $e');
      return null;
    }
  }

  /// Base64 문자열을 이미지 파일로 디코딩
  ///
  /// 사용 예시:
  /// ```dart
  /// await ImageHelper.decodeBase64ToImage(base64String, '/path/to/save/image.jpg');
  /// ```
  static Future<bool> decodeBase64ToImage(
    String base64String,
    String savePath,
  ) async {
    try {
      final bytes = base64Decode(base64String);
      final file = File(savePath);
      await file.writeAsBytes(bytes);
      return true;
    } catch (e) {
      print('이미지 디코딩 실패: $e');
      return false;
    }
  }

  /// 이미지 크기를 조정하여 Base64로 인코딩 (BLE 전송 최적화)
  /// maxWidth, maxHeight로 크기 제한
  ///
  /// TODO: image 패키지를 추가하여 구현
  /// pubspec.yaml에 image: ^4.0.0 추가 필요
  static Future<String?> encodeImageToBase64WithResize(
    String imagePath, {
    int maxWidth = 800,
    int maxHeight = 800,
    int quality = 85,
  }) async {
    // TODO: 이미지 리사이징 후 Base64 인코딩
    // 현재는 리사이징 없이 인코딩만 수행
    return encodeImageToBase64(imagePath);
  }
}
