import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travel_mate/screens/my/upcoming_trips_screen.dart';
import 'package:travel_mate/screens/trip/itinerary_screen.dart';
import 'package:travel_mate/services/plan_service.dart';
import 'package:travel_mate/services/trip_service.dart';

class _Trips extends TripService {
  @override
  Future<List<TripListItem>> list() async => [
    TripListItem(tripId: 1, status: 'DRAFT', destination: '부산', startDate: DateTime(2020, 1, 1), endDate: DateTime(2020, 1, 2)),
    TripListItem(tripId: 92, status: 'DRAFT', destination: '제주', startDate: DateTime(2099, 10, 26), endDate: DateTime(2099, 10, 28)),
    TripListItem(tripId: 93, status: 'DRAFT', destination: '강릉', startDate: DateTime(2099, 11, 1), endDate: DateTime(2099, 11, 2)),
  ];
}

class _Plans extends PlanService {
  final opened = <int>[];

  @override
  Future<TripPlanLookup> findForTrip(int tripId) async {
    opened.add(tripId);
    if (tripId != 92) return const TripPlanLookup(TripPlanState.missing);
    return TripPlanLookup(TripPlanState.ready, GeneratedPlan.fromJson({
      'plan_id': 36,
      'status': 'DRAFT',
      'warnings': <String>[],
      'days': [
        {'day': 1, 'visit_date': '2099-10-26', 'items': [
          {'item_id': 1, 'place_id': 5, 'name': '함덕해수욕장', 'start_time': '09:00:00', 'end_time': '10:00:00',
           'validation_status': 'VALID', 'item_type': 'PLACE', 'travel_status': 'NONE'},
        ]},
      ],
    }));
  }
}

void main() {
  testWidgets('upcoming saved trips open their real plan; past trips are not listed', (tester) async {
    final onError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.toString().contains('RenderFlex overflowed')) onError?.call(details);
    };
    addTearDown(() => FlutterError.onError = onError);
    final plans = _Plans();
    await tester.pumpWidget(MaterialApp(home: UpcomingTripsScreen(tripService: _Trips(), planService: plans)));
    await tester.pumpAndSettle();

    expect(find.text('부산 여행'), findsNothing);
    expect(find.text('제주 여행'), findsOneWidget);

    await tester.tap(find.text('강릉 여행'));
    await tester.pumpAndSettle();
    expect(find.text('이 여행에는 아직 만들어진 일정이 없어요.'), findsOneWidget);

    await tester.tap(find.text('제주 여행'));
    await tester.pumpAndSettle();
    expect(plans.opened, [93, 92]);
    expect(find.byType(ItineraryScreen), findsOneWidget);
    expect(find.text('제주 여행 일정'), findsOneWidget); // the trip's name, not its first stop
  });
}
