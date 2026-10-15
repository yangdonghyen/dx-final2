import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';
import '../../services/active_trip_service.dart';
import '../../services/plan_service.dart';
import '../../widgets/app_bottom_navigation.dart';
import 'itinerary_screen.dart';

/// "AI 코스 초안": the plan right after generation, before the user commits.
///
/// Shows each day as a timetable with the verified travel between stops.
/// 다시 만들기 asks the AI for a new draft of the same trip; 확정하기 confirms
/// the plan and opens the full itinerary screen.
class PlanDraftScreen extends StatefulWidget {
  const PlanDraftScreen({
    super.key,
    required this.plan,
    this.tripDates,
    this.transport = const {},
    this.places = const [],
    this.planService,
  });

  final GeneratedPlan plan;
  final DateTimeRange? tripDates;
  final Set<String> transport;
  final List<String> places;
  final PlanService? planService;

  @override
  State<PlanDraftScreen> createState() => _PlanDraftScreenState();
}

class _PlanDraftScreenState extends State<PlanDraftScreen> {
  late final PlanService _planService = widget.planService ?? PlanService();
  late GeneratedPlan _plan = widget.plan;
  int _day = 0;
  bool _redrafting = false;
  bool _confirming = false;

  GeneratedPlanDay? get _selectedDay =>
      _plan.days.isEmpty ? null : _plan.days[_day.clamp(0, _plan.days.length - 1)];

  static int? _minutes(String? value) {
    if (value == null || value.length < 5) return null;
    final hour = int.tryParse(value.substring(0, 2));
    final minute = int.tryParse(value.substring(3, 5));
    return hour == null || minute == null ? null : hour * 60 + minute;
  }

  static String _modeLabel(String? mode) => switch (mode) {
    'WALK' => '도보',
    'CAR' => '자차',
    'TAXI' => '택시',
    'PUBLIC_TRANSIT' => '대중교통',
    _ => '이동',
  };

  static IconData _modeIcon(String? mode) => switch (mode) {
    'WALK' => Icons.directions_walk_rounded,
    'PUBLIC_TRANSIT' => Icons.directions_bus_rounded,
    _ => Icons.directions_car_rounded,
  };

  static String _distance(int meters) =>
      meters >= 1000 ? '${(meters / 1000).toStringAsFixed(1)}km' : '${meters}m';

  /// "해수욕장 · 150분": the last category level and the planned stay.
  static String _detail(GeneratedPlanItem item) {
    final category = item.category?.split('>').last.trim();
    final label = switch (item.itemType) {
      'REST' => '휴식',
      'FREE_TIME' => '자유 시간',
      _ => category == null || category.isEmpty ? (item.itemType == 'MEAL' ? '식사' : '방문') : category,
    };
    final start = _minutes(item.startTime);
    final end = _minutes(item.endTime);
    final stay = start != null && end != null && end > start ? ' · ${end - start}분' : '';
    final note = item.note?.trim();
    return note != null && note.isNotEmpty ? '$label$stay · $note' : '$label$stay';
  }

  String _summary(GeneratedPlanDay day) {
    final stops = day.items.where((item) => item.placeId != null).length;
    var travel = 0;
    var walk = 0;
    for (final item in day.items) {
      final minutes = item.travelMinutesFromPrevious;
      if (minutes == null) continue;
      travel += minutes;
      if (item.transportModeFromPrevious == 'WALK') walk += minutes;
    }
    final name = ActiveTripService.name ?? (widget.places.isEmpty ? '여행' : '${widget.places.first} 여행');
    return [
      '$name 코스',
      '${day.day}일차',
      '$stops곳',
      if (travel > 0) '총 이동 약 $travel분',
      if (walk > 0) '도보 $walk분',
    ].join(' · ');
  }

  Future<void> _redraft() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('새 초안을 만들까요?'),
        content: const Text('AI가 같은 조건으로 코스를 다시 짜요. 1~3분 정도 걸려요.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('취소')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('다시 만들기')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _redrafting = true);
    try {
      final plan = await _planService.redraft(_plan.planId);
      if (!mounted) return;
      setState(() {
        _plan = plan;
        _day = 0;
        _redrafting = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _redrafting = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(planErrorMessage(error))));
    }
  }

