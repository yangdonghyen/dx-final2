import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';
import '../../services/active_trip_service.dart';
import '../../services/plan_service.dart';
import '../../services/trip_service.dart';
import '../../widgets/app_bottom_navigation.dart';
import '../trip/itinerary_screen.dart';

/// Upcoming trips saved on the server; a trip with a plan opens its itinerary.
///
/// The home card only knows the trip saved on this phone (cleared on
/// logout), so this is the way back to any other saved plan.
class UpcomingTripsScreen extends StatefulWidget {
  const UpcomingTripsScreen({super.key, this.tripService, this.planService});

  final TripService? tripService;
  final PlanService? planService;

  @override
  State<UpcomingTripsScreen> createState() => _UpcomingTripsScreenState();
}

class _UpcomingTripsScreenState extends State<UpcomingTripsScreen> {
  late final TripService _tripService = widget.tripService ?? TripService();
  late final PlanService _planService = widget.planService ?? PlanService();

  bool _loading = true;
  String? _error;
  int? _opening;
  List<TripListItem> _trips = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final now = DateTime.now();
      final today = DateTime(now.year, now.month, now.day);
      final trips = (await _tripService.list()).where((trip) {
        final end = trip.endDate;
        return end != null && !DateTime(end.year, end.month, end.day).isBefore(today);
      }).toList()
        ..sort((a, b) => (a.startDate ?? DateTime(9999)).compareTo(b.startDate ?? DateTime(9999)));
      if (!mounted) return;
      setState(() {
        _trips = trips;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '예정 여행을 불러오지 못했어요.';
      });
    }
  }

  Future<void> _open(TripListItem trip) async {
    if (_opening != null) return;
    setState(() => _opening = trip.tripId);
    try {
      final lookup = await _planService.findForTrip(trip.tripId);
      if (!mounted) return;
      final plan = lookup.plan;
      if (lookup.state != TripPlanState.ready || plan == null) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(lookup.state == TripPlanState.generating
              ? '이 여행의 일정을 아직 만들고 있어요.'
              : '이 여행에는 아직 만들어진 일정이 없어요.'),
        ));
        return;
      }
      final start = trip.startDate;
      final end = trip.endDate;
      final dates = start != null && end != null && !end.isBefore(start)
          ? DateTimeRange(start: start, end: end)
          : null;
      final places = <String>{
        for (final day in plan.days)
          for (final item in day.items)
            if (item.placeId != null && item.name.trim().isNotEmpty) item.name.trim(),
      }.toList();
      // Same record a freshly generated plan leaves, so Home shows this trip.
      ActiveTripService.save(
        savedTripId: trip.tripId,
        savedPlanId: plan.planId,
        tripDates: dates,
        selectedTransport: const <String>{},
        selectedPlaces: places,
      );
      await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => ItineraryScreen(
          tripDates: dates,
          places: places,
          generatedPlan: plan,
          planService: _planService,
        ),
      ));
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(planErrorMessage(error))),
      );
    } finally {
      if (mounted) setState(() => _opening = null);
    }
  }

  static String _date(DateTime? value) =>
      value == null ? '-' : '${value.year}.${value.month.toString().padLeft(2, '0')}.${value.day.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: AppColors.bg,
    appBar: AppBar(title: const Text('예정 여행')),
    body: _loading
        ? const Center(child: CircularProgressIndicator())
        : _error != null
        ? Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(_error!),
                TextButton(onPressed: _load, child: const Text('다시 시도')),
              ],
            ),
          )
        : _trips.isEmpty
        ? const Center(child: Text('예정된 여행이 없어요'))
        : ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
            itemCount: _trips.length,
            separatorBuilder: (_, _) => const SizedBox(height: 10),
            itemBuilder: (context, index) {
              final trip = _trips[index];
              final title = (trip.title?.trim().isNotEmpty ?? false)
                  ? trip.title!.trim()
                  : '${trip.destination ?? '여행'} 여행';
              return Material(
                color: Colors.white,
                borderRadius: BorderRadius.circular(16),
                child: ListTile(
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                  title: Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
                  subtitle: Text('${_date(trip.startDate)} ~ ${_date(trip.endDate)}'),
                  trailing: _opening == trip.tripId
                      ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.chevron_right_rounded),
                  onTap: () => _open(trip),
                ),
              );
            },
          ),
    bottomNavigationBar: const AppBottomNavigation(selectedIndex: 3),
  );
}
