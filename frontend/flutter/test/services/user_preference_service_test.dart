import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:travel_mate/data/api/api_client.dart';
import 'package:travel_mate/services/auth_service.dart';
import 'package:travel_mate/services/user_preference_service.dart';

class _RecordingClient extends http.BaseClient {
  http.Request? request;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    this.request = request as http.Request;
    return http.StreamedResponse(Stream.value(utf8.encode('{}')), 200);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await AuthSession.clear();
  });

  tearDown(AuthSession.clear);

  test('saves sea and nature as separate interest codes', () async {
    final client = _RecordingClient();
    final service = UserPreferenceService(
      apiClient: ApiClient(baseUrl: 'https://api.example', client: client),
    );
    AuthSession.accessToken = 'access-token';

    await service.saveSetup(
      selectedInterests: {'바다', '자연'},
      travelStyle: '여유롭게',
      seniorMode: true,
    );

    final body = jsonDecode(client.request!.body) as Map<String, dynamic>;
    expect(body['interests'], ['NATURE', 'SEA']);
    expect(body['travel_style'], 'SLOW');
    expect(body['senior_mode'], isTrue);
  });
}