  Future<void> _confirm() async {
    setState(() => _confirming = true);
    try {
      await _planService.confirm(_plan.planId);
      if (!mounted) return;
      await Navigator.of(context).pushReplacement(
        MaterialPageRoute(
          builder: (_) => ItineraryScreen(
            tripDates: widget.tripDates,
            transport: widget.transport,
            places: widget.places,
            generatedPlan: _plan,
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() => _confirming = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(planErrorMessage(error))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final day = _selectedDay;
    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(title: const Text('AI 코스 초안'), centerTitle: true),
      bottomNavigationBar: const AppBottomNavigation(selectedIndex: 0),
      body: _redrafting
          ? const Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  CircularProgressIndicator(),
                  SizedBox(height: 16),
                  Text('AI가 새 코스 초안을 짜고 있어요', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                  SizedBox(height: 6),
                  Text('1~3분 정도 걸릴 수 있어요.', style: TextStyle(color: Color(0xFF6B7280))),
                ],
              ),
            )
          : Column(
              children: [
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(20, 16, 20, 16),
                    children: [
                      const Text('AI 코스 초안', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w900)),
                      const SizedBox(height: 8),
                      if (day != null)
                        Text(_summary(day), style: const TextStyle(fontSize: 15, color: Color(0xFF4B5563), height: 1.4)),
                      if (_plan.days.length > 1) ...[
                        const SizedBox(height: 14),
                        Wrap(
                          spacing: 8,
                          children: [
                            for (var index = 0; index < _plan.days.length; index++)
                              ChoiceChip(
                                label: Text('${_plan.days[index].day}일차'),
                                selected: index == _day,
                                onSelected: (_) => setState(() => _day = index),
                              ),
                          ],
                        ),
                      ],
                      const SizedBox(height: 16),
                      const Text('방문 순서와 이동 정보를 확인해주세요.',
                          style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800)),
                      const SizedBox(height: 10),
                      if (day != null)
                        for (var index = 0; index < day.items.length; index++) ...[
                          // A rest has no place of its own, so no travel line to it.
                          if (index > 0 && (day.items[index].placeId != null || day.items[index].travelMinutesFromPrevious != null))
                            _TravelLeg(item: day.items[index]),
                          _StopCard(number: index + 1, item: day.items[index], detail: _detail(day.items[index])),
                        ],
                      if (_plan.warnings.isNotEmpty) ...[
                        const SizedBox(height: 14),
                        Text('확인이 필요한 일정 ${_plan.warnings.length}건은 확정 후 일정 화면에서 볼 수 있어요.',
                            style: const TextStyle(fontSize: 13, color: Color(0xFF9A3412))),
                      ],
                    ],
                  ),
                ),
                SafeArea(
                  top: false,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(20, 8, 20, 12),
                    child: Column(
                      children: [
                        SizedBox(
                          width: double.infinity,
                          child: OutlinedButton(
                            onPressed: _confirming ? null : _redraft,
                            style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                            child: const Text('다시 만들기'),
                          ),
                        ),
                        const SizedBox(height: 10),
                        SizedBox(
                          width: double.infinity,
                          child: FilledButton(
                            onPressed: _confirming ? null : _confirm,
                            style: FilledButton.styleFrom(
                              minimumSize: const Size.fromHeight(56),
                              backgroundColor: AppColors.primary,
                            ),
                            child: Text(_confirming ? '확정하는 중…' : '확정하기',
                                style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
    );
  }
}

class _StopCard extends StatelessWidget {
  const _StopCard({required this.number, required this.item, required this.detail});

  final int number;
  final GeneratedPlanItem item;
  final String detail;

  @override
  Widget build(BuildContext context) {
    final start = item.startTime != null && item.startTime!.length >= 5 ? item.startTime!.substring(0, 5) : '--:--';
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE5E7EB)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            decoration: BoxDecoration(color: const Color(0xFFEEF2FF), borderRadius: BorderRadius.circular(10)),
            child: Text(start, style: const TextStyle(fontWeight: FontWeight.w800, color: AppColors.primary)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('$number. ${item.name}', style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
                const SizedBox(height: 4),
                Text(detail, style: const TextStyle(fontSize: 13, color: Color(0xFF6B7280))),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _TravelLeg extends StatelessWidget {
  const _TravelLeg({required this.item});

  final GeneratedPlanItem item;

  @override
  Widget build(BuildContext context) {
    final minutes = item.travelMinutesFromPrevious;
    final meters = item.travelDistanceMetersFromPrevious;
    final mode = item.transportModeFromPrevious;
    final text = minutes == null
        ? (item.travelStatus == 'NONE' ? '같은 곳 · 이동 없음' : '이동 시간 확인 전')
        : [
            '${_PlanDraftScreenState._modeLabel(mode)} $minutes분',
            if (meters != null && meters > 0) _PlanDraftScreenState._distance(meters),
          ].join(' · ');
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      child: Row(
        children: [
          Icon(_PlanDraftScreenState._modeIcon(mode), size: 18, color: const Color(0xFF6B7280)),
          const SizedBox(width: 6),
          Text(text, style: const TextStyle(fontSize: 13, color: Color(0xFF4B5563), fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}
