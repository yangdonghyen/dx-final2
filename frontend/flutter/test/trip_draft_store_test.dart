// TC-09: trip-creation inputs are kept per account across app restarts.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
// ignore: depend_on_referenced_packages
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
// ignore: depend_on_referenced_packages
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';
import 'package:travel_mate/screens/trip/trip_places_screen.dart';
import 'package:travel_mate/services/auth_service.dart';
import 'package:travel_mate/services/trip_draft_store.dart';

String token(String subject) {
  String part(Map<String, Object> value) =>
      base64Url.encode(utf8.encode(jsonEncode(value))).replaceAll('=', '');
  return '${part({'alg': 'HS256'})}.${part({'sub': subject, 'type': 'access'})}.signature';
}

String futureDate(int days) =>
    DateUtils.dateOnly(DateTime.now().add(Duration(days: days))).toIso8601String();

void main() {
  setUp(() {
    SharedPreferencesAsyncPlatform.instance = InMemorySharedPreferencesAsync.empty();
    AuthSession.accessToken = token('7');
  });

  test('a draft is stored per account and removed after creation', () async {
    await TripDraftStore.save({'travel_style': '여유롭게'});
    expect((await TripDraftStore.load())?['travel_style'], '여유롭게');

    AuthSession.accessToken = token('18');
    expect(await TripDraftStore.load(), isNull); // another account sees nothing

    AuthSession.accessToken = token('7');
    await TripDraftStore.clear();
    expect(await TripDraftStore.load(), isNull);
  });

  test('without a known account nothing is saved or read', () async {
    AuthSession.accessToken = null;
    await TripDraftStore.save({'travel_style': '알차게'});
    expect(await TripDraftStore.load(), isNull);
    expect(TripDraftStore.ownerOf('not-a-jwt'), isNull);
  });

  testWidgets('the screen restores a saved draft and keeps saving changes', (tester) async {
    await TripDraftStore.save({
      'step': 3,
      'start_date': futureDate(10),
      'end_date': futureDate(12),
      'travel_style': '여유롭게',
      'tastes': ['바다', '카페'],
      'transport': ['자동차'],
      'companions': ['엄마', '친구'],
      'selected_companions': [0, 1],
      'current_companion': 1,
      'destination': '제주',
    });

    await tester.pumpWidget(const MaterialApp(home: TripPlacesScreen()));
    await tester.pumpAndSettle();
    expect(find.text('이동수단'), findsWidgets); // restored to step 3

    // Restoring must not overwrite the stored draft with empty values.
    await tester.pump(const Duration(seconds: 1));
    final stored = await TripDraftStore.load();
    expect(stored?['transport'], ['자동차']);
    expect(stored?['tastes'], ['바다', '카페']);
    expect(stored?['destination'], '제주');

    await tester.ensureVisible(find.text('택시'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('택시'));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    expect((await TripDraftStore.load())?['transport'], ['택시']); // one transport mode is selected at a time
  });

  testWidgets('a draft started for another place does not reopen at its step', (tester) async {
    // Demo: a YouTube video (강릉) opened trip creation at step 3 of an old draft.
    await TripDraftStore.save({'step': 3, 'transport': ['자동차'], 'origin': ['제주']});

    await tester.pumpWidget(const MaterialApp(home: TripPlacesScreen(initialPlaces: {'강릉'})));
    await tester.pumpAndSettle();

    expect(find.text('이동수단'), findsNothing); // starts from the first step
  });
}
