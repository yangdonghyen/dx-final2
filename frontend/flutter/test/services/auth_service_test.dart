import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:travel_mate/data/api/api_client.dart';
import 'package:travel_mate/services/auth_service.dart';

class _AuthClient extends http.BaseClient {
  _AuthClient(this.statusCode, this.body);
  final int statusCode;
  final String body;
  http.BaseRequest? request;
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    this.request = request;
    return http.StreamedResponse(Stream.value(utf8.encode(body)), statusCode);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const naverChannel = MethodChannel('travelmate/naver_auth');

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await AuthSession.clear();
  });

  tearDown(() async {
    await AuthSession.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(naverChannel, null);
  });

  test('local login stores the backend JWT in AuthSession', () async {
    final client = _AuthClient(
      200,
      '{"access_token":"access","refresh_token":"refresh","user":{"profile_completed":false}}',
    );
    final service = AuthService(
      apiClient: ApiClient(baseUrl: 'https://api.example', client: client),
    );

    await service.loginLocal('local.user', 'correct-password');
    expect(client.request!.url.path, '/api/v1/auth/login');
    expect(AuthSession.accessToken, 'access');
    expect(AuthSession.refreshToken, 'refresh');
  });

  test('local login failure does not create an AuthSession', () async {
    final client = _AuthClient(401, '{"error":{"code":"INVALID_CREDENTIALS"}}');
    final service = AuthService(
      apiClient: ApiClient(baseUrl: 'https://api.example', client: client),
    );

    await expectLater(
      service.loginLocal('local.user', 'wrong-password'),
      throwsA(isA<ApiException>()),
    );
    expect(AuthSession.isLoggedIn, isFalse);
  });

  test('native NAVER token is sent to backend and stores JWT', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(naverChannel, (call) async {
          expect(call.method, 'login');
          return 'native-naver-token';
        });
    final client = _AuthClient(
      200,
      '{"access_token":"access","refresh_token":"refresh","user":{"profile_completed":true}}',
    );
    final service = AuthService(
      apiClient: ApiClient(baseUrl: 'https://api.example', client: client),
      naverChannel: naverChannel,
      naverIdentifier: (_) async => null,
    );

    await service.loginWithNaver();
    expect(client.request!.url.path, '/api/v1/auth/naver/token-login');
    expect(
      (client.request! as http.Request).body,
      contains('native-naver-token'),
    );
    expect(AuthSession.accessToken, 'access');
  });

  test('native NAVER failure does not create an AuthSession', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(naverChannel, (_) async {
          throw PlatformException(code: 'NAVER_LOGIN_CANCELLED');
        });
    final service = AuthService(naverChannel: naverChannel);

    await expectLater(
      service.loginWithNaver(),
      throwsA(isA<PlatformException>()),
    );
    expect(AuthSession.isLoggedIn, isFalse);
  });
}
