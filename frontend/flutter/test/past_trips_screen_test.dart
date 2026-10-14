import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travel_mate/screens/my/past_trips_screen.dart';
import 'package:travel_mate/screens/trip/itinerary_screen.dart';
import 'package:travel_mate/services/plan_service.dart';
import 'package:travel_mate/services/trip_service.dart';

class _Trips extends TripService {
  final discarded = <int>[];

  @override
  Future<void> discard(int tripId) async => discarded.add(tripId);

  @override
  Future<String?> destinationImage(String destination) async => null;

  @override
  Future<List<TripListItem>> list() async => [
    TripListItem(
      tripId: 60,
      status: 'DRAFT',
      title: 'Demo past trip',
      destination: 'Jeju',
      startDate: DateTime(2026, 9, 12),
      endDate: DateTime(2026, 9, 14),
    ),
    TripListItem(
      tripId: 92,
      status: 'DRAFT',
      destination: 'Future trip',
      startDate: DateTime(2099, 10, 26),
      endDate: DateTime(2099, 10, 28),
    ),
  ];
}

class _Plans extends PlanService {
  final opened = <int>[];

  @override
  Future<TripPlanLookup> findForTrip(int tripId) async {
    opened.add(tripId);
    return TripPlanLookup(
      TripPlanState.ready,
      GeneratedPlan.fromJson({
        'plan_id': 14,
        'status': 'DRAFT',
        'warnings': <String>[],
        'days': [
          {
            'day': 1,
            'visit_date': '2026-09-12',
            'items': [
              {
                'item_id': 1,
                'place_id': 5,
                'name': 'Verified place',
                'start_time': '09:00:00',
                'end_time': '10:00:00',
                'validation_status': 'VALID',
                'item_type': 'PLACE',
                'travel_status': 'NONE',
              },
            ],
          },
        ],
      }),
    );
  }
}

void main() {
  testWidgets('past trips use the saved server plan and exclude future trips', (
    tester,
  ) async {
    // Phone-sized view, as in the other itinerary tests.
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.5;
    addTearDown(tester.view.reset);
    // The test font is wider than the device font; ignore only layout overflow.
    final onError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.toString().contains('RenderFlex overflowed')) onError?.call(details);
    };
    addTearDown(() => FlutterError.onError = onError);
    final plans = _Plans();

    await tester.pumpWidget(
      MaterialApp(
        home: PastTripsScreen(tripService: _Trips(), planService: plans),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Demo past trip'), findsOneWidget);
    expect(find.text('Future trip'), findsNothing);

    await tester.tap(find.text('Demo past trip'));
    await tester.pumpAndSettle();

    expect(plans.opened, [60]);
    expect(find.byType(ItineraryScreen), findsOneWidget);
    expect(find.textContaining('Verified place'), findsWidgets);
  });

  testWidgets('a past trip can be discarded after confirming', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.5;
    addTearDown(tester.view.reset);
    final onError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.toString().contains('RenderFlex overflowed')) onError?.call(details);
    };
    addTearDown(() => FlutterError.onError = onError);
    final trips = _Trips();
    await tester.pumpWidget(MaterialApp(home: PastTripsScreen(tripService: trips, planService: _Plans())));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('여행 버리기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();
    expect(trips.discarded, isEmpty);

    await tester.tap(find.byTooltip('여행 버리기'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '버리기'));
    await tester.pumpAndSettle();
    expect(trips.discarded, [60]);
    expect(find.text('Demo past trip'), findsNothing);
  });
}
