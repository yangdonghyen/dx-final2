import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:latlong2/latlong.dart';
import 'package:travel_mate/screens/trip/itinerary_screen.dart';
import 'package:travel_mate/services/plan_service.dart';

// Three days far apart on Jeju: DAY 1 north-east, DAY 2 east, DAY 3 west.
const _days = [
  [(33.5430, 126.6692), (33.5425, 126.6700)],
  [(33.4590, 126.9410), (33.4790, 126.9060)],
  [(33.4780, 126.3690)],
];

Map<String, dynamic> _item(int id, (double, double) at, String start) => {
  'item_id': id,
  'place_id': id,
  'name': '장소$id',
  'start_time': start,
  'end_time': start,
  'latitude': at.$1,
  'longitude': at.$2,
  'validation_status': 'VALID',
  'item_type': 'PLACE',
  'travel_status': 'NONE',
};

GeneratedPlan _plan() {
  var id = 0;
  return GeneratedPlan.fromJson({
    'plan_id': 36,
    'status': 'DRAFT',
    'warnings': <String>[],
    'days': [
      for (var day = 0; day < _days.length; day++)
        {
          'day': day + 1,
          'visit_date': '2026-10-2${6 + day}',
          'items': [
            for (var index = 0; index < _days[day].length; index++)
              _item(++id, _days[day][index], '${9 + index * 2}:00:00'.padLeft(8, '0')),
          ],
        },
    ],
  });
}

MapCamera _camera(WidgetTester tester) =>
    MapCamera.of(tester.element(find.byType(MarkerLayer)));

List<LatLng> _markers(WidgetTester tester) =>
    tester.widget<MarkerLayer>(find.byType(MarkerLayer)).markers.map((m) => m.point).toList();

void _expectAllVisible(WidgetTester tester, List<(double, double)> expected) {
  final shown = _markers(tester);
  expect(shown, [for (final at in expected) LatLng(at.$1, at.$2)]);
  final bounds = _camera(tester).visibleBounds;
  for (final point in shown) {
    expect(bounds.contains(point), isTrue, reason: '$point outside $bounds');
  }
}

Future<void> _settle(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
  await tester.pumpAndSettle(const Duration(milliseconds: 50));
}

void main() {
  testWidgets('the map follows DAY 1 -> 2 -> 3 -> 전체 and shows every pin', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.5;
    addTearDown(tester.view.reset);
    final onError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.toString().contains('RenderFlex overflowed')) onError?.call(details);
    };
    addTearDown(() => FlutterError.onError = onError);

    await tester.pumpWidget(MaterialApp(home: ItineraryScreen(generatedPlan: _plan())));
    await _settle(tester);
    _expectAllVisible(tester, _days[0]);

    await tester.tap(find.text('DAY 2'));
    await _settle(tester);
    _expectAllVisible(tester, _days[1]);

    await tester.tap(find.text('DAY 3'));
    await _settle(tester);
    _expectAllVisible(tester, _days[2]); // one stop: a street-level zoom
    expect(_camera(tester).zoom, lessThanOrEqualTo(15));

    await tester.tap(find.text('전체'));
    await _settle(tester);
    await tester.tap(find.text('지도 펼치기'));
    await _settle(tester);
    _expectAllVisible(tester, [..._days[0], ..._days[1], ..._days[2]]);
  });
}
