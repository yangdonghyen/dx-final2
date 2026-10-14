import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:kakao_flutter_sdk_user/kakao_flutter_sdk_user.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../data/api/api_client.dart';
import 'active_trip_service.dart';

class AuthSession {
  AuthSession._();

  static const _accessTokenKey = 'auth_access_token';
  static const _refreshTokenKey = 'auth_refresh_token';
  static const _displayNameKey = 'auth_display_name';
  static const _autoLoginKey = 'auth_auto_login';

  /// "자동 로그인" was checked at the last login: the app opens Home on start.
  static bool autoLogin = false;

  static Future<void> setAutoLogin(bool value) async {
    autoLogin = value;
    final preferences = await SharedPreferences.getInstance();
    await preferences.setBool(_autoLoginKey, value);
  }

  static String? accessToken;
  static String? refreshToken;

  /// Who is logged in: the Kakao/Naver account email (or account ID when the
  /// email is not shared) for social login, users.nickname for local login.
  static String? displayName;

  static bool get isLoggedIn => accessToken != null;

  /// Full identifier for the profile; empty when it is not known yet.
  static String get displayLabel => displayName?.trim() ?? '';

  /// Short form for greetings: an email shows only the part before '@'.
  static String get shortLabel {
    final label = displayLabel;
    final at = label.indexOf('@');
    return at > 0 ? label.substring(0, at) : label;
  }

  static String get greeting =>
      shortLabel.isEmpty ? '안녕하세요' : '안녕하세요, $shortLabel님';

  /// Profile title: an email as is, a name with '님'.
  static String get profileTitle {
    final label = displayLabel;
    if (label.isEmpty) return '내 계정';
    return label.contains('@') ? label : '$label님';
  }

  static Future<void> setDisplayName(String name) async {
    displayName = name;
    await _storeDisplayName(await SharedPreferences.getInstance(), name);
  }

  /// Restores the application's existing session for a background isolate.
  ///
  /// The same [AuthSession] storage is used by foreground and background work;
  /// no second copy of the access token is maintained for weather checks.
  static Future<void> restore() async {
    final preferences = await SharedPreferences.getInstance();
    accessToken = preferences.getString(_accessTokenKey);
    refreshToken = preferences.getString(_refreshTokenKey);
    displayName = preferences.getString(_displayNameKey);
    autoLogin = preferences.getBool(_autoLoginKey) ?? false;
  }

  static Future<void> store({
    required String accessToken,
    String? refreshToken,
    String? displayName,
  }) async {
    AuthSession.accessToken = accessToken;
    AuthSession.refreshToken = refreshToken;
    AuthSession.displayName = displayName;

    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(_accessTokenKey, accessToken);
    if (refreshToken == null || refreshToken.isEmpty) {
      await preferences.remove(_refreshTokenKey);
    } else {
      await preferences.setString(_refreshTokenKey, refreshToken);
    }
    await _storeDisplayName(preferences, displayName);
  }

  static Future<void> _storeDisplayName(
    SharedPreferences preferences,
    String? name,
  ) async {
    if (name == null || name.trim().isEmpty) {
      await preferences.remove(_displayNameKey);
    } else {
      await preferences.setString(_displayNameKey, name);
    }
  }

  /// Sessions saved before the name was stored have no name; load it once
  /// from GET /api/v1/users/me.
  static Future<void> loadDisplayNameIfMissing() async {
    final token = accessToken;
    if (token == null || displayName != null) return;
    try {
      final response = await ApiClient().get(
        '/api/v1/users/me',
        accessToken: token,
      );
      final nickname = response['nickname'];
      displayName = nickname is String ? nickname : '';
      final preferences = await SharedPreferences.getInstance();
      await _storeDisplayName(preferences, displayName);
    } catch (_) {
      // Keep the neutral label; the next login stores the name.
    }
  }

  static Future<void> clear() async {
    accessToken = null;
    refreshToken = null;
    displayName = null;
    autoLogin = false;
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_autoLoginKey);
    await preferences.remove(_accessTokenKey);
    await preferences.remove(_refreshTokenKey);
    await preferences.remove(_displayNameKey);
    await ActiveTripService.clear();
  }
}

class AuthService {
  AuthService({
    ApiClient? apiClient,
    MethodChannel? naverChannel,
    Future<String?> Function(String accessToken)? naverIdentifier,
  })
    : _apiClient = apiClient ?? ApiClient(),
      _naverChannel =
          naverChannel ?? const MethodChannel('travelmate/naver_auth'),
      _naverIdentifierOverride = naverIdentifier;

  final ApiClient _apiClient;
  final MethodChannel _naverChannel;
  final Future<String?> Function(String accessToken)? _naverIdentifierOverride;

