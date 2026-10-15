import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:travel_mate/data/api/api_client.dart';

void main() {
  tearDown(() => ApiClient.refreshAccessToken = null);

  test('a 401 renews the expired access token once and retries', () async {
    final seen = <String?>[];
    var refreshes = 0;
    ApiClient.refreshAccessToken = () async {
      refreshes++;
      return 'fresh';
    };
    final client = ApiClient(
      baseUrl: 'https://api.test',
      client: MockClient((request) async {
        seen.add(request.headers['Authorization']);
        return request.headers['Authorization'] == 'Bearer fresh'
            ? http.Response('{"ok": true}', 200)
            : http.Response('{"error": {"code": "INVALID_TOKEN"}}', 401);
      }),
    );

    final results = await Future.wait([
      client.get('/api/v1/trips', accessToken: 'expired'),
      client.get('/api/v1/weather', accessToken: 'expired'),
    ]);

    expect(results.every((body) => body['ok'] == true), isTrue);
    expect(refreshes, 1); // one shared refresh for concurrent calls
    expect(seen.where((value) => value == 'Bearer fresh'), hasLength(2));
  });

  test('without a refresh (or when it fails) the 401 is reported as before', () async {
    ApiClient.refreshAccessToken = () async => null;
    final client = ApiClient(
      baseUrl: 'https://api.test',
      client: MockClient((_) async => http.Response('{"error": {"code": "INVALID_TOKEN"}}', 401)),
    );
    expect(
      () => client.get('/api/v1/trips', accessToken: 'expired'),
      throwsA(isA<ApiException>().having((error) => error.statusCode, 'status', 401)),
    );
  });
}
