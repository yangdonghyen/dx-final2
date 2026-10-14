import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
// ignore: depend_on_referenced_packages
import 'package:image_picker_platform_interface/image_picker_platform_interface.dart';

import 'package:travel_mate/screens/discovery/camera_screen.dart';

/// The album refuses access, as when the user denies photo permission.
class _DeniedPicker extends ImagePickerPlatform {
  int calls = 0;

  @override
  Future<XFile?> getImageFromSource({
    required ImageSource source,
    ImagePickerOptions options = const ImagePickerOptions(),
  }) async {
    calls++;
    throw PlatformException(code: 'photo_access_denied');
  }
}

void main() {
  testWidgets('gallery flow starts without a selected image and disables analysis', (tester) async {
    // A phone-sized screen: on the default 800x600 test view the buttons sit
    // below the lazily built part of the ListView.
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.5;
    addTearDown(tester.view.reset);
    final picker = _DeniedPicker();
    ImagePickerPlatform.instance = picker;
    await tester.pumpWidget(const MaterialApp(home: CameraScreen(galleryOnly: true)));

    expect(find.text('이미지에서 장소를 찾아드릴게요'), findsOneWidget);
    // OutlinedButton.icon builds a private OutlinedButton subclass, which
    // widgetWithText (exact type match) cannot find.
    final galleryButton = find.ancestor(
      of: find.text('앨범에서 불러오기'),
      matching: find.byWidgetPredicate((widget) => widget is OutlinedButton),
    );
    expect(galleryButton, findsOneWidget);
    final analyze = tester.widget<FilledButton>(find.widgetWithText(FilledButton, '장소 분석하기'));
    expect(analyze.onPressed, isNull);

    await tester.tap(galleryButton);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(picker.calls, 1); // the album was actually asked for an image
    expect(find.text('사진을 불러오지 못했어요. 권한을 확인해 주세요.'), findsOneWidget);
  });

  testWidgets('camera flow exposes a cancel control while opening the camera', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: CameraScreen()));
    await tester.pump();

    expect(find.byIcon(Icons.close), findsOneWidget);
    expect(find.bySemanticsLabel('사진 촬영하기'), findsOneWidget);
  });
}