  Future<void> _storeTokens(Map<String, dynamic> response) async {
    final accessToken = response['access_token'];
    if (accessToken is! String || accessToken.isEmpty) {
      throw const FormatException(
        'Login response does not contain access_token.',
      );
    }

    final refreshToken = response['refresh_token'];
    final user = response['user'];
    final nickname = user is Map<String, dynamic> ? user['nickname'] : null;
    await AuthSession.store(
      accessToken: accessToken,
      refreshToken: refreshToken is String && refreshToken.isNotEmpty
          ? refreshToken
          : null,
      displayName: nickname is String ? nickname : null,
    );
  }

  /// Auto login: trades the saved refresh token for a fresh access token.
  /// Returns false (and keeps the user on the login screen) when it fails.
  Future<bool> resumeSession() async {
    final refresh = AuthSession.refreshToken;
    if (!AuthSession.autoLogin || refresh == null || refresh.isEmpty) return false;
    try {
      final response = await _apiClient.post(
        '/api/v1/auth/refresh',
        body: {'refresh_token': refresh},
      );
      final access = response['access_token'];
      final rotated = response['refresh_token'];
      if (access is! String || access.isEmpty) return false;
      await AuthSession.store(
        accessToken: access,
        refreshToken: rotated is String && rotated.isNotEmpty ? rotated : refresh,
        displayName: AuthSession.displayName,
      );
      return true;
    } catch (error) {
      debugPrint('[Auth] auto login failed: $error');
      return false;
    }
  }

  Future<void> registerLocal(
    String loginId,
    String password,
    String nickname,
  ) async {
    final response = await _apiClient.post(
      '/api/v1/auth/register',
      body: {
        'login_id': loginId.trim(),
        'password': password,
        'nickname': nickname.trim(),
      },
    );

    await _storeTokens(response);
  }

  Future<void> loginLocal(String loginId, String password) async {
    final response = await _apiClient.post(
      '/api/v1/auth/login',
      body: {'login_id': loginId.trim(), 'password': password},
    );

    await _storeTokens(response);
  }

  Future<void> loginWithKakao() async {
    OAuthToken kakaoToken;

    if (await isKakaoTalkInstalled()) {
      try {
        kakaoToken = await UserApi.instance.loginWithKakaoTalk();
      } on PlatformException catch (error) {
        if (error.code == 'CANCELED') {
          rethrow;
        }

        kakaoToken = await UserApi.instance.loginWithKakaoAccount();
      } catch (_) {
        kakaoToken = await UserApi.instance.loginWithKakaoAccount();
      }
    } else {
      kakaoToken = await UserApi.instance.loginWithKakaoAccount();
    }

    final response = await _apiClient.post(
      '/api/v1/auth/social-login',
      body: {'provider': 'KAKAO', 'access_token': kakaoToken.accessToken},
    );

    await _storeTokens(response);
    try {
      final user = await UserApi.instance.me();
      final email = user.kakaoAccount?.email;
      await AuthSession.setDisplayName(
        email != null && email.isNotEmpty ? email : user.id.toString(),
      );
    } catch (error) {
      // Keep the server nickname when Kakao does not return the account.
      debugPrint('[Auth] Kakao account lookup failed: $error');
    }
  }

  Future<void> loginWithNaver() async {
    final naverAccessToken = await _naverChannel.invokeMethod<String>('login');
    if (naverAccessToken == null || naverAccessToken.isEmpty) {
      throw PlatformException(code: 'NAVER_ACCESS_TOKEN_MISSING');
    }
    final response = await _apiClient.post(
      '/api/v1/auth/naver/token-login',
      body: {'access_token': naverAccessToken},
    );
    await _storeTokens(response);
    try {
      final identifier = await (_naverIdentifierOverride?.call(naverAccessToken) ??
          _naverIdentifier(naverAccessToken));
      if (identifier != null) await AuthSession.setDisplayName(identifier);
    } catch (error) {
      // Keep the server nickname when Naver does not return the profile.
      debugPrint('[Auth] Naver profile lookup failed: $error');
    }
  }

  /// Naver account email, or the Naver account ID when no email is shared.
  Future<String?> _naverIdentifier(String accessToken) async {
    final result = await http.get(
      Uri.parse('https://openapi.naver.com/v1/nid/me'),
      headers: {'Authorization': 'Bearer $accessToken'},
    );
    if (result.statusCode != 200) return null;
    final body = jsonDecode(result.body);
    final profile = body is Map<String, dynamic> ? body['response'] : null;
    if (profile is! Map<String, dynamic>) return null;
    for (final key in ['email', 'id']) {
      final value = profile[key];
      if (value is String && value.isNotEmpty) return value;
    }
    return null;
  }
}
