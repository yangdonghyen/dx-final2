import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:travel_mate/data/api/api_client.dart';
import 'package:travel_mate/services/auth_service.dart';
import 'package:travel_mate/services/plan_service.dart';

Map<String, dynamic> planJson(int planId) => {
  'plan_id': planId,
  'status': 'DRAFT',
  'current_version': 1,
  'validation_status': 'VALID',
  'warnings': <String>[],
  'days': [
    {
      'day': 1,
      'visit_date': '2026-10-29',
      'items': [
        {
          'item_id': 1,
          'place_id': 5,
          'name': '광안리해수욕장',
          'start_time': '09:00:00',
          'end_time': '11:00:00',
          'validation_status': 'UNKNOWN',
          'item_type': 'PLACE',
        },
      ],
    },
  ],
};

http.Response error(int status, String code, [Map<String, Object>? details]) =>
    http.Response(
      jsonEncode({
        'error': {'code': code, 'message': code, 'details': ?details},
      }),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

http.Response ok(Map<String, dynamic> body) => http.Response(
  jsonEncode(body),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

void main() {
  setUp(() => AuthSession.accessToken = 'test-access-token');
  tearDown(() => AuthSession.accessToken = null);

  PlanService serviceWith(
    Future<http.Response> Function(http.Request) handler,
    List<String> calls,
  ) => PlanService(
    apiClient: ApiClient(
      baseUrl: 'http://test',
      client: MockClient((request) {
        calls.add('${request.method} ${request.url.path}');
        return handler(request);
      }),
    ),
    wait: (_) async {},
  );

  test('lost connection: waits for the running generation and loads it '
      'without calling the model again', () async {
    final calls = <String>[];
    var lookups = 0;
    final service = serviceWith((request) async {
      if (request.method == 'POST') {
        throw http.ClientException('Connection closed before full header');
      }
      lookups++;
      return lookups == 1
          ? error(409, 'PLAN_GENERATION_IN_PROGRESS', {'trip_id': 68})
          : ok(planJson(18));
    }, calls);

    final plan = await service.generateOrRecover(68);

    expect(plan.planId, 18);
    expect(calls, [
      'POST /api/v1/trips/68/plans/generate',
      'GET /api/v1/trips/68/plan',
      'GET /api/v1/trips/68/plan',
    ]);
  });

  test('409 with the existing plan_id loads that plan directly', () async {
    final calls = <String>[];
    final service = serviceWith((request) async {
      if (request.method == 'POST') {
        return error(409, 'PLAN_ALREADY_EXISTS', {'plan_id': 18});
      }
      return ok(planJson(18));
    }, calls);

    final plan = await service.generateOrRecover(68);

    expect(plan.planId, 18);
    expect(calls, [
      'POST /api/v1/trips/68/plans/generate',
      'GET /api/v1/plans/18',
    ]);
  });

  test('sends the verified selected place IDs on the first generation call',
      () async {
    final calls = <String>[];
    late Map<String, dynamic> requestBody;
    final service = serviceWith((request) async {
      if (request.method == 'POST') {
        requestBody = jsonDecode(request.body) as Map<String, dynamic>;
        return ok(planJson(18));
      }
      throw StateError('Unexpected recovery request');
    }, calls);

    final plan = await service.generateOrRecover(68, const [11, 22]);

    expect(plan.planId, 18);
    expect(requestBody, {'selected_place_ids': [11, 22]});
    expect(calls, ['POST /api/v1/trips/68/plans/generate']);
  });

  test('omits selected_place_ids when the caller has no new selection',
      () async {
    late Map<String, dynamic> requestBody;
    final service = serviceWith((request) async {
      requestBody = jsonDecode(request.body) as Map<String, dynamic>;
      return ok(planJson(18));
    }, <String>[]);

    await service.generateOrRecover(68);

    expect(requestBody, isEmpty);
  });

  test('409 from an older server without plan_id falls back to the trip '
      'lookup', () async {
    final calls = <String>[];
    final service = serviceWith((request) async {
      if (request.method == 'POST') return error(409, 'PLAN_ALREADY_EXISTS');
      return ok(planJson(18));
    }, calls);

    expect((await service.generateOrRecover(68)).planId, 18);
    expect(calls.last, 'GET /api/v1/trips/68/plan');
  });

  test('lost connection and no plan on the server rethrows the original '
      'error so the user can retry', () async {
    final calls = <String>[];
    final service = serviceWith((request) async {
      if (request.method == 'POST') throw http.ClientException('reset');
      return error(404, 'PLAN_NOT_FOUND');
    }, calls);

    await expectLater(
      service.generateOrRecover(68),
      throwsA(isA<http.ClientException>()),
    );
    expect(calls.where((call) => call.startsWith('POST')), hasLength(1));
  });

  test('a real generation failure is reported without a lookup', () async {
    final calls = <String>[];
    final service = serviceWith(
      (request) async => error(504, 'OLLAMA_TIMEOUT'),
      calls,
    );

    await expectLater(
      service.generateOrRecover(68),
      throwsA(
        isA<ApiException>().having(apiErrorCode, 'code', 'OLLAMA_TIMEOUT'),
      ),
    );
    expect(calls, ['POST /api/v1/trips/68/plans/generate']);
  });

  test('findForTrip separates ready, generating and missing', () async {
    final responses = [
      ok(planJson(18)),
      error(409, 'PLAN_GENERATION_IN_PROGRESS'),
      error(404, 'PLAN_NOT_FOUND'),
    ];
    final service = serviceWith(
      (request) async => responses.removeAt(0),
      <String>[],
    );

    final ready = await service.findForTrip(68);
    expect(ready.state, TripPlanState.ready);
    expect(ready.plan!.planId, 18);
    expect((await service.findForTrip(68)).state, TripPlanState.generating);
    expect((await service.findForTrip(68)).state, TripPlanState.missing);
  });

  test('existingPlanId reads only the plan_id detail', () {
    expect(
      existingPlanId(
        const ApiException(409, {
          'error': {
            'code': 'PLAN_ALREADY_EXISTS',
            'details': {'plan_id': 18},
          },
        }),
      ),
      18,
    );
    expect(existingPlanId(const ApiException(409, {})), isNull);
    expect(existingPlanId(StateError('x')), isNull);
  });
}
