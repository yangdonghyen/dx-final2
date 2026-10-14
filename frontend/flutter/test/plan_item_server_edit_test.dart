import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travel_mate/screens/trip/itinerary_screen.dart';
import 'package:travel_mate/services/plan_service.dart';

GeneratedPlan _plan({String start = '09:00:00', String? note}) => GeneratedPlan.fromJson({
  'plan_id': 38,
  'status': 'DRAFT',
  'warnings': <String>[],
  'days': [
    {'day': 1, 'visit_date': '2099-10-26', 'items': [
      {'item_id': 7, 'place_id': 5, 'name': '함덕해수욕장', 'start_time': start, 'end_time': '10:00:00',
       'validation_status': 'VALID', 'item_type': 'PLACE', 'travel_status': 'NONE', 'note': ?note},
    ]},
  ],
});

class _Plans extends PlanService {
  final calls = <String>[];

  @override
  Future<void> updateItem(int planId, int itemId, {String? startTime, String? title, String? note}) async {
    calls.add('$planId $itemId $startTime $title $note');
  }

  @override
  Future<GeneratedPlan> get(int planId) async => _plan(start: '09:30:00', note: '일출 보기');
}

void main() {
  testWidgets('a stop edit is saved on the server and the saved plan is shown', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.5;
    addTearDown(tester.view.reset);
    final onError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.toString().contains('RenderFlex overflowed')) onError?.call(details);
    };
    addTearDown(() => FlutterError.onError = onError);
    final plans = _Plans();
    await tester.pumpWidget(MaterialApp(home: ItineraryScreen(generatedPlan: _plan(), planService: plans)));
    await tester.pumpAndSettle();

    final course = find.text('코스 수정');
    await tester.scrollUntilVisible(course, 200, scrollable: find.byType(Scrollable).last);
    await tester.tap(course);
    await tester.pumpAndSettle();
    final editButton = find.byTooltip('함덕해수욕장 수정');
    await tester.scrollUntilVisible(editButton, -200, scrollable: find.byType(Scrollable).last);
    await tester.tap(editButton);
    await tester.pumpAndSettle();

    final placeField = tester.widget<TextField>(find.widgetWithText(TextField, '장소'));
    expect(placeField.enabled, isFalse); // a verified place is not retyped
    await tester.enterText(find.widgetWithText(TextField, '시간'), '0930');
    await tester.enterText(find.widgetWithText(TextField, '설명'), '일출 보기');
    await tester.tap(find.widgetWithText(FilledButton, '저장'));
    await tester.pumpAndSettle();

    expect(plans.calls, ['38 7 09:30 null 일출 보기']);
    expect(find.textContaining('일출 보기'), findsWidgets);
  });
}
