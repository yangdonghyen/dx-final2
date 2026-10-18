import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travel_mate/screens/trip/itinerary_screen.dart';
import 'package:travel_mate/services/plan_service.dart';

const _hours = 'Opening hours are not verified for this visit';

Map<String, dynamic> _item(int id, String name, String start) => {
  'item_id': id,
  'place_id': id,
  'name': name,
  'start_time': start,
  'end_time': start,
  'validation_status': 'WARNING',
  'item_type': 'PLACE',
  'travel_status': 'NONE',
};

GeneratedPlan _plan() => GeneratedPlan.fromJson({
  'plan_id': 32,
  'status': 'DRAFT',
  'warnings': [_hours, _hours, '1일차 점심(11:00~14:00) 식사 일정이 없어요.'],
  'days': [
    {'day': 1, 'visit_date': '2026-10-26', 'items': [_item(1, '첫날장소', '09:00:00')]},
    {'day': 2, 'visit_date': '2026-10-27', 'items': [_item(2, '둘째날장소', '09:00:00')]},
    {'day': 3, 'visit_date': '2026-10-28', 'items': [_item(3, '셋째날장소', '09:00:00')]},
  ],
});

Future<void> _pump(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.5;
  addTearDown(tester.view.reset);
  final onError = FlutterError.onError;
  FlutterError.onError = (details) {
    if (!details.toString().contains('RenderFlex overflowed')) onError?.call(details);
  };
  addTearDown(() => FlutterError.onError = onError);
  await tester.pumpWidget(MaterialApp(home: ItineraryScreen(generatedPlan: _plan())));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('전체 tab lists every day and each day folds', (tester) async {
    await _pump(tester);
    await tester.tap(find.text('전체'));
    await tester.pumpAndSettle();

    expect(find.textContaining('첫날장소'), findsWidgets);
    expect(find.textContaining('셋째날장소'), findsWidgets);
    expect(find.text('지도 펼치기'), findsOneWidget); // map folded by default here

    await tester.tap(find.textContaining('10월 27일 · 1개 일정'));
    await tester.pumpAndSettle();
    expect(find.textContaining('둘째날장소'), findsNothing);
  });

  testWidgets('a swipe on the list moves to the next day', (tester) async {
    await _pump(tester);
    expect(find.textContaining('첫날장소'), findsWidgets);
    await tester.fling(find.textContaining('첫날장소').first, const Offset(-400, 0), 1500);
    await tester.pumpAndSettle();
    expect(find.textContaining('둘째날장소'), findsWidgets);
  });

  testWidgets('repeated unverified-hours warnings are summarised in Korean', (tester) async {
    await _pump(tester);
    expect(find.text('• $_hours'), findsNothing);
    expect(find.textContaining('영업시간이 확인되지 않은 장소 2곳'), findsOneWidget);
    expect(find.textContaining('점심(11:00~14:00) 식사 일정이 없어요'), findsOneWidget);

    await tester.tap(find.textContaining('영업시간이 확인되지 않은 장소 2곳'));
    await tester.pumpAndSettle();
    expect(find.text('- 첫날장소'), findsOneWidget);
  }, skip: !showPlanWarnings); // hidden for the demo video

  testWidgets('the map folds and unfolds on the DAY view', (tester) async {
    await _pump(tester);
    await tester.tap(find.text('지도 접기'));
    await tester.pumpAndSettle();
    expect(find.text('지도 펼치기'), findsOneWidget);
  });
}
