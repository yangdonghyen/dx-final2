import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'auth_service.dart';

/// 여행 만들기 화면에서 작성 중인 입력값을 이 기기에 임시 보관합니다.
///
/// 로그인한 계정마다 다른 키(`trip_draft_v1_<user>`)에 저장하므로 다른
/// 계정으로 로그인하면 이전 계정의 초안이 보이지 않습니다. 계정을 알 수
/// 없으면 저장하지도 읽지도 않습니다. 여행 생성이 끝나면 [clear]로 지웁니다.
class TripDraftStore {
  TripDraftStore._();

  static const _keyPrefix = 'trip_draft_v1_';
  static const _version = 1;
  static SharedPreferencesAsync _storage = SharedPreferencesAsync();

  @visibleForTesting
  static set storage(SharedPreferencesAsync value) => _storage = value;

  /// The account the draft belongs to: the `sub` claim of the stored access
  /// token (read only to separate storage, never trusted for authorization).
  @visibleForTesting
  static String? ownerOf(String? accessToken) {
    final parts = accessToken?.split('.');
    if (parts == null || parts.length != 3) return null;
    try {
      final payload = jsonDecode(
        utf8.decode(base64Url.decode(base64Url.normalize(parts[1]))),
      );
      final subject = payload is Map ? payload['sub']?.toString() : null;
      return subject == null || subject.isEmpty ? null : subject;
    } catch (_) {
      return null;
    }
  }

  static String? get _key {
    final owner = ownerOf(AuthSession.accessToken);
    return owner == null ? null : '$_keyPrefix$owner';
  }

  static Future<Map<String, dynamic>?> load() async {
    final key = _key;
    if (key == null) return null;
    try {
      final raw = await _storage.getString(key);
      if (raw == null) return null;
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic> || decoded['version'] != _version) {
        return null;
      }
      return decoded;
    } catch (error) {
      debugPrint('[TripDraft] load failed: $error');
      return null;
    }
  }

  static Future<void> save(Map<String, dynamic> draft) async {
    final key = _key;
    if (key == null) return;
    try {
      await _storage.setString(key, jsonEncode({...draft, 'version': _version}));
    } catch (error) {
      debugPrint('[TripDraft] save failed: $error');
    }
  }

  static Future<void> clear() async {
    final key = _key;
    if (key == null) return;
    try {
      await _storage.remove(key);
    } catch (error) {
      debugPrint('[TripDraft] clear failed: $error');
    }
  }
}
