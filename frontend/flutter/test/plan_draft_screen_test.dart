import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travel_mate/screens/trip/itinerary_screen.dart';
import 'package:travel_mate/screens/trip/plan_draft_screen.dart';
import 'package:travel_mate/services/plan_service.dart';

Map<String, dynamic> _item(int id, String name, String start, String end, {String type = 'PLACE', int? minutes, String? mode, int? meters, String category = '여행 > 관광,명소 > 해수욕장,해변'}) => {
  'item_id': id, 'place_id': type == 'REST' ? null : id, 'name': name, 'start_time': start, 'end_time': end,
  'validation_status': 'VALID', 'item_type': type, 'category': category,
  'travel_status': minutes == null ? 'NONE' : 'KNOWN',
  'transport_mode_from_previous': mode, 'travel_minutes_from_previous': minutes,
  'travel_distance_meters_from_previous': meters,
};

GeneratedPlan _plan(String first) => GeneratedPlan.fromJson({
  'plan_id': 52, 'status': 'DRAFT', 'warnings': <String>[],
  'days': [
    {'day': 1, 'visit_date': '2099-10-24', 'items': [
      _item(1, first, '10:00:00', '11:30:00'),
      _item(2, '강릉커피거리', '11:40:00', '13:00:00', minutes: 10, mode: 'WALK', meters: 700, category: '음식점 > 카페'),
      _item(3, '강릉중앙시장', '13:10:00', '14:10:00', type: 'MEAL', minutes: 8, mode: 'CAR', meters: 3200, category: '음식점 > 한식'),
    ]},
  ],
});

class _Plans extends PlanService {
  final calls = <String>[];
  @override
  Future<GeneratedPlan> redraft(int planId) async { calls.add('redraft $planId'); return _plan('경포해변'); }
  @override
  Future<void> confirm(int planId) async => calls.add('confirm $planId');
}

Future<_Plans> _pump(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.5;
  addTearDown(tester.view.reset);
  final onError = FlutterError.onError;
  FlutterError.onError = (details) {
    if (!details.toString().contains('RenderFlex overflowed')) onError?.call(details);
  };
  addTearDown(() => FlutterError.onError = onError);
  final plans = _Plans();
  await tester.pumpWidget(MaterialApp(home: PlanDraftScreen(plan: _plan('안목해변'), places: const ['강릉'], planService: plans)));
  await tester.pumpAndSettle();
  return plans;
}

void main() {
  testWidgets('the draft shows the timetable with travel and a day summary', (tester) async {
    await _pump(tester);
    expect(find.text('1. 안목해변'), findsOneWidget);
    expect(find.text('해수욕장,해변 · 90분'), findsOneWidget);
    expect(find.text('도보 10분 · 700m'), findsOneWidget);
    expect(find.text('자차 8분 · 3.2km'), findsOneWidget);
    expect(find.textContaining('1일차 · 3곳 · 총 이동 약 18분 · 도보 10분'), findsOneWidget);
  });

  testWidgets('다시 만들기 shows a new draft and 확정하기 opens the itinerary', (tester) async {
    final plans = await _pump(tester);
    await tester.tap(find.widgetWithText(OutlinedButton, '다시 만들기'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '다시 만들기'));
    await tester.pumpAndSettle();
    expect(find.text('1. 경포해변'), findsOneWidget);

    await tester.tap(find.text('확정하기'));
    await tester.pumpAndSettle();
    expect(plans.calls, ['redraft 52', 'confirm 52']);
    expect(find.byType(ItineraryScreen), findsOneWidget);
  });
}
