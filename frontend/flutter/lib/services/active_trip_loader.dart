import 'package:flutter/material.dart';

import 'active_trip_service.dart';
import 'plan_service.dart';
import 'trip_service.dart';

/// Makes a trip saved on the server the phone's current trip (Home's
/// 다가오는 여행, 전체 일정, 오늘 날씨).  Returns false when the trip has no
/// plan yet.
Future<bool> activateServerTrip(TripListItem trip, {PlanService? planService}) async {
  final lookup = await (planService ?? PlanService()).findForTrip(trip.tripId);
  final plan = lookup.plan;
  if (plan == null) return false;
  final start = trip.startDate;
  final end = trip.endDate;
  ActiveTripService.save(
    savedTripId: trip.tripId,
    savedPlanId: plan.planId,
    tripDates: start != null && end != null && !end.isBefore(start)
        ? DateTimeRange(start: start, end: end)
        : null,
    selectedTransport: const <String>{},
    selectedPlaces: <String>{
      for (final day in plan.days)
        for (final item in day.items)
          if (item.placeId != null && item.name.trim().isNotEmpty) item.name.trim(),
    }.toList(),
    tripName: ActiveTripService.nameFor(title: trip.title, destination: trip.destination),
  );
  return true;
}

/// The trip with [tripId] from the user's list (owned or joined), if any.
Future<TripListItem?> findServerTrip(int tripId) async {
  final trips = await TripService().list();
  for (final trip in trips) {
    if (trip.tripId == tripId) return trip;
  }
  return null;
}
