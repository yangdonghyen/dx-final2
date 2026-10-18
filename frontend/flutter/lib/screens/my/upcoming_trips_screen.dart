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

  /// 왼쪽→오른쪽 슬라이드: 먼저 물어보고, 확인하면 여행을 지워요(서버 보관).
  Future<bool> _deleteTrip(TripListItem trip, String title) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('일정을 삭제하시겠습니까?'),
        content: Text('$title을(를) 내 여행 일정에서 삭제해요.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(dialogContext).pop(false), child: const Text('거절')),
          FilledButton(onPressed: () => Navigator.of(dialogContext).pop(true), child: const Text('확인')),
        ],
      ),
    );
    if (ok != true || !mounted) return false;
    try {
      await _tripService.discard(trip.tripId);
      if (ActiveTripService.tripId == trip.tripId) await ActiveTripService.clear();
      if (!mounted) return false;
      setState(() => _trips = _trips.where((item) => item.tripId != trip.tripId).toList());
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$title을(를) 삭제했어요.')));
      return false; // removed from the list above
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('삭제하지 못했어요. 잠시 후 다시 시도해주세요.')),
        );
      }
      return false;
    }
  }

  /// 공유받은 여행 나가기: 먼저 물어보고, 확인하면 동행자에서 빠져요.
  /// 여행 주인에게는 "동행자가 나갔어요" 알림이 가요.
  Future<bool> _leaveTrip(TripListItem trip, String title) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('여행에서 나가시겠습니까?'),
        content: Text('$title에서 나가면 이 여행을 더 볼 수 없어요. 다시 함께하려면 새 초대 링크가 필요해요.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(dialogContext).pop(false), child: const Text('거절')),
          FilledButton(onPressed: () => Navigator.of(dialogContext).pop(true), child: const Text('확인')),
        ],
      ),
    );
    if (ok != true || !mounted) return false;
    try {
      await _tripService.leave(trip.tripId);
      if (ActiveTripService.tripId == trip.tripId) await ActiveTripService.clear();
      if (!mounted) return false;
      setState(() => _trips = _trips.where((item) => item.tripId != trip.tripId).toList());
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$title에서 나갔어요.')));
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('나가지 못했어요. 잠시 후 다시 시도해주세요.')),
        );
      }
    }
    return false;
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
        tripName: ActiveTripService.nameFor(title: trip.title, destination: trip.destination),
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
    appBar: AppBar(title: const Text('내 여행 일정')),
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
              final card = Material(
                color: Colors.white,
                borderRadius: BorderRadius.circular(16),
                child: ListTile(
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                  title: Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
                  subtitle: Text(
                    '${_date(trip.startDate)} ~ ${_date(trip.endDate)}'
                    '${trip.isShared ? ' · 공유받은 여행' : ''}',
                  ),
                  trailing: _opening == trip.tripId
                      ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.chevron_right_rounded),
                  onTap: () => _open(trip),
                ),
              );
              // Own trip: 삭제.  A shared trip belongs to its owner, so the
              // same swipe means 나가기 (leave) instead.
              return Dismissible(
                key: ValueKey('trip-${trip.tripId}'),
                direction: DismissDirection.startToEnd,
                background: Container(
                  alignment: Alignment.centerLeft,
                  padding: const EdgeInsets.only(left: 24),
                  decoration: BoxDecoration(
                    color: trip.isShared ? const Color(0xFF6B7280) : const Color(0xFFD9363E),
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(trip.isShared ? Icons.logout_rounded : Icons.delete_outline_rounded, color: Colors.white),
                      const SizedBox(width: 6),
                      Text(trip.isShared ? '나가기' : '삭제',
                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900)),
                    ],
                  ),
                ),
                confirmDismiss: (_) => trip.isShared ? _leaveTrip(trip, title) : _deleteTrip(trip, title),
                child: card,
              );
            },
          ),
    bottomNavigationBar: const AppBottomNavigation(selectedIndex: 3),
  );
}
