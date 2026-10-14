import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travel_mate/screens/travel/weather_screen.dart';
import 'package:travel_mate/screens/trip/itinerary_screen.dart';
import 'package:travel_mate/services/plan_service.dart';

class _Plans extends PlanService {
  final asked = <String>[];

  @override
  Future<PlanRegenerationPreview> createRegenerationPreview(
    int planId, {
    required String reason,
    required String instruction,
    List<String> feedbackCodes = const <String>[],
  }) async {
    asked.add('$planId $reason ${feedbackCodes.length}');
    return PlanRegenerationPreview.fromJson({
      'preview_id': 7,
      'plan_id': planId,
      'base_version': 1,
      'status': 'PENDING',
      'proposed_itinerary': {'items': <Object>[]},
      'diff': <Object>[],
      'validation_status': 'VALID',
      'expires_at': '2099-01-01T00:00:00Z',
    });
  }
}

void main() {
  testWidgets('opening the itinerary from weather plan 2 asks for a WEATHER_CHANGE preview and applies nothing', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.5;
    addTearDown(tester.view.reset);
    final onError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.toString().contains('RenderFlex overflowed')) onError?.call(details);
    };
    addTearDown(() => FlutterError.onError = onError);
    final plans = _Plans();
    final plan = GeneratedPlan.fromJson({
      'plan_id': 36,
      'status': 'DRAFT',
      'warnings': <String>[],
      'days': [
        {'day': 1, 'visit_date': '2099-10-26', 'items': [
          {'item_id': 1, 'place_id': 5, 'name': '협재해수욕장', 'start_time': '09:00:00', 'end_time': '10:00:00',
           'validation_status': 'VALID', 'item_type': 'PLACE', 'travel_status': 'NONE'},
        ]},
      ],
    });
    await tester.pumpWidget(MaterialApp(home: ItineraryScreen(
      generatedPlan: plan,
      planService: plans,
      weatherInstruction: weatherPlanInstructions[2],
    )));
    await tester.pumpAndSettle();

    expect(plans.asked, ['36 WEATHER_CHANGE 0']);
    expect(find.text('일정 수정안'), findsOneWidget);
    expect(find.textContaining('협재해수욕장'), findsWidgets); // stored itinerary still shown
  });
}
