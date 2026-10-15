import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 여행을 확정했을 때 전체 일정에서 다시 사용하는 동행자 정보입니다.
class ActiveTripCompanion {
  const ActiveTripCompanion({required this.name});

  final String name;
}

/// Keeps the most recently confirmed trip available across home destinations.
///
/// The trip is also written to the device so it survives an app restart, and
/// it is removed on logout so another account never sees it.
class ActiveTripService {
  static const _tripIdKey = 'active_trip_id';
  static const _planIdKey = 'active_trip_plan_id';
  static const _startKey = 'active_trip_start';
  static const _endKey = 'active_trip_end';
  static const _transportKey = 'active_trip_transport';
  static const _placesKey = 'active_trip_places';
  static const _nameKey = 'active_trip_name';

  /// Backend trip_id of the confirmed trip; null until the server saved it.
  static int? tripId;

  /// Backend plan_id of the AI plan for [tripId]; null when none was made.
  static int? planId;
  static DateTimeRange? dates;
  static Set<String> transport = <String>{};
  static List<String> places = <String>[];
  static List<ActiveTripCompanion> companions = <ActiveTripCompanion>[];

  /// "강릉 여행": the trip's title or destination.  Null for trips saved
  /// before this was kept; Home then falls back to the first place.
  static String? name;

  /// Trip title if set, else "(destination) 여행", else null.
  static String? nameFor({String? title, String? destination}) {
    final clean = title?.trim();
    if (clean != null && clean.isNotEmpty) return clean;
    final place = destination?.trim();
    return place == null || place.isEmpty ? null : '$place 여행';
  }

  /// Increments whenever a trip is confirmed so visible home cards refresh.
  static final ValueNotifier<int> revision = ValueNotifier<int>(0);

  static void save({
    required int? savedTripId,
    int? savedPlanId,
    required DateTimeRange? tripDates,
    required Set<String> selectedTransport,
    required Iterable<String> selectedPlaces,
    Iterable<ActiveTripCompanion> selectedCompanions = const [],
    String? tripName,
  }) {
    tripId = savedTripId;
    name = tripName;
    planId = savedPlanId;
    dates = tripDates;
    transport = Set<String>.of(selectedTransport);
    places = List<String>.of(selectedPlaces);
    companions = List<ActiveTripCompanion>.of(selectedCompanions);
    revision.value++;
    unawaited(
      _persist().catchError(
        (Object error) => debugPrint('[ActiveTrip] save failed: $error'),
      ),
    );
  }

  /// Loads the trip saved by [save] on a previous app run.
  static Future<void> restore() async {
    try {
      final preferences = await SharedPreferences.getInstance();
      tripId = preferences.getInt(_tripIdKey);
      planId = preferences.getInt(_planIdKey);
      final start = DateTime.tryParse(preferences.getString(_startKey) ?? '');
      final end = DateTime.tryParse(preferences.getString(_endKey) ?? '');
      dates = start != null && end != null && !end.isBefore(start)
          ? DateTimeRange(start: start, end: end)
          : null;
      transport = (preferences.getStringList(_transportKey) ?? const [])
          .toSet();
      places = preferences.getStringList(_placesKey) ?? <String>[];
      name = preferences.getString(_nameKey);
    } catch (error) {
      debugPrint('[ActiveTrip] restore failed: $error');
    }
  }

  /// Forgets the trip in memory and on the device (used on logout).
  static Future<void> clear() async {
    tripId = null;
    planId = null;
    dates = null;
    transport = <String>{};
    places = <String>[];
    companions = <ActiveTripCompanion>[];
    name = null;
    revision.value++;
    final preferences = await SharedPreferences.getInstance();
    for (final key in [
      _tripIdKey,
      _planIdKey,
      _startKey,
      _endKey,
      _transportKey,
      _placesKey,
      _nameKey,
    ]) {
      await preferences.remove(key);
    }
  }

  static Future<void> _persist() async {
    final preferences = await SharedPreferences.getInstance();
    final id = tripId;
    if (id == null) {
      await preferences.remove(_tripIdKey);
    } else {
      await preferences.setInt(_tripIdKey, id);
    }
    final plan = planId;
    if (plan == null) {
      await preferences.remove(_planIdKey);
    } else {
      await preferences.setInt(_planIdKey, plan);
    }
    final range = dates;
    if (range == null) {
      await preferences.remove(_startKey);
      await preferences.remove(_endKey);
    } else {
      await preferences.setString(_startKey, range.start.toIso8601String());
      await preferences.setString(_endKey, range.end.toIso8601String());
    }
    await preferences.setStringList(_transportKey, transport.toList());
    await preferences.setStringList(_placesKey, places);
    final tripName = name;
    if (tripName == null) {
      await preferences.remove(_nameKey);
    } else {
      await preferences.setString(_nameKey, tripName);
    }
  }
}
