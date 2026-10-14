import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:travel_mate/data/api/api_client.dart';
import 'package:travel_mate/services/auth_service.dart';
import 'package:travel_mate/services/scene_image_service.dart';

class _RecordingClient extends http.BaseClient {
  http.BaseRequest? request;
  int responseStatus = 200;
  bool recognized = false;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    this.request = request;
    final body = responseStatus != 200
        ? '{"error":{"code":"INVALID_IMAGE"}}'
        : recognized
        ? '{"recognized":true,"primary_candidate":{"place_name":"성산일출봉","city":"서귀포시","region":"제주특별자치도"},"candidates":[{"place_name":"성산일출봉"},{"place_name":"섭지코지"}],"place_verified":true,"verified_place":{"place_name":"성산일출봉","road_address":"제주 서귀포시 성산읍","latitude":33.458,"longitude":126.942}}'
        : '{"recognized":false,"primary_candidate":null,"candidates":[],"place_verified":false}';
    return http.StreamedResponse(Stream.value(utf8.encode(body)), responseStatus);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await AuthSession.clear();
  });

  tearDown(AuthSession.clear);

  test('uploads the authenticated image and parses a verified result', () async {
    final client = _RecordingClient()..recognized = true;
    final service = SceneImageService(baseUrl: 'https://api.example', client: client);
    AuthSession.accessToken = 'access-token';

    final result = await service.analyze('test/services/scene_image_service_test.dart');

    final request = client.request! as http.MultipartRequest;
    expect(request.url.path, '/api/v1/discovery/scene-image');
    expect(request.headers['Authorization'], 'Bearer access-token');
    expect(request.fields['analyze'], 'true');
    expect(request.files.single.field, 'file');
    expect(result.placeName, '성산일출봉');
    expect(result.verified, isTrue);
    expect(result.latitude, 33.458);
    expect(result.otherCandidates, ['섭지코지']);
  });

  test('keeps an unrecognized result separate from an HTTP error', () async {
    final service = SceneImageService(baseUrl: 'https://api.example', client: _RecordingClient());
    AuthSession.accessToken = 'access-token';

    final result = await service.analyze('test/services/scene_image_service_test.dart');

    expect(result.recognized, isFalse);
    expect(result.verified, isFalse);
  });

  test('propagates API errors and does not upload without a session', () async {
    final failing = _RecordingClient()..responseStatus = 415;
    final service = SceneImageService(baseUrl: 'https://api.example', client: failing);
    AuthSession.accessToken = 'access-token';
    await expectLater(
      service.analyze('test/services/scene_image_service_test.dart'),
      throwsA(isA<ApiException>()),
    );

    AuthSession.clear();
    await expectLater(
      service.analyze('test/services/scene_image_service_test.dart'),
      throwsStateError,
    );
  });
}
