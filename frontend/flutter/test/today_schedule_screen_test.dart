import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travel_mate/screens/travel/today_travel_screen.dart';
import 'package:travel_mate/screens/trip/itinerary_screen.dart';
import 'package:travel_mate/services/active_trip_service.dart';
import 'package:travel_mate/services/plan_service.dart';

/// Busan trip 68 shape: two days, travel facts as the API sends them.
GeneratedPlan busanPlan() => GeneratedPlan.fromJson({
  'plan_id': 18,
  'status': 'DRAFT',
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
          'validation_status': 'UNKNOWN',
          'item_type': 'PLACE',
          'travel_status': 'NONE',
        },
        {
          'item_id': 2,
          'place_id': 6,
          'name': '신선식당',
          'start_time': '12:00:00',
          'validation_status': 'UNKNOWN',
          'item_type': 'MEAL',
          'travel_status': 'UNKNOWN',
        },
      ],
    },
    {
      'day': 2,
      'visit_date': '2026-10-30',
      'items': [
        {
          'item_id': 3,
          'place_id': 7,
          'name': '해파랑길 1코스',
          'start_time': '09:00:00',
          'validation_status': 'UNKNOWN',
          'item_type': 'PLACE',
          'travel_status': 'NONE',
        },
        {
          'item_id': 4,
          'place_id': 8,
          'name': '이재모피자 본점',
          'start_time': '12:00:00',
          'validation_status': 'UNKNOWN',
          'item_type': 'MEAL',
          'transport_mode_from_previous': 'PUBLIC_TRANSIT',
          'travel_minutes_from_previous': 21,
          'travel_status': 'KNOWN',
        },
      ],
    },
  ],
});

class FakePlanService extends PlanService {
  FakePlanService({this.plan, this.tripState});

  final GeneratedPlan? plan;
  final TripPlanState? tripState;
  final requestedPlanIds = <int>[];
  final requestedTripIds = <int>[];

  @override
  Future<GeneratedPlan> get(int planId) async {
    requestedPlanIds.add(planId);
    return plan!;
  }

  @override
  Future<TripPlanLookup> findForTrip(int tripId) async {
    requestedTripIds.add(tripId);
    return TripPlanLookup(tripState ?? TripPlanState.missing, plan);
  }
}

const sampleCourse = ['안목', '강릉', '경포', '중앙시장', '도보 10분', '오죽헌'];

void expectNoSampleCourse() {
  for (final text in sampleCourse) {
    expect(find.textContaining(text), findsNothing, reason: text);
  }
}

Future<void> pumpToday(
  WidgetTester tester,
  FakePlanService service,
  DateTime today,
) async {
  await tester.pumpWidget(
    MaterialApp(
      home: TodayTravelScreen(planService: service, today: today),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    ActiveTripService.tripId = null;
    ActiveTripService.planId = null;
    ActiveTripService.dates = null;
  });

  testWidgets('without a trip it says so instead of a sample course', (
    tester,
  ) async {
    await pumpToday(tester, FakePlanService(), DateTime(2026, 10, 29));

    expect(find.text('진행 중인 여행이 없어요'), findsOneWidget);
    expectNoSampleCourse();
  });

  testWidgets('shows only the saved plan day whose date is today', (
    tester,
  ) async {
    ActiveTripService.tripId = 68;
    ActiveTripService.planId = 18;
    final service = FakePlanService(plan: busanPlan());
    await pumpToday(tester, service, DateTime(2026, 10, 30, 15));

    expect(service.requestedPlanIds, [18]);
    expect(find.textContaining('오늘 일정 · 10월 30일'), findsWidgets);
    expect(find.textContaining('해파랑길 1코스'), findsWidgets);
    expect(find.textContaining('이재모피자 본점'), findsWidgets);
    expect(find.textContaining('광안리해수욕장'), findsNothing);
    // KNOWN travel is shown as sent; the first stop shows no travel.
    expect(find.textContaining('대중교통 21분'), findsOneWidget);
    expectNoSampleCourse();
  });

  testWidgets('UNKNOWN travel says so and NONE shows nothing', (tester) async {
    ActiveTripService.planId = 18;
    await pumpToday(
      tester,
      FakePlanService(plan: busanPlan()),
      DateTime(2026, 10, 29),
    );

    expect(find.textContaining('09:00\n'), findsOneWidget);
    expect(find.textContaining('12:00 · 이동시간 정보 없음'), findsOneWidget);
    expectNoSampleCourse();
  });

  testWidgets('on a day outside the trip it shows no schedule', (tester) async {
    ActiveTripService.planId = 18;
    await pumpToday(
      tester,
      FakePlanService(plan: busanPlan()),
      DateTime(2026, 10, 11),
    );

    expect(find.text('오늘은 여행 일정이 없어요'), findsOneWidget);
    expect(find.text('이 여행은 10월 29일 ~ 10월 30일 일정이에요.'), findsOneWidget);
    expect(find.textContaining('광안리해수욕장'), findsNothing);
    expectNoSampleCourse();
  });

  testWidgets('a trip without plan_id is looked up by trip_id', (tester) async {
    ActiveTripService.tripId = 68;
    final generating = FakePlanService(tripState: TripPlanState.generating);
    await pumpToday(tester, generating, DateTime(2026, 10, 29));

    expect(generating.requestedTripIds, [68]);
    expect(find.text('일정을 아직 만들고 있어요'), findsOneWidget);
    expect(find.text('다시 확인'), findsOneWidget);
    expectNoSampleCourse();
  });

  testWidgets('a day handed over from the itinerary keeps its travel facts', (
    tester,
  ) async {
    final day = busanPlan().days.last;
    await tester.pumpWidget(
      MaterialApp(
        home: TodayTravelScreen(
          title: 'DAY 2 · 10월 30일 일정',
          itinerary: todayEntriesForPlanDay(day),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('DAY 2 · 10월 30일 일정'), findsWidgets);
    expect(find.textContaining('12:00 · 대중교통 21분'), findsOneWidget);
    expectNoSampleCourse();
  });

  testWidgets('the itinerary without a plan shows an empty state, not the '
      'sample course', (tester) async {
    await tester.pumpWidget(
      MaterialApp(home: ItineraryScreen(planService: FakePlanService())),
    );
    await tester.pumpAndSettle();

    expect(find.text('아직 만들어진 일정이 없어요'), findsOneWidget);
    expect(find.textContaining('강릉역'), findsNothing);
    expectNoSampleCourse();
  });
  testWidgets('server plan warnings are shown on the itinerary', (
    tester,
  ) async {
    final json = {
      'plan_id': 18,
      'status': 'DRAFT',
      'warnings': ['1일차 점심(11:00~14:00) 식사 일정이 없어요.'],
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
              'validation_status': 'WARNING',
              'item_type': 'PLACE',
              'travel_status': 'NONE',
            },
          ],
        },
      ],
    };
    // The day chips overflow by a few pixels with the test font only.
    final onError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.toString().contains('RenderFlex overflowed')) {
        onError?.call(details);
      }
    };
    addTearDown(() => FlutterError.onError = onError);
    await tester.pumpWidget(
      MaterialApp(
        home: ItineraryScreen(generatedPlan: GeneratedPlan.fromJson(json)),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('확인이 필요한 일정'), findsOneWidget);
    expect(find.textContaining('점심(11:00~14:00) 식사 일정이 없어요'), findsOneWidget);
    expectNoSampleCourse();
  }, skip: !showPlanWarnings); // hidden for the demo video
}
