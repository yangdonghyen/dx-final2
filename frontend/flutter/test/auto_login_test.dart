import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:travel_mate/data/api/api_client.dart';
import 'package:travel_mate/services/auth_service.dart';

AuthService _service(List<String> bodies, {int status = 200}) => AuthService(
  apiClient: ApiClient(
    baseUrl: 'https://auth.test',
    client: MockClient((request) async {
      bodies.add('${request.url.path} ${request.body}');
      return http.Response(
        jsonEncode(status == 200
            ? {'access_token': 'new-access', 'refresh_token': 'new-refresh', 'token_type': 'bearer'}
            : {'error': {'code': 'INVALID_TOKEN', 'message': 'x'}}),
        status,
      );
    }),
  ),
);

void main() {
  test('auto login trades the saved refresh token for a new session', () async {
    SharedPreferences.setMockInitialValues({
      'auth_access_token': 'old-access',
      'auth_refresh_token': 'old-refresh',
      'auth_auto_login': true,
    });
    await AuthSession.restore();
    final bodies = <String>[];

    expect(await _service(bodies).resumeSession(), isTrue);
    expect(bodies.single, '/api/v1/auth/refresh {"refresh_token":"old-refresh"}');
    expect((AuthSession.accessToken, AuthSession.refreshToken), ('new-access', 'new-refresh'));
  });

  test('without the checkbox, or with an expired token, the login screen stays', () async {
    SharedPreferences.setMockInitialValues({'auth_refresh_token': 'old-refresh'});
    await AuthSession.restore();
    final bodies = <String>[];
    expect(await _service(bodies).resumeSession(), isFalse);
    expect(bodies, isEmpty); // not even asked

    SharedPreferences.setMockInitialValues({'auth_refresh_token': 'old-refresh', 'auth_auto_login': true});
    await AuthSession.restore();
    expect(await _service(bodies, status: 401).resumeSession(), isFalse);

    await AuthSession.clear();
    expect(AuthSession.autoLogin, isFalse); // logout turns it off
  });
}
