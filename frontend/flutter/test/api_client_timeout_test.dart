import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:travel_mate/data/api/api_client.dart';
import 'package:travel_mate/services/plan_service.dart';

void main() {
  test('a request slower than its timeout throws TimeoutException', () async {
    final client = MockClient((request) async {
      await Future<void>.delayed(const Duration(milliseconds: 200));
      return http.Response('{}', 200);
    });
    final api = ApiClient(baseUrl: 'https://timeout.test', client: client);

    expect(
      api.post('/slow', timeout: const Duration(milliseconds: 20)),
      throwsA(isA<TimeoutException>()),
    );
  });

  test('AI plan timeout covers four 180 second model calls', () {
    expect(planAiRequestTimeout, greaterThan(const Duration(seconds: 720)));
    expect(previewAiRequestTimeout, greaterThan(const Duration(seconds: 960)));
    expect(ApiClient.defaultTimeout, const Duration(seconds: 60));
  });

  test('timeout gets its own Korean message', () {
    expect(planErrorMessage(TimeoutException('slow')), contains('오래 걸려'));
  });
}
