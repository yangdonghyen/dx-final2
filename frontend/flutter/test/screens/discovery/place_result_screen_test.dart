import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:travel_mate/screens/discovery/place_result_screen.dart';
import 'package:travel_mate/screens/trip/trip_places_screen.dart';
import 'package:travel_mate/services/scene_image_service.dart';

const _imagePath = 'test/screens/discovery/place_result_screen_test.dart';

void main() {
  testWidgets('shows a retake action when the image has no recognized place', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: PlaceResultScreen(
          imagePath: _imagePath,
          result: SceneRecognitionResult(recognized: false, verified: false),
        ),
      ),
    );

    expect(find.text('어디인지는 알 수 없었어요'), findsOneWidget);
    expect(find.text('다시 찍기'), findsOneWidget);
    expect(find.text('여행 코스 짜기'), findsNothing);
  });

  testWidgets('starts trip creation from a recognized place without inventing coordinates', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: PlaceResultScreen(
          imagePath: _imagePath,
          result: SceneRecognitionResult(
            recognized: true,
            verified: false,
            placeName: 'Gyeongbokgung Palace',
            areaLabel: 'Seoul',
          ),
        ),
      ),
    );

    expect(find.text('AI가 추측한 장소예요. 지도에서 확인되지 않았으니 정확한지 한 번 확인해주세요.'), findsOneWidget);
    await tester.tap(find.text('여행 코스 짜기'));
    await tester.pumpAndSettle();

    final tripScreen = tester.widget<TripPlacesScreen>(find.byType(TripPlacesScreen));
    expect(tripScreen.initialPlaces, {'Gyeongbokgung Palace'});
  });
}
