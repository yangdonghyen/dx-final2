import 'dart:async';

import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';
import 'package:flutter/services.dart';
import 'package:kakao_flutter_sdk_share/kakao_flutter_sdk_share.dart';

import '../../core/theme/app_theme.dart';
import '../../services/active_trip_service.dart';
import '../../services/auth_service.dart';
import '../../services/notification_service.dart';
import '../../services/place_search_service.dart';
import '../../services/plan_service.dart';
import '../../services/preview_diff_summary.dart';
import '../../services/trip_service.dart';
import '../../widgets/ai_working_indicator.dart';
import '../../widgets/app_bottom_navigation.dart';
import '../../widgets/itinerary_route_map.dart';
import '../travel/today_travel_screen.dart';

enum _CompanionLoadState { noTrip, loading, loaded, error }

/// 홈에서 전체 일정 화면을 다시 열어도 선택한 일정을 유지합니다.
class ItinerarySession {
  List<_PlanStop>? _comfortableSchedule;
  List<_PlanStop>? _originalRecommendation;
  final List<int> _alternativeScheduleIds = [1, 2];
  int _activeScheduleId = 0;
  List<String> _appliedChanges = [];
  final Set<String> _appliedComfortReasons = {};
  int _selectedDay = 0;
  bool _satellite = false;
}

/// 생성된 여행 일정을 날짜별로 보여주고 순서 변경을 처리하는 화면입니다.
/// "확인이 필요한 일정" (validation notes) on the itinerary.  Was off for the
/// demo video; the checks still run and still block 확정 when critical.
const bool showPlanWarnings = true;

class ItineraryScreen extends StatefulWidget {
  const ItineraryScreen({
    super.key,
    this.session,
    this.tripDates,
    this.transport = const {},
    this.places = const [],
    this.changeNotice,
    this.generatedPlan,
    this.planService,
    this.weatherInstruction,
  });

  final ItinerarySession? session;

  /// AI(plans/generate)가 만든 실제 일정입니다. 있으면 날짜·장소를 여기서 만듭니다.
  final GeneratedPlan? generatedPlan;
  /// Injectable for preview-flow widget tests. Production uses [PlanService].
  final PlanService? planService;
  final DateTimeRange? tripDates;
  final Set<String> transport;
  final List<String> places;
  final String? changeNotice;

  /// TC-08: opened from the weather screen's plan 2/3.  Once the stored plan
  /// is shown, a WEATHER_CHANGE proposal is requested with this instruction;
  /// nothing changes until the user approves it.
  final String? weatherInstruction;

  List<String> get confirmedPlaces =>
      places.isNotEmpty ? places : ActiveTripService.places;

  @override
  State<ItineraryScreen> createState() => _ItineraryScreenState();
}

class _ItineraryScreenState extends State<ItineraryScreen> {
  bool hardOpen = false;
  bool alternativesOpen = false;
  bool rebuilding = false;
  bool _approvingPreview = false;
  bool _cancellingPreview = false;
  PlanRegenerationPreview? _pendingPreview;
  bool inviteLinkCreated = false;
  bool courseEditOpen = false;
  final Map<int, List<_PlanStop>> _manualSchedules = {};
  int? editingScheduleIndex;
  final TextEditingController _editTimeController = TextEditingController();
  final TextEditingController _editPlaceController = TextEditingController();
  final FocusNode _editPlaceFocusNode = FocusNode();
  // A place picked from the name suggestions (edit or add).
  PlaceSearchResult? _pickedPlace;
  // Bumped when a whole new plan is applied, so the list starts at the top.
  int _listRevision = 0;
  // The name the place field opened with; typing something else updates the
  // description live with the best match's address.
  String _placeNameAtOpen = '';
  // 장소 추가: the same panel as editing, with empty fields.
  bool _addingPlace = false;
  int _suggestRequest = 0;
  final PlaceSearchService _placeSearch = PlaceSearchService();
  final TextEditingController _editDescriptionController =
      TextEditingController();
  int selectedPlan = 0;
  final Set<String> selectedComfortReasons = {};
  final GlobalKey _selectedScheduleItemKey = GlobalKey();
  final ScrollController _dayScrollController = ScrollController();

  /// '전체' tab: every day on one vertical list (map folded by default).
  bool _showAllDays = false;
  bool _mapOpenInAllDays = false;
  bool _mapFolded = false;
  final Set<int> _foldedDays = <int>{};
  bool _hoursWarningsOpen = false;

  /// The server's repeated warning for places without verified hours.
  static const _unverifiedHoursWarning = 'Opening hours are not verified for this visit';
  late final ItinerarySession _session = widget.session ?? ItinerarySession();
  final TripService _tripService = TripService();
  late final PlanService _planService = widget.planService ?? PlanService();
  _CompanionLoadState _companionState = _CompanionLoadState.loading;
  List<TripCompanionSummary> _companions = const [];
  bool _creatingShareLink = false;
  TripShareLink? _viewLink;
  TripShareLink? _inviteLink;
  bool _viewLinkFailed = false;

  bool get satellite => _session._satellite;
  set satellite(bool value) => _session._satellite = value;
  int get selectedDay => _session._selectedDay;
  set selectedDay(int value) => _session._selectedDay = value;
  List<_PlanStop>? get comfortableSchedule => _session._comfortableSchedule;
  set comfortableSchedule(List<_PlanStop>? value) =>
      _session._comfortableSchedule = value;
  List<_PlanStop>? get originalRecommendation =>
      _session._originalRecommendation;
  set originalRecommendation(List<_PlanStop>? value) =>
      _session._originalRecommendation = value;
  List<int> get alternativeScheduleIds => _session._alternativeScheduleIds;
  int get activeScheduleId => _session._activeScheduleId;
  set activeScheduleId(int value) => _session._activeScheduleId = value;
  List<String> get appliedChanges => _session._appliedChanges;
  set appliedChanges(List<String> value) => _session._appliedChanges = value;
  Set<String> get appliedComfortReasons => _session._appliedComfortReasons;
  bool get hasAppliedComfortReasons => appliedComfortReasons.isNotEmpty;
  void _setSelectedDay(int value) {
    final nextDay = value.clamp(0, _days.length - 1);
    if (nextDay == selectedDay && !_showAllDays) return;
    setState(() {
      selectedDay = nextDay;
      _showAllDays = false;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_dayScrollController.hasClients) return;
      final target = (72.0 + nextDay * 88.0 - 88.0)
          .clamp(0.0, _dayScrollController.position.maxScrollExtent)
          .toDouble();
      _dayScrollController.animateTo(
        target,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  void dispose() {
    _dayScrollController.dispose();
    _editTimeController.dispose();
    _editPlaceController.dispose();
    _editPlaceFocusNode.dispose();
    _editDescriptionController.dispose();
    super.dispose();
  }

  void _startEditingScheduleItem(List<_PlanStop> schedule, int index) {
    final item = schedule[index];
    NotificationService.addEditStarted(place: item.place);
    setState(() {
      editingScheduleIndex = index;
      _addingPlace = false;
      _pickedPlace = null;
      _placeNameAtOpen = item.place;
      _editTimeController.text = item.time;
      _editPlaceController.text = item.place;
      _editDescriptionController.text = item.description;
    });
  }

  bool _isValidTime(String value) =>
      RegExp(r'^([01]\d|2[0-3]):[0-5]\d$').hasMatch(value);

  void _saveEditedSchedule(List<_PlanStop> schedule, int index) {
    final editedTime = _editTimeController.text.trim();
    if (editedTime.isNotEmpty && !_isValidTime(editedTime)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('시간은 00:00부터 23:59까지 입력할 수 있어요.')),
      );
      return;
    }

    final stop = schedule[index];
    final plan = _plan;
    if (plan != null && stop.itemId != null) {
      unawaited(_saveEditOnServer(plan, stop, editedTime));
      return;
    }

    final updated = List<_PlanStop>.from(schedule);
    updated[index] = updated[index].copyWith(
      time: editedTime.isEmpty ? updated[index].time : editedTime,
      place: _editPlaceController.text.trim().isEmpty
          ? updated[index].place
          : _editPlaceController.text.trim(),
      description: _editDescriptionController.text.trim().isEmpty
          ? updated[index].description
          : _editDescriptionController.text.trim(),
    );
    setState(() {
      _manualSchedules[selectedDay] = updated;
      editingScheduleIndex = null;
    });
    NotificationService.addEditCompleted(place: updated[index].place);
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('수정한 일정을 저장했어요.')));
  }

  /// Saves only what changed, then shows the server's itinerary.
  Future<void> _saveEditOnServer(GeneratedPlan plan, _PlanStop stop, String editedTime) async {
    final place = _editPlaceController.text.trim();
    final note = _editDescriptionController.text.trim();
    final picked = _pickedPlace;
    final replacing = picked != null && place != stop.place && picked.name != stop.place;
    if (stop.isPlace && place != stop.place && !replacing) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('장소 이름을 입력한 뒤 아래 목록에서 장소를 골라 주세요.')),
      );
      return;
    }
    final startTime = editedTime.isNotEmpty && editedTime != stop.time ? editedTime : null;
    final title = !replacing && !stop.isPlace && place.isNotEmpty && place != stop.place ? place : null;
    final changedNote = note != stop.description ? note : null;
    if (!replacing && startTime == null && title == null && changedNote == null) {
      // Nothing to send; the server would refuse an empty edit.
      setState(() => editingScheduleIndex = null);
      return;
    }
    try {
      if (replacing) {
        await _planService.replacePlace(plan.planId, stop.itemId!, picked.placeId);
      }
      if (startTime != null || title != null || changedNote != null) {
        await _planService.updateItem(
          plan.planId,
          stop.itemId!,
          startTime: startTime,
          title: title,
          note: changedNote,
        );
      }
      final latest = await _planService.get(plan.planId);
      if (!mounted) return;
      setState(() {
        _loadedPlan = latest;
        _applyPlan(latest);
        editingScheduleIndex = null;
      });
      NotificationService.addEditCompleted(place: stop.place);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('수정한 일정을 저장했어요. 동행자에게도 보여요.')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(planErrorMessage(error))));
    }
  }

  /// 코스 수정 중에는 카드를 왼쪽에서 오른쪽으로 밀어 장소를 뺄 수 있어요(먼저 물어봐요).
  Widget _swipeToRemove(_PlanStop stop, Widget card) {
    if (!courseEditOpen || _plan == null || stop.itemId == null) return card;
    return Dismissible(
      key: ValueKey('remove-stop-${stop.itemId}'),
      direction: DismissDirection.startToEnd,
      background: Container(
        alignment: Alignment.centerLeft,
        padding: const EdgeInsets.only(left: 24),
        margin: const EdgeInsets.only(bottom: 10),
        decoration: BoxDecoration(
          color: const Color(0xFFD9363E),
          borderRadius: BorderRadius.circular(18),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.delete_outline_rounded, color: Colors.white),
            SizedBox(width: 6),
            Text('삭제', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900)),
          ],
        ),
      ),
      // The card stays until the server confirms; the reload redraws the day.
      confirmDismiss: (_) async {
        await _removeStop(stop);
        return false;
      },
      child: card,
    );
  }

  /// Reloads the plan from the server after a course edit.
  Future<void> _reloadAfterEdit(GeneratedPlan plan, String message) async {
    final latest = await _planService.get(plan.planId);
    if (!mounted) return;
    setState(() {
      _loadedPlan = latest;
      _applyPlan(latest);
      editingScheduleIndex = null;
    });
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  /// 코스 수정: 한 곳을 일정에서 뺍니다(서버 저장, 동행자에게 알림).
  Future<void> _removeStop(_PlanStop stop) async {
    final plan = _plan;
    final itemId = stop.itemId;
    if (plan == null || itemId == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('계획을 삭제하시겠습니까?'),
        content: Text('${stop.place}을(를) 일정에서 삭제해요.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('거절')),
          FilledButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text('확인')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await _planService.deletePlace(plan.planId, itemId);
      NotificationService.addEditCompleted(place: stop.place);
      await _reloadAfterEdit(plan, '${stop.place}을(를) 뺐어요. 동행자에게도 보여요.');
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(planErrorMessage(error))));
    }
  }

  /// The trip's region ("부산 여행" → "부산"), used to rank suggestions.
  String get _tripRegion => (ActiveTripService.name ?? '').replaceAll('여행', '').trim();

  /// Places whose name looks like [query]; the trip's region comes first.
  Future<List<PlaceSearchResult>> _suggestPlaces(String query) async {
    final text = query.trim();
    final request = ++_suggestRequest;
    if (text.isEmpty) return const [];
    // Wait for the typing to pause so each keystroke is not a search.
    await Future<void>.delayed(const Duration(milliseconds: 350));
    if (request != _suggestRequest) return const [];
    final region = _tripRegion;
    final found = <PlaceSearchResult>[];
    try {
      if (region.isNotEmpty) found.addAll(await _placeSearch.search(text, region: region));
      if (found.length < 5) {
        final seen = found.map((place) => place.placeId).toSet();
        found.addAll((await _placeSearch.search(text)).where((place) => seen.add(place.placeId)));
      }
    } catch (error) {
      debugPrint('[CourseEdit] place suggestions failed: $error');
    }
    if (request != _suggestRequest) return const [];
    bool local(PlaceSearchResult place) =>
        region.isNotEmpty && '${place.region ?? ''} ${place.address ?? ''}'.contains(region);
    found.sort((a, b) => (local(a) ? 0 : 1).compareTo(local(b) ? 0 : 1));
    // Live: while the name is being changed, the best match becomes the
    // pick and its address goes into 설명 (another pick from the list wins).
    if (mounted && found.isNotEmpty && text != _placeNameAtOpen && _editPlaceController.text.trim() == text) {
      final best = found.first;
      setState(() {
        _pickedPlace = best;
        _editDescriptionController.text = best.address ?? best.region ?? '';
      });
    }
    return found.take(8).toList();
  }

  /// 장소 이름 칸: 쓰는 동안 비슷한 장소를 보여주고, 고르면 설명에 주소를 넣어요.
  Widget _placeNameField() => RawAutocomplete<PlaceSearchResult>(
    textEditingController: _editPlaceController,
    focusNode: _editPlaceFocusNode,
    optionsBuilder: (value) => _suggestPlaces(value.text),
    displayStringForOption: (place) => place.name,
    onSelected: (place) => setState(() {
      _pickedPlace = place;
      _editDescriptionController.text = place.address ?? place.region ?? '';
    }),
    fieldViewBuilder: (context, controller, focusNode, onSubmit) => TextField(
      controller: controller,
      focusNode: focusNode,
      decoration: InputDecoration(
        labelText: '장소',
        isDense: true,
        helperText: _tripRegion.isEmpty
            ? '이름을 쓰면 비슷한 장소를 보여줘요'
            : '이름을 쓰면 $_tripRegion 장소부터 보여줘요',
      ),
    ),
    optionsViewBuilder: (context, onSelected, options) => Align(
      alignment: Alignment.topLeft,
      child: Material(
        elevation: 6,
        borderRadius: BorderRadius.circular(12),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 280, maxWidth: 340),
          child: ListView.separated(
            padding: EdgeInsets.zero,
            shrinkWrap: true,
            itemCount: options.length,
            separatorBuilder: (_, _) => const Divider(height: 1),
            itemBuilder: (context, index) {
              final place = options.elementAt(index);
              return ListTile(
                dense: true,
                title: Text(place.name, style: const TextStyle(fontWeight: FontWeight.w800)),
                subtitle: Text(place.address ?? place.region ?? ''),
                onTap: () => onSelected(place),
              );
            },
          ),
        ),
      ),
    ),
  );

  void _openAddPanel() => setState(() {
    _addingPlace = true;
    editingScheduleIndex = null;
    _pickedPlace = null;
    _placeNameAtOpen = '';
    _editTimeController.clear();
    _editPlaceController.clear();
    _editDescriptionController.clear();
  });

  /// 장소 추가: 고른 장소를 그날 마지막 일정 뒤에 넣습니다(시간·설명은 선택).
  Future<void> _saveAddedPlace(List<_PlanStop> schedule) async {
    final plan = _plan;
    final withId = schedule.where((stop) => stop.itemId != null).toList();
    final picked = _pickedPlace;
    final time = _editTimeController.text.trim();
    if (plan == null || withId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('저장된 일정에서만 장소를 넣을 수 있어요.')),
      );
      return;
    }
    if (picked == null || _editPlaceController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('장소 이름을 입력한 뒤 목록에서 장소를 골라 주세요.')),
      );
      return;
    }
    if (time.isNotEmpty && !_isValidTime(time)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('시간은 00:00부터 23:59까지 입력할 수 있어요.')),
      );
      return;
    }
    final note = _editDescriptionController.text.trim();
    try {
      await _planService.addPlace(
        plan.planId,
        day: selectedDay + 1,
        afterItemId: withId.last.itemId!,
        placeId: picked.placeId,
        // A time inside another stop is fitted in by the server: it starts
        // when that stop ends and later stops move back.
        startTime: time.isEmpty ? null : time,
        note: note.isEmpty ? null : note,
      );
      NotificationService.addEditCompleted(place: picked.name);
      _addingPlace = false;
      await _reloadAfterEdit(
        plan,
        time.isEmpty
            ? '${picked.name}을(를) 넣었어요. 동행자에게도 보여요.'
            : '${picked.name}을(를) 넣었어요. 겹치는 시간은 앞뒤 일정에 맞춰 자동으로 조정했어요.',
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(planErrorMessage(error))));
    }
  }

  Widget _inlineAddPanel(List<_PlanStop> schedule) => Container(
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: const Color(0xFFEFF6FF),
      border: Border.all(color: const Color(0xFF2563EB)),
      borderRadius: BorderRadius.circular(16),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '장소 추가',
          style: TextStyle(fontWeight: FontWeight.w900, color: Color(0xFF1D4ED8)),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _editTimeController,
          keyboardType: TextInputType.number,
          inputFormatters: const [_TimeInputFormatter()],
          decoration: const InputDecoration(
            labelText: '시간',
            isDense: true,
            helperText: '원하는 시간을 쓰면 겹쳐도 앞뒤 일정에 맞춰 넣어요 · 비워두면 마지막 일정 뒤',
          ),
        ),
        const SizedBox(height: 8),
        _placeNameField(),
        const SizedBox(height: 8),
        TextField(
          controller: _editDescriptionController,
          decoration: const InputDecoration(labelText: '설명', isDense: true),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: () => setState(() => _addingPlace = false),
                child: const Text('취소'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: FilledButton(
                onPressed: () => _saveAddedPlace(schedule),
                style: FilledButton.styleFrom(backgroundColor: const Color(0xFF2563EB)),
                child: const Text('추가'),
              ),
            ),
          ],
        ),
      ],
    ),
  );

  Widget _inlineEditPanel(List<_PlanStop> schedule, int index) => Container(
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: const Color(0xFFEFF6FF),
      border: Border.all(color: const Color(0xFF2563EB)),
      borderRadius: BorderRadius.circular(16),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '일정 수정',
          style: TextStyle(
            fontWeight: FontWeight.w900,
            color: Color(0xFF1D4ED8),
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _editTimeController,
          keyboardType: TextInputType.number,
          inputFormatters: const [_TimeInputFormatter()],
          decoration: const InputDecoration(labelText: '시간', isDense: true),
        ),
        const SizedBox(height: 8),
        _placeNameField(),
        const SizedBox(height: 8),
        TextField(
          controller: _editDescriptionController,
          decoration: const InputDecoration(labelText: '설명', isDense: true),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            if (_plan != null && schedule[index].itemId != null) ...[
              Expanded(
                child: OutlinedButton(
                  onPressed: () => _removeStop(schedule[index]),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: const Color(0xFFD9363E),
                  ),
                  child: const Text('삭제'),
                ),
              ),
              const SizedBox(width: 8),
            ],
            Expanded(
              child: OutlinedButton(
                onPressed: () => setState(() => editingScheduleIndex = null),
                child: const Text('취소'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: FilledButton(
                onPressed: () => _saveEditedSchedule(schedule, index),
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFF2563EB),
                ),
                child: const Text('저장'),
              ),
            ),
          ],
        ),
      ],
    ),
  );

  String _comfortReasonLabel(String reason) =>
      _comfortOptions.firstWhere((option) => option.$1 == reason).$2;

  static const _comfortOptions = <(String, String)>[
    ('walking', '🚶 너무 많이 걸어요'),
    ('places', '📍 장소가 너무 많아요'),
    ('travel', '🚗 이동시간이 길어요'),
    ('rest', '☕ 쉬는 시간이 부족해요'),
  ];

  static const _naturePlaces = <(String, String, String, LatLng)>[
    ('경포호 산책', '🌿', '산책 · 휴식 중심', LatLng(37.7955, 128.8965)),
    ('강릉솔향수목원', '🌿', '숲길 산책 · 휴식', LatLng(37.7239, 128.8753)),
    ('안목해변 산책로', '🌿', '바닷길 산책 · 휴식', LatLng(37.7718, 128.9465)),
    ('경포대 숲길', '🌿', '숲길 산책 · 휴식', LatLng(37.7957, 128.8950)),
    ('오죽헌 정원', '🌿', '정원 산책 · 휴식', LatLng(37.7819, 128.8783)),
  ];

  static const _foodPlaces = <(String, String, String, LatLng)>[
    ('초당두부마을', '🍲', '식사 · 맛집 코스', LatLng(37.7900, 128.9173)),
    ('강릉 중앙시장', '🍲', '시장 먹거리 · 맛집', LatLng(37.7554, 128.8962)),
    ('강릉 커피거리', '🍲', '카페 · 디저트', LatLng(37.7704, 128.9440)),
    ('주문진 수산시장', '🍲', '해산물 맛집', LatLng(37.8947, 128.8294)),
    ('명주동 카페거리', '🍲', '카페 · 휴식', LatLng(37.7524, 128.8977)),
  ];

  /// 화면에 보여줄 AI 일정입니다. 생성 직후 전달받거나 저장된 plan_id로 불러옵니다.
  GeneratedPlan? _loadedPlan;
  bool _planLoading = false;
  String? _planError;

  /// True while the server is still generating this trip's first plan.
  bool _planStillGenerating = false;
  GeneratedPlan? get _plan => _loadedPlan ?? widget.generatedPlan;

  /// 생성된 일정이 있으면 날짜별 일정, 없으면 null입니다.
  List<List<_PlanStop>>? _generatedDays;
  Set<String> _generatedAttractions = {};

  void _applyPlan(GeneratedPlan plan) {
    _generatedAttractions = {
      for (final day in plan.days)
        for (final item in day.items)
          if (item.itemType == 'PLACE') item.name,
    };
    _generatedDays = plan.days.isEmpty
        ? null
        : plan.days
              .map(
                (day) => [
                  for (final item in day.items)
                    _PlanStop(
                      _generatedTime(item),
                      _generatedEmoji(item),
                      item.name,
                      _generatedDescription(item),
                      _generatedPosition(item),
                      travel: item.travelLabel,
                      travelMode: item.transportModeFromPrevious,
                      itemId: item.itemId,
                      isPlace: item.placeId != null,
                    ),
                ],
              )
              .toList();
  }

  // 시간이 없는 항목은 지어내지 않고 "--:--"로 보여줍니다.
  static String _generatedTime(GeneratedPlanItem item) =>
      item.startTime != null && item.startTime!.length >= 5
      ? item.startTime!.substring(0, 5)
      : '--:--';

  // 좌표가 없는 항목은 목록에만 두고 지도에서는 뺍니다.
  static LatLng? _generatedPosition(GeneratedPlanItem item) =>
      item.latitude != null && item.longitude != null
      ? LatLng(item.latitude!, item.longitude!)
      : null;

  static String _generatedDescription(GeneratedPlanItem item) {
    final note = item.note?.trim();
    if (note != null && note.isNotEmpty) return note;
    final details = [
      if (item.address != null && item.address!.isNotEmpty) item.address!,
      if (item.category != null && item.category!.isNotEmpty)
        _shortCategory(item.category!),
    ];
    return details.isEmpty
        ? _generatedTypeLabel(item.itemType)
        : details.join(' · ');
  }

  @override
  void initState() {
    super.initState();
    final plan = widget.generatedPlan;
    if (plan != null) {
      _applyPlan(plan);
      _requestWeatherPreviewOnce(plan);
    } else if (ActiveTripService.planId != null ||
        ActiveTripService.tripId != null) {
      _loadSavedPlan();
    }
  }

  /// 저장된 plan_id로 일정을 다시 불러옵니다 (홈에서 다시 열 때).
  /// plan_id를 모르면 trip_id로 서버에 저장된 일정을 찾습니다.
  Future<void> _loadSavedPlan() async {
    final planId = ActiveTripService.planId;
    final tripId = ActiveTripService.tripId;
    if (planId == null && tripId == null) return;
    setState(() {
      _planLoading = true;
      _planError = null;
      _planStillGenerating = false;
    });
    try {
      GeneratedPlan? plan;
      var generating = false;
      if (planId != null) {
        plan = await _planService.get(planId);
      } else {
        final lookup = await _planService.findForTrip(tripId!);
        plan = lookup.plan;
        generating = lookup.state == TripPlanState.generating;
      }
      if (!mounted) return;
      setState(() {
        _planLoading = false;
        _planStillGenerating = generating;
        if (plan != null) {
          _loadedPlan = plan;
          _applyPlan(plan);
        }
      });
      if (plan != null) _requestWeatherPreviewOnce(plan);
    } catch (error) {
      debugPrint('[Plan] load failed: $error');
      if (!mounted) return;
      setState(() {
        _planLoading = false;
        _planError = planErrorMessage(error);
      });
    }
  }

  Widget _planLoadState() => Scaffold(
    backgroundColor: AppColors.bg,
    appBar: AppBar(title: const Text('전체 일정')),
    body: Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 28),
        child: _planLoading
            ? const Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  CircularProgressIndicator(),
                  SizedBox(height: 16),
                  Text(
                    '일정을 불러오고 있어요',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900),
                  ),
                ],
              )
            : Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    '일정을 불러오지 못했어요',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _planError ?? '',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Color(0xFF4B5563)),
                  ),
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _loadSavedPlan,
                    style: FilledButton.styleFrom(
                      backgroundColor: AppColors.primary,
                      minimumSize: const Size.fromHeight(52),
                    ),
                    child: const Text('다시 시도'),
                  ),
                ],
              ),
      ),
    ),
    bottomNavigationBar: const AppBottomNavigation(selectedIndex: 0),
  );

  /// Kakao 카테고리("여행 > 관광,명소 > 해수욕장")의 마지막 단계만 보여줍니다.
  static String _shortCategory(String category) =>
      category
          .split('>')
          .map((part) => part.trim())
          .where((part) => part.isNotEmpty)
          .lastOrNull ??
      category;

  static String _generatedTypeLabel(String? itemType) => switch (itemType) {
    'MEAL' => '식사',
    'REST' => '휴식',
    'FREE_TIME' => '자유 시간',
    _ => '관광',
  };

  static String _generatedEmoji(GeneratedPlanItem item) {
    final category = (item.category ?? '').replaceAll(' ', '');
    if (category.contains('카페') || category.toUpperCase().contains('CE7')) {
      return '☕';
    }
    return switch (item.itemType) {
      'MEAL' => '🍽️',
      'REST' => '☕',
      'FREE_TIME' => '🚶',
      _ =>
        category.contains('숙박')
            ? '🏨'
            : category.contains('해수욕장') || category.contains('해변')
            ? '🌊'
            : category.contains('전시') ||
                  category.contains('미술관') ||
                  category.contains('박물관')
            ? '🏛️'
            : '📍',
    };
  }

  List<(String, String)> get _days {
    final generatedPlan = _plan;
    if (_generatedDays != null && generatedPlan != null) {
      return generatedPlan.days.map((day) {
        final date = day.visitDate;
        return (
          'DAY ${day.day}',
          date == null ? '' : '${date.month}월 ${date.day}일',
        );
      }).toList();
    }
    final start = DateUtils.dateOnly(
      widget.tripDates?.start ?? DateTime(2026, 9, 24),
    );
    final end = DateUtils.dateOnly(
      widget.tripDates?.end ?? DateTime(2026, 9, 26),
    );
    final dayCount = end.difference(start).inDays + 1;
    return List.generate(dayCount, (index) {
      final date = start.add(Duration(days: index));
      return ('DAY ${index + 1}', '${date.month}월 ${date.day}일');
    });
  }

  static const plans = <List<_PlanStop>>[
    [
      _PlanStop(
        '10:30',
        '🚉',
        '강릉역',
        '기차역에서 안목해변으로',
        LatLng(37.7643, 128.8990),
      ),
      _PlanStop(
        '11:20',
        '🌊',
        '안목해변',
        '산책 · 사진 · 휴식',
        LatLng(37.7718, 128.9465),
      ),
      _PlanStop('12:10', '☕', '강릉 커피거리', '30분 휴식', LatLng(37.7704, 128.9440)),
      _PlanStop('13:30', '🍽️', '중앙시장', '점심 식사', LatLng(37.7554, 128.8962)),
      _PlanStop('16:30', '🏨', '숙소 체크인', '여유롭게 이동', LatLng(37.7529, 128.8902)),
    ],
    [
      _PlanStop(
        '10:40',
        '🚉',
        '강릉역',
        '택시로 실내 장소 이동',
        LatLng(37.7643, 128.8990),
      ),
      _PlanStop(
        '11:40',
        '☕',
        '안목해변 카페',
        '실내 관람 전 휴식',
        LatLng(37.7713, 128.9460),
      ),
      _PlanStop('13:00', '🏛️', '강릉시립미술관', '실내 관람', LatLng(37.7660, 128.9029)),
      _PlanStop('14:30', '🍽️', '중앙시장', '점심 식사', LatLng(37.7554, 128.8962)),
      _PlanStop('16:30', '🏨', '숙소 체크인', '여유롭게 이동', LatLng(37.7529, 128.8902)),
    ],
    [
      _PlanStop('10:30', '🚉', '강릉역', '경포호로 이동', LatLng(37.7643, 128.8990)),
      _PlanStop(
        '11:30',
        '🌳',
        '경포호 산책로',
        '완만한 산책 · 벤치',
        LatLng(37.7955, 128.8965),
      ),
      _PlanStop('12:40', '🍽️', '중앙시장', '점심 식사', LatLng(37.7554, 128.8962)),
      _PlanStop('14:10', '☕', '안목 카페거리', '실내 휴식', LatLng(37.7704, 128.9440)),
      _PlanStop('16:20', '🏨', '숙소 체크인', '여유롭게 이동', LatLng(37.7529, 128.8902)),
    ],
  ];

  /// 생성된 일정이면 그날 기준 일정, 아니면 기존 추천 일정입니다.
  List<_PlanStop> get _recommendedSchedule {
    final generated = _generatedDays;
    if (generated == null) return plans[selectedPlan];
    return generated[selectedDay.clamp(0, generated.length - 1)];
  }

  bool _isAttraction(_PlanStop stop) => _plan != null
      ? _generatedAttractions.contains(stop.place)
      : const {
          '안목해변',
          '안목해변 카페',
          '강릉시립미술관',
          '경포호 산책로',
          '중앙시장',
          '안목 카페거리',
          '경포호 산책',
          '강릉솔향수목원',
          '안목해변 산책로',
          '경포대 숲길',
          '오죽헌 정원',
          '초당두부마을',
          '강릉 중앙시장',
          '강릉 커피거리',
          '주문진 수산시장',
          '명주동 카페거리',
        }.contains(stop.place);

  void _selectAlternative(int slotIndex) {
    final selectedId = alternativeScheduleIds[slotIndex];
    final previousId = activeScheduleId;
    final recommendation =
        originalRecommendation ??
        List<_PlanStop>.of(comfortableSchedule ?? plans[selectedPlan]);
    if (selectedId == 0) {
      setState(() {
        originalRecommendation = recommendation;
        comfortableSchedule = List<_PlanStop>.of(recommendation);
        alternativeScheduleIds[slotIndex] = previousId;
        activeScheduleId = 0;
        appliedChanges = ['처음 추천했던 일정을 다시 적용했어요.'];
        alternativesOpen = false;
        hardOpen = false;
        selectedComfortReasons.clear();
        appliedComfortReasons.clear();
      });
      _scrollToSelectedScheduleItem();
      return;
    }

    final nature = selectedId == 1;
    final options = nature ? _naturePlaces : _foodPlaces;
    var placeCursor = 0;
    final updated = recommendation.map((stop) {
      if (!_isAttraction(stop)) return stop;
      final option = options[placeCursor % options.length];
      placeCursor++;
      return stop.copyWith(
        place: option.$1,
        emoji: option.$2,
        description: option.$3,
        position: option.$4,
      );
    }).toList();

    if (placeCursor == 0) {
      updated.addAll([
        for (var i = 0; i < 2; i++)
          _PlanStop(
            i == 0 ? '13:30' : '15:00',
            options[i].$2,
            options[i].$1,
            options[i].$3,
            options[i].$4,
          ),
      ]);
      updated.sort((a, b) => a.time.compareTo(b.time));
    }

    final theme = nature ? '자연 중심 코스' : '맛집 집중 코스';
    setState(() {
      originalRecommendation = recommendation;
      comfortableSchedule = updated;
      alternativeScheduleIds[slotIndex] = previousId;
      activeScheduleId = selectedId;
      appliedChanges = [
        '$theme 장소 ${placeCursor == 0 ? 2 : placeCursor}곳을 일정과 지도에 반영했어요.',
      ];
      alternativesOpen = false;
      hardOpen = false;
      selectedComfortReasons.clear();
      appliedComfortReasons.clear();
    });
    _scrollToSelectedScheduleItem();
  }

  void _scrollToSelectedScheduleItem() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final selectedItemContext = _selectedScheduleItemKey.currentContext;
      if (selectedItemContext != null) {
        Scrollable.ensureVisible(
          selectedItemContext,
          duration: const Duration(milliseconds: 350),
          curve: Curves.easeOut,
          alignment: 0.15,
        );
      }
    });
  }

  List<_PlanStop> _makeComfortableSchedule(Set<String> reasons) {
    var result = List<_PlanStop>.of(_recommendedSchedule);
    if (reasons.contains('places')) {
      final attractions = result.where(_isAttraction).toList();
      final keep = (attractions.length / 2).ceil().clamp(1, attractions.length);
      var seen = 0;
      result = result.where((stop) {
        if (!_isAttraction(stop)) return true;
        return seen++ < keep;
      }).toList();
    }
    if (reasons.contains('travel')) {
      var keptAttraction = false;
      result = result.where((stop) {
        if (!_isAttraction(stop)) return true;
        if (keptAttraction) return false;
        keptAttraction = true;
        return true;
      }).toList();
    }
    if (reasons.contains('walking')) {
      result = result
          .map(
            (stop) => _isAttraction(stop)
                ? stop.copyWith(description: '택시·차량 이용 권장')
                : stop,
          )
          .toList();
    }
    if (reasons.contains('rest')) {
      final rests = <int, _PlanStop>{};
      for (var i = 0; i < result.length; i++) {
        final stop = result[i];
        if (!_isAttraction(stop) || !_hasTime(stop.time)) continue;
        final start = _minutes(stop.time);
        final end = i + 1 < result.length && _hasTime(result[i + 1].time)
            ? _minutes(result[i + 1].time)
            : 18 * 60;
        if (end - start < 20) continue;
        final restTime = start + (end - start) ~/ 2;
        rests[i] = _PlanStop(
          _clock(restTime),
          '☕',
          '관광 후 앉아서 쉬기',
          '추가 휴식',
          stop.position,
        );
      }
      // 각 휴식은 해당 관광지 바로 뒤에 넣습니다 (시간 미정 항목의 순서 유지).
      result = [
        for (var i = 0; i < result.length; i++) ...[
          result[i],
          if (rests[i] != null) rests[i]!,
        ],
      ];
    }
    return result;
  }

  List<String> _describeChanges(
    List<_PlanStop> before,
    List<_PlanStop> after,
    Set<String> reasons,
  ) {
    final beforeAttractions = before.where(_isAttraction).length;
    final afterAttractions = after.where(_isAttraction).length;
    final changes = <String>[];
    if (reasons.contains('walking')) {
      changes.add('관광 일정 $afterAttractions곳에 택시·차량 이용 권장을 표시했어요.');
    }
    if (reasons.contains('places')) {
      changes.add(
        beforeAttractions > afterAttractions
            ? '관광지를 $beforeAttractions곳에서 $afterAttractions곳으로 줄였어요.'
            : '관광지가 이미 적어 장소 수는 유지했어요.',
      );
    }
    if (reasons.contains('travel')) {
      changes.add(
        beforeAttractions > afterAttractions
            ? '하루 관광지를 $afterAttractions곳으로 줄여 장소 간 이동을 줄였어요.'
            : '추가 관광지 이동 없이 현재 일정을 유지해요.',
      );
    }
    if (reasons.contains('rest')) {
      final addedRests = after
          .where((stop) => stop.place == '관광 후 앉아서 쉬기')
          .length;
      changes.add(
        addedRests > 0
            ? '관광 후 앉아서 쉬는 시간을 $addedRests회 추가했어요.'
            : '일정 사이에 넣을 여유가 없어 휴식 일정을 추가하지 못했어요.',
      );
    }
    return changes;
  }

  bool _hasTime(String time) => RegExp(r'^\d{1,2}:\d{2}$').hasMatch(time);

  int _minutes(String time) {
    final parts = time.split(':').map(int.tryParse).toList();
    if (parts.length < 2 || parts[0] == null || parts[1] == null) return 0;
    return parts[0]! * 60 + parts[1]!;
  }

  String _clock(int minutes) =>
      '${(minutes ~/ 60).toString().padLeft(2, '0')}:${(minutes % 60).toString().padLeft(2, '0')}';

  void _clearComfortChanges() {
    if (!hasAppliedComfortReasons) return;
    setState(() {
      comfortableSchedule = null;
      originalRecommendation = null;
      alternativeScheduleIds[0] = 1;
      alternativeScheduleIds[1] = 2;
      activeScheduleId = 0;
      appliedChanges = [];
      appliedComfortReasons.clear();
      selectedComfortReasons.clear();
      hardOpen = false;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(
          '\uC801\uC6A9\uC911\uC774\uB358 \uC77C\uC815 \uC644\uD654 \uC870\uAC74\uC744 \uD574\uC9C0\uD588\uC5B4\uC694.',
        ),
      ),
    );
  }

  /// 고른 이유를 AI 재생성 요청 문장으로 바꿉니다.
  static const _comfortInstructions = {
    'walking': 'Reduce walking: keep consecutive stops close together.',
    'places': 'Visit fewer places per day.',
    'travel': 'Shorten travel time: keep each day within one nearby area.',
    'rest': 'Add more rest or free time between activities.',
  };

  bool _weatherPreviewRequested = false;

  void _requestWeatherPreviewOnce(GeneratedPlan plan) {
    final instruction = widget.weatherInstruction;
    if (instruction == null || _weatherPreviewRequested) return;
    _weatherPreviewRequested = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _requestPreview(plan, reason: 'WEATHER_CHANGE', instruction: instruction);
      }
    });
  }

  /// Requests a pending change only; the displayed itinerary stays unchanged.
  Future<void> _regenerateEasier(
    GeneratedPlan plan,
    Set<String> reasons,
  ) => _requestPreview(
    plan,
    reason: 'USER_FATIGUE',
    instruction: [
      'The traveler said the schedule is too tiring.',
      for (final reason in _comfortOptions.map((option) => option.$1))
        if (reasons.contains(reason)) _comfortInstructions[reason]!,
    ].join(' '),
    feedbackCodes: reasons.toList()..sort(),
  );

  Future<void> _requestPreview(
    GeneratedPlan plan, {
    required String reason,
    required String instruction,
    List<String> feedbackCodes = const <String>[],
  }) async {
    setState(() => rebuilding = true);
    try {
      final preview = await _planService.createRegenerationPreview(
        plan.planId,
        reason: reason,
        instruction: instruction,
        feedbackCodes: feedbackCodes,
      );
      if (!mounted) return;
      setState(() {
        rebuilding = false;
        _pendingPreview = preview;
        hardOpen = false;
        selectedComfortReasons.clear();
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('수정안을 만들었어요. 확인 후에만 기존 일정이 변경됩니다.')),
      );
    } catch (error) {
      debugPrint('[Plan] regenerate failed: $error');
      if (!mounted) return;
      setState(() => rebuilding = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(planErrorMessage(error))));
    }
  }

  String _diffLabel(Map<String, dynamic> row) {
    return previewDiffSummary(row);
  }

  List<Map<String, dynamic>> _proposedItems(PlanRegenerationPreview preview) {
    final rawItems = preview.proposedItinerary['items'];
    return rawItems is List
        ? rawItems
              .whereType<Map>()
              .map((item) => Map<String, dynamic>.from(item))
              .toList()
        : const <Map<String, dynamic>>[];
  }

  /// The preview contract has no anchor field. The screen already owns the
  /// user's selected-place names, so only label a selected place as preserved
  /// when it is actually present in the server-proposed itinerary.
  List<String> _preservedAnchors(PlanRegenerationPreview preview) {
    final proposedNames = _proposedItems(preview)
        .map((item) => item['title']?.toString())
        .whereType<String>()
        .where((name) => name.isNotEmpty)
        .toSet();
    return widget.confirmedPlaces
        .where(proposedNames.contains)
        .toSet()
        .toList(growable: false);
  }

  String _proposedItemLabel(Map<String, dynamic> item) {
    // 2026-10-20 / 09:00:00 → 10/20 / 09:00 so the line reads like the rest of the app.
    final rawDate = item['visit_date']?.toString() ?? '';
    final dateParts = rawDate.split('-');
    final date = dateParts.length == 3
        ? '${int.tryParse(dateParts[1]) ?? dateParts[1]}/${int.tryParse(dateParts[2]) ?? dateParts[2]}'
        : rawDate;
    String? clock(Object? value) {
      final text = value?.toString() ?? '';
      return text.length >= 5 ? text.substring(0, 5) : (text.isEmpty ? null : text);
    }
    final time = [clock(item['start_time']), clock(item['end_time'])].whereType<String>();
    final prefix = [
      if (date.isNotEmpty) date,
      if (time.isNotEmpty) time.join('~'),
    ].join(' ');
    final title = item['title']?.toString() ?? '일정 항목';
    final label = prefix.isEmpty ? title : '$prefix · $title';
    // Previews carry no travel_status, so only known minutes are shown.
    final travel = planTravelLabel(
      mode: item['transport_mode_from_previous']?.toString(),
      minutes: item['travel_minutes_from_previous'],
    );
    return travel == null ? label : '$label ($travel 이동)';
  }

  Future<void> _approvePreview(GeneratedPlan plan) async {
    final preview = _pendingPreview;
    if (preview == null || _approvingPreview) return;
    setState(() => _approvingPreview = true);
    try {
      await _planService.approveRegenerationPreview(
        plan.planId,
        preview.previewId,
      );
      final latest = await _planService.get(plan.planId);
      if (!mounted) return;
      setState(() {
        _loadedPlan = latest;
        _applyPlan(latest);
        _pendingPreview = null;
        _manualSchedules.clear();
        _approvingPreview = false;
        _listRevision++; // the new plan opens at its top
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('수정안이 적용되었어요. 최신 일정을 표시합니다.')),
      );
    } catch (error) {
      // Do not retry an ambiguous approve. Fetch the authoritative plan first.
      try {
        final latest = await _planService.get(plan.planId);
        if (mounted) {
          setState(() {
            _loadedPlan = latest;
            _applyPlan(latest);
          });
        }
      } catch (_) {}
      if (!mounted) return;
      setState(() => _approvingPreview = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(planErrorMessage(error))));
    }
  }

  Future<void> _cancelPreview(GeneratedPlan plan) async {
    final preview = _pendingPreview;
    if (preview == null || _cancellingPreview || _approvingPreview) return;
    setState(() => _cancellingPreview = true);
    try {
      await _planService.cancelRegenerationPreview(
        plan.planId,
        preview.previewId,
      );
      if (!mounted) return;
      setState(() {
        _pendingPreview = null;
        _cancellingPreview = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('수정안을 취소했어요. 기존 일정은 유지됩니다.')),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() => _cancellingPreview = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(planErrorMessage(error))));
    }
  }

  Future<void> _rebuild() async {
    if (selectedComfortReasons.isEmpty || rebuilding) return;
    final reasons = Set<String>.of(selectedComfortReasons);
    final plan = _plan;
    if (plan != null) {
      await _regenerateEasier(plan, reasons);
      return;
    }
    setState(() => rebuilding = true);
    await Future<void>.delayed(const Duration(milliseconds: 1100));
    if (!mounted) return;
    final updatedSchedule = _makeComfortableSchedule(reasons);
    final changes = _describeChanges(
      _recommendedSchedule,
      updatedSchedule,
      reasons,
    );
    setState(() {
      rebuilding = false;
      comfortableSchedule = updatedSchedule;
      originalRecommendation = null;
      alternativeScheduleIds[0] = 1;
      alternativeScheduleIds[1] = 2;
      activeScheduleId = 0;
      appliedChanges = changes;
      appliedComfortReasons
        ..clear()
        ..addAll(reasons);
      hardOpen = false;
      alternativesOpen = false;
      selectedComfortReasons.clear();
    });
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('더 편안한 일정으로 다시 만들었어요.')));
  }

  List<_PlanStop> _buildConfirmedDay(List<_PlanStop> schedule, int dayIndex) {
    if (widget.confirmedPlaces.isEmpty) return schedule;
    final places = widget.confirmedPlaces;
    final isFirstDay = dayIndex == 0;
    final isLastDay = dayIndex == _days.length - 1;
    final primary = places[dayIndex % places.length];
    final secondary = places[(dayIndex + 1) % places.length];
    final middleLabels = switch (dayIndex % 4) {
      1 => <String>[
        primary,
        '$primary 문화 · 역사 탐방',
        '점심 식사 · 지역 맛집',
        secondary == primary ? '$primary 골목 산책' : secondary,
        '저녁 식사 · 로컬 맛집',
      ],
      2 => <String>[
        primary,
        '$primary 자연 · 전망 산책',
        '점심 식사 · 지역 맛집',
        secondary == primary ? '$primary 체험 활동' : secondary,
        '저녁 식사 · 특색 메뉴',
      ],
      3 => <String>[
        primary,
        '$primary 시장 · 지역 체험',
        '점심 식사 · 지역 맛집',
        secondary == primary ? '$primary 카페 거리' : secondary,
        '저녁 식사 · 야간 명소',
      ],
      _ => <String>[
        primary,
        '$primary 전시 · 문화 체험',
        '점심 식사 · 지역 맛집',
        secondary == primary ? '$primary 쇼핑 · 산책' : secondary,
        '저녁 식사 · 로컬 맛집',
      ],
    };
    final middleDescriptions = switch (dayIndex % 4) {
      1 => const [
        '대표 명소 · 관람 90분',
        '문화 · 역사 관람 80분',
        '점심 식사 60분',
        '골목 · 거리 산책 90분',
        '저녁 식사 70분',
      ],
      2 => const [
        '대표 명소 · 관람 90분',
        '자연 · 전망 감상 80분',
        '점심 식사 60분',
        '지역 체험 90분',
        '저녁 식사 70분',
      ],
      3 => const [
        '대표 명소 · 관람 90분',
        '시장 · 로컬 체험 80분',
        '점심 식사 60분',
        '카페 · 자유 시간 80분',
        '야간 식사 70분',
      ],
      _ => const [
        '대표 명소 · 관람 90분',
        '전시 · 문화 관람 80분',
        '점심 식사 60분',
        '쇼핑 · 산책 80분',
        '저녁 식사 70분',
      ],
    };
    final labels = isLastDay
        ? <String>[
            '숙소 체크아웃',
            primary,
            '점심 식사 · 지역 맛집',
            '기념품 · 마지막 산책',
            '귀가 · 출발',
          ]
        : isFirstDay
        ? <String>[
            '숙소 체크인 · 짐 보관',
            primary,
            '점심 식사 · 지역 맛집',
            secondary == primary ? '$primary 주변 산책' : secondary,
            '숙소 복귀 · 휴식',
          ]
        : middleLabels;
    final descriptions = isLastDay
        ? const [
            '체크아웃 · 짐 정리',
            '대표 명소 · 관람 90분',
            '점심 식사 60분',
            '자유 시간 · 기념품',
            '교통편 탑승',
          ]
        : isFirstDay
        ? const [
            '체크인 · 짐 보관 후 가볍게 출발',
            '대표 명소 · 관람 90분',
            '점심 식사 60분',
            '지역 산책 · 체험 90분',
            '숙소로 돌아와 짐 정리 · 휴식',
          ]
        : middleDescriptions;
    final times = isFirstDay
        ? const ['10:00', '11:00', '13:00', '14:30', '18:30']
        : const ['10:00', '11:30', '13:00', '15:00', '18:30'];
    const emojis = ['📍', '🚶', '🍽️', '🎨', '🏨'];
    return List.generate(
      schedule.length,
      (index) => schedule[index].copyWith(
        time: times[index.clamp(0, times.length - 1)],
        place: labels[index.clamp(0, labels.length - 1)],
        emoji: isFirstDay && index == 0
            ? '🏨'
            : isFirstDay && index == 4
            ? '🛏️'
            : isLastDay && index == 0
            ? '🧳'
            : isLastDay && index == 4
            ? '🚉'
            : emojis[index.clamp(0, emojis.length - 1)],
        description: descriptions[index.clamp(0, descriptions.length - 1)],
      ),
    );
  }

  /// Travel into [stop] from the item before it, as the server sent it.
  /// Nothing is shown when the server sent no travel for this item.
  Widget _travelLine(_PlanStop stop) {
    final label = stop.travel;
    if (label == null) return const SizedBox(height: 10);
    final icon = switch (stop.travelMode) {
      'CAR' => Icons.directions_car_rounded,
      'PUBLIC_TRANSIT' => Icons.directions_bus_rounded,
      'WALK' => Icons.directions_walk_rounded,
      'TAXI' => Icons.local_taxi_rounded,
      _ => Icons.more_vert_rounded,
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 0, 14, 10),
      child: Row(
        children: [
          Icon(icon, size: 17, color: const Color(0xFF6B7280)),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(
              fontSize: 13,
              color: Color(0xFF6B7280),
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  /// 서버에 저장된 이 여행의 동행자(trip_companions)를 불러옵니다.
  Future<void> _loadCompanions(StateSetter setSheetState) async {
    final tripId = ActiveTripService.tripId;
    if (tripId == null) {
      setSheetState(() => _companionState = _CompanionLoadState.noTrip);
      return;
    }
    setSheetState(() => _companionState = _CompanionLoadState.loading);
    try {
      final companions = await _tripService.companions(tripId);
      if (!mounted) return;
      setSheetState(() {
        _companions = companions;
        _companionState = _CompanionLoadState.loaded;
      });
    } catch (error) {
      debugPrint('[Share] companions load failed: $error');
      if (!mounted) return;
      setSheetState(() => _companionState = _CompanionLoadState.error);
    }
  }

  /// 서버에서 공유 링크를 만듭니다. 이 화면에서 만든 링크는 다시 씁니다.
  /// 저장된 여행이 없거나 실패하면 null입니다.
  Future<TripShareLink?> _createShareLink({
    required bool invite,
    bool quiet = false,
  }) async {
    final cached = invite ? _inviteLink : _viewLink;
    final expiresAt = cached?.expiresAt;
    if (cached != null &&
        (expiresAt == null || expiresAt.isAfter(DateTime.now()))) {
      return cached;
    }
    final tripId = ActiveTripService.tripId;
    if (tripId == null) {
      if (!quiet) _showShareMessage('저장된 여행이 없어 링크를 만들 수 없어요.');
      return null;
    }
    try {
      final link = await _tripService.createShareLink(tripId, invite: invite);
      if (invite) {
        _inviteLink = link;
      } else {
        _viewLink = link;
      }
      return link;
    } catch (error) {
      debugPrint('[Share] link create failed: $error');
      if (!quiet) _showShareMessage('링크를 만들지 못했어요. 다시 시도해주세요.');
      return null;
    }
  }

  /// 시트를 열면 링크 공유 칸에 보여줄 내 보기 전용 링크를 준비합니다.
  Future<void> _loadViewLink(StateSetter setSheetState) async {
    final link = await _createShareLink(invite: false, quiet: true);
    if (!mounted) return;
    setSheetState(() => _viewLinkFailed = link == null);
  }

  void _showShareMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  /// 링크를 카카오톡으로 보냅니다. 카카오톡이 없으면 카카오 웹 공유 화면을 엽니다.
  /// [inviteToken]이 있으면 앱을 바로 여는 "앱에서 참여하기" 버튼을 함께 보냅니다.
  Future<void> _sendToKakaoTalk({
    required TripShareLink link,
    required String text,
    required String buttonTitle,
    String? inviteToken,
  }) async {
    final url = Uri.parse(link.url);
    final webLink = Link(webUrl: url, mobileWebUrl: url);
    final template = TextTemplate(
      text: text,
      link: webLink,
      // An invite carries one button only: 앱에서 참여하기.
      buttons: [
        if (inviteToken == null) Button(title: buttonTitle, link: webLink),
        if (inviteToken != null)
          Button(
            title: '앱에서 참여하기',
            link: Link(
              androidExecutionParams: {'invite_token': inviteToken},
              iosExecutionParams: {'invite_token': inviteToken},
            ),
          ),
      ],
    );
    try {
      if (await ShareClient.instance.isKakaoTalkSharingAvailable()) {
        await ShareClient.instance.shareDefault(template: template);
      } else {
        final webShareUrl = await WebSharerClient.instance.makeDefaultUrl(
          template: template,
        );
        await launchBrowser(webShareUrl);
      }
    } catch (error) {
      debugPrint('[Share] KakaoTalk share failed: $error');
      _showShareMessage('카카오톡으로 공유하지 못했어요. 카카오 설정을 확인해주세요.');
    }
  }

  String get _tripLabel {
    final places = widget.confirmedPlaces;
    return places.isEmpty ? '여행' : '${places.first} 여행';
  }

  /// 동행자 초대 링크를 카카오톡으로 보냅니다.
  Future<void> _inviteViaKakaoTalk() async {
    final link = await _createShareLink(invite: true);
    if (link == null) return;
    await _sendToKakaoTalk(
      link: link,
      text: '$_tripLabel에 함께 가요! 초대 링크로 일정을 확인해주세요.',
      buttonTitle: '초대 확인하기',
      inviteToken: Uri.parse(link.url).pathSegments.last,
    );
    if (mounted) setState(() => inviteLinkCreated = true);
  }

  /// 동행자 초대 링크를 클립보드에 복사합니다.
  Future<void> _copyInviteLink() async {
    final link = await _createShareLink(invite: true);
    if (link == null) return;
    await Clipboard.setData(ClipboardData(text: link.url));
    if (!mounted) return;
    setState(() => inviteLinkCreated = true);
    _showShareMessage('초대 링크를 복사했어요. 원하는 곳에 붙여넣어 보내세요.');
  }

  Future<void> _runShareAction(
    StateSetter setSheetState,
    Future<void> Function() action,
  ) async {
    if (_creatingShareLink) return;
    setSheetState(() => _creatingShareLink = true);
    try {
      await action();
    } finally {
      if (mounted) setSheetState(() => _creatingShareLink = false);
    }
  }

  static const _avatarColors = [
    Color(0xFF6C63FF),
    Color(0xFF00A6A6),
    Color(0xFFFF8A65),
  ];

  static String _relationLabel(TripCompanionSummary companion) {
    if (companion.joinedByInvite) return '초대로 참여';
    return switch (companion.relation) {
      'FATHER' => '아버지',
      'MOTHER' => '어머니',
      'SPOUSE' => '배우자',
      'CHILD' => '자녀',
      'FRIEND' => '친구',
      _ => '동행자',
    };
  }

  /// 여행 만들기에서 고른 동행자 중 아직 초대 링크로 참여하지 않은 사람.
  /// (고른 동행자는 이름표일 뿐이고, 계정은 초대로 참여해야 연결돼요.)
  List<String> get _pendingCompanionNames {
    final joined = _companions.map((companion) => companion.name.trim()).toSet();
    return ActiveTripService.companions
        .map((companion) => companion.name.trim())
        .where((name) => name.isNotEmpty && !joined.contains(name))
        .toSet()
        .toList();
  }

  /// 서버에 저장된 동행자를 보여줍니다.
  Widget _companionsPreview() => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: const Color(0xFFF7F8FC),
      borderRadius: BorderRadius.circular(18),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.groups_rounded, color: AppColors.primary),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                _companionState != _CompanionLoadState.loaded
                    ? '현재 동행자'
                    : _companions.isEmpty
                    ? (_pendingCompanionNames.isEmpty
                        ? '등록된 동행자가 없어요'
                        : '아직 참여한 동행자가 없어요')
                    : '현재 동행자 ${_companions.length}명',
                style: const TextStyle(fontWeight: FontWeight.w900),
              ),
            ),
          ],
        ),
        const SizedBox(height: 13),
        switch (_companionState) {
          _CompanionLoadState.loading => const Text(
            '동행자를 불러오고 있어요',
            style: TextStyle(fontSize: 13, color: Color(0xFF6B7280)),
          ),
          _CompanionLoadState.noTrip => const Text(
            '저장된 여행이 없어 동행자를 확인할 수 없어요',
            style: TextStyle(fontSize: 13, color: Color(0xFF6B7280)),
          ),
          _CompanionLoadState.error => const Text(
            '동행자 정보를 확인할 수 없어요',
            style: TextStyle(fontSize: 13, color: Color(0xFF6B7280)),
          ),
          _CompanionLoadState.loaded when _companions.isEmpty =>
            _pendingCompanionNames.isEmpty
                ? const Text(
                    '아직 동행자가 없어요. 친구를 초대해보세요.',
                    style: TextStyle(fontSize: 13, color: Color(0xFF6B7280)),
                  )
                : Text(
                    '${_pendingCompanionNames.join(', ')}님은 아직 초대 전이에요. '
                    '아래 친구 초대하기로 링크를 보내면 함께 일정을 볼 수 있어요.',
                    style: const TextStyle(fontSize: 13, color: Color(0xFF6B7280)),
                  ),
          _CompanionLoadState.loaded => Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              for (var index = 0; index < _companions.length; index++)
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircleAvatar(
                      radius: 18,
                      backgroundColor:
                          _avatarColors[index % _avatarColors.length],
                      child: Text(
                        _companions[index].name.isEmpty
                            ? '?'
                            : _companions[index].name.characters.first,
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    const SizedBox(width: 6),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _companions[index].name,
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        Text(
                          _relationLabel(_companions[index]),
                          style: const TextStyle(
                            fontSize: 11,
                            color: Color(0xFF6B7280),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
            ],
          ),
        },
      ],
    ),
  );

  /// 서버에 저장된 동행자를 보여주고 카카오톡 공유와 초대 링크 복사를 제공합니다.
  void _showShareSheet() {
    var sheetOpen = true;
    var companionsRequested = false;
    _companionState = _CompanionLoadState.loading;
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (context, setSheetState) {
          // 시트가 닫힌 뒤 끝난 요청은 화면 상태만 바꾸고 시트는 건드리지 않습니다.
          void setSheet(VoidCallback update) =>
              sheetOpen ? setSheetState(update) : update();
          if (!companionsRequested) {
            companionsRequested = true;
            WidgetsBinding.instance.addPostFrameCallback((_) {
              _loadCompanions(setSheet);
              _loadViewLink(setSheet);
            });
          }
          return SafeArea(
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.sizeOf(sheetContext).height * 0.84,
              ),
              child: SingleChildScrollView(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Expanded(
                            child: Text(
                              '여행 일정 공유',
                              style: TextStyle(
                                fontSize: 22,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                          ),
                          IconButton(
                            onPressed: () => Navigator.of(sheetContext).pop(),
                            icon: const Icon(Icons.close_rounded),
                            tooltip: '닫기',
                          ),
                        ],
                      ),
                      const SizedBox(height: 2),
                      const Text(
                        '동행자에게 일정 링크를 보내보세요.',
                        style: TextStyle(color: Color(0xFF6B7280)),
                      ),
                      const SizedBox(height: 18),
                      _companionsPreview(),
                      const SizedBox(height: 12),
                      _viewLinkCard(),
                      const SizedBox(height: 10),
                      _inviteCard(
                        onKakao: () =>
                            _runShareAction(setSheet, _inviteViaKakaoTalk),
                        onCopy: () =>
                            _runShareAction(setSheet, _copyInviteLink),
                      ),
                      if (_creatingShareLink) ...[
                        const SizedBox(height: 12),
                        const LinearProgressIndicator(),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          );
        },
      ),
    ).whenComplete(() => sheetOpen = false);
  }

  Widget _shareIcon(IconData icon) => Container(
    width: 44,
    height: 44,
    decoration: BoxDecoration(
      color: AppColors.soft,
      borderRadius: BorderRadius.circular(14),
    ),
    child: Icon(icon, color: AppColors.primary),
  );

  /// 내 보기 전용 링크를 보여주기만 합니다. 보내기는 아래 친구 초대하기에서 합니다.
  Widget _viewLinkCard() {
    final link = _viewLink;
    final linkText = link != null
        ? link.url
        : _viewLinkFailed
        ? '링크를 만들지 못했어요. 공유 창을 다시 열어주세요.'
        : '내 링크를 만들고 있어요';
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF7F8FC),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        children: [
          _shareIcon(Icons.link_rounded),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '링크 공유하기',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 3),
                const Text(
                  '일정을 보기 전용으로 볼 수 있는 내 링크예요',
                  style: TextStyle(fontSize: 13, color: Color(0xFF6B7280)),
                ),
                const SizedBox(height: 8),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 8,
                  ),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: const Color(0xFFE5E7EB)),
                  ),
                  child: Text(
                    linkText,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 12,
                      color: link != null
                          ? AppColors.primary
                          : const Color(0xFF6B7280),
                      fontWeight: link != null
                          ? FontWeight.w700
                          : FontWeight.w500,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// 친구 초대: 왼쪽은 카카오톡으로 보내기, 오른쪽은 링크 복사입니다.
  Widget _inviteCard({
    required VoidCallback onKakao,
    required VoidCallback onCopy,
  }) => Container(
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: const Color(0xFFF7F8FC),
      borderRadius: BorderRadius.circular(18),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            _shareIcon(Icons.person_add_alt_1_rounded),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '친구 초대하기',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    inviteLinkCreated
                        ? '초대 링크가 준비되었어요 · 7일 동안 쓸 수 있어요'
                        : '동행자로 초대할 링크를 보내요',
                    style: const TextStyle(
                      fontSize: 13,
                      color: Color(0xFF6B7280),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: SizedBox(
                height: 52,
                child: FilledButton.icon(
                  onPressed: onKakao,
                  style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFFFEE500),
                    foregroundColor: const Color(0xFF191919),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                  ),
                  icon: const Icon(Icons.chat_bubble_rounded, size: 20),
                  label: const FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text(
                      '카카오톡',
                      maxLines: 1,
                      style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: SizedBox(
                height: 52,
                child: OutlinedButton.icon(
                  onPressed: onCopy,
                  style: OutlinedButton.styleFrom(
                    backgroundColor: Colors.white,
                    foregroundColor: AppColors.primary,
                    side: const BorderSide(color: Color(0xFFD1D5DB)),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                  ),
                  icon: const Icon(Icons.copy_rounded, size: 20),
                  label: const FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text(
                      '링크 복사',
                      maxLines: 1,
                      style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ],
    ),
  );

  /// 코스 수정 모드에서 장소 추가와 저장 동작을 제공하는 하단 제어 영역입니다.
  Widget _courseEditActions(List<_PlanStop> schedule) => Container(
    margin: const EdgeInsets.only(top: 10),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: const Color(0xFFFFF5F5),
      borderRadius: BorderRadius.circular(16),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '코스 수정 중',
          style: TextStyle(
            fontWeight: FontWeight.w900,
            color: Color(0xFFD9363E),
          ),
        ),
        const SizedBox(height: 4),
        const Text(
          '연필로 시간·장소를 바꾸고, 카드를 오른쪽으로 밀면 장소를 삭제해요. 장소 추가로 새 장소를 넣어보세요.',
          style: TextStyle(fontSize: 12, color: Color(0xFF6B7280)),
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: _openAddPanel,
                child: const Text('장소 추가'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: FilledButton(
                onPressed: () {
                  // Each change is saved on the server as it is made;
                  // this only leaves edit mode.
                  setState(() {
                    courseEditOpen = false;
                    editingScheduleIndex = null;
                  });
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('수정한 코스를 저장했어요.')),
                  );
                },
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFF202020),
                ),
                child: const Text('저장'),
              ),
            ),
          ],
        ),
      ],
    ),
  );

  /// 전체 알림에서 이동했을 때 방금 확인할 일정 변경 내용을 강조합니다.
  Widget _changeNoticeBanner(String message) => Container(
    margin: const EdgeInsets.only(bottom: 14),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: const Color(0xFFFFF5F5),
      border: Border.all(color: const Color(0xFFFECACA)),
      borderRadius: BorderRadius.circular(16),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(
          Icons.notifications_active_rounded,
          color: Color(0xFFD9363E),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '변경된 일정 확인',
                style: TextStyle(fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 4),
              Text(
                message,
                style: const TextStyle(fontSize: 13, color: Color(0xFF4B5563)),
              ),
            ],
          ),
        ),
      ],
    ),
  );
  /// What the server's plan check found (meal times, food-only days,
  /// repeated areas, unverified long legs). Shown as stored, never hidden.
  /// Places of the current plan without verified opening hours, in plan order.
  List<String> _unverifiedHoursPlaces() {
    final names = <String>[];
    for (final day in _plan?.days ?? const <GeneratedPlanDay>[]) {
      for (final item in day.items) {
        if (item.placeId != null && item.validationStatus == 'WARNING' && !names.contains(item.name)) {
          names.add(item.name);
        }
      }
    }
    return names.isEmpty ? ['상세 장소 정보는 각 일정에서 확인해주세요'] : names;
  }

  Widget _planWarningsCard(List<String> warnings) => Container(
    margin: const EdgeInsets.only(bottom: 12),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: const Color(0xFFFFF7ED),
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: const Color(0xFFFED7AA)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '확인이 필요한 일정',
          style: TextStyle(fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 6),
        // Every other warning stays visible as sent by the server.
        for (final warning in warnings.where((w) => w != _unverifiedHoursWarning))
          Padding(
            padding: const EdgeInsets.only(top: 3),
            child: Text(
              '• $warning',
              style: const TextStyle(fontSize: 13, color: Color(0xFF9A3412)),
            ),
          ),
        if (warnings.contains(_unverifiedHoursWarning)) ...[
          InkWell(
            onTap: () => setState(() => _hoursWarningsOpen = !_hoursWarningsOpen),
            child: Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      '• 영업시간이 확인되지 않은 장소 '
                      '${warnings.where((w) => w == _unverifiedHoursWarning).length}곳 · 방문 전 영업 여부를 확인해주세요',
                      style: const TextStyle(fontSize: 13, color: Color(0xFF9A3412)),
                    ),
                  ),
                  Icon(
                    _hoursWarningsOpen ? Icons.expand_less_rounded : Icons.expand_more_rounded,
                    size: 18,
                    color: const Color(0xFF9A3412),
                  ),
                ],
              ),
            ),
          ),
          if (_hoursWarningsOpen)
            const Padding(
              padding: EdgeInsets.only(left: 12, top: 4),
              child: Text(
                '확인 표시가 붙은 장소 (영업시간 미확인 포함)',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Color(0xFF9A3412)),
              ),
            ),
          if (_hoursWarningsOpen)
            for (final place in _unverifiedHoursPlaces())
              Padding(
                padding: const EdgeInsets.only(left: 12, top: 2),
                child: Text(
                  '- $place',
                  style: const TextStyle(fontSize: 12, color: Color(0xFF9A3412)),
                ),
              ),
        ],
      ],
    ),
  );

  /// Shown instead of sample stops when this trip has no AI plan to show.
  Widget _noPlanState() => Scaffold(
    backgroundColor: AppColors.bg,
    appBar: AppBar(title: const Text('전체 일정')),
    body: Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              _planStillGenerating ? '일정을 아직 만들고 있어요' : '아직 만들어진 일정이 없어요',
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: 8),
            Text(
              _planStillGenerating
                  ? '잠시 후 다시 확인해주세요.'
                  : '여행 만들기에서 AI 일정을 생성하면 여기에 표시돼요.',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Color(0xFF4B5563)),
            ),
            if (_planStillGenerating) ...[
              const SizedBox(height: 20),
              FilledButton(
                onPressed: _loadSavedPlan,
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.primary,
                  minimumSize: const Size.fromHeight(52),
                ),
                child: const Text('다시 확인'),
              ),
            ],
          ],
        ),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    if (_planLoading || _planError != null) return _planLoadState();
    // Never fall back to the built-in sample course as if it were this trip.
    if (_generatedDays == null) return _noPlanState();
    if (rebuilding && _plan != null) {
      return const PopScope(
        canPop: false,
        child: Scaffold(
          backgroundColor: AppColors.bg,
          body: SafeArea(
            child: AiWorkingIndicator(
              title: 'AI가 일정을 다시 짜고 있어요',
              messages: AiWorkingIndicator.easierMessages,
            ),
          ),
        ),
      );
    }
    if (selectedDay >= _days.length) selectedDay = _days.length - 1;
    final day = _days[selectedDay];
    final aiDays = _generatedDays;
    final baseSchedule = aiDays != null
        ? (hasAppliedComfortReasons
              ? _makeComfortableSchedule(appliedComfortReasons)
              : aiDays[selectedDay])
        : comfortableSchedule ??
              plans[(selectedPlan + selectedDay) % plans.length];
    final generatedSchedule = aiDays != null
        ? baseSchedule
        : _buildConfirmedDay(baseSchedule, selectedDay);
    final schedule = _manualSchedules[selectedDay] ?? generatedSchedule;
    final firstAttractionIndex = schedule.indexWhere(_isAttraction);
    // Keep the last buttons (코스 수정, 일정이 힘들어요) clear of the system
    // gesture area and the bottom navigation when scrolled to the end.
    final listPadding = EdgeInsets.fromLTRB(
      20, 16, 20, 40 + MediaQuery.viewPaddingOf(context).bottom,
    );
    // While the keyboard is up (typing in 코스 수정), the map and day tabs
    // make room for the list instead of overflowing.
    final typing = MediaQuery.viewInsetsOf(context).bottom > 0;
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        child: Column(
          children: [
            if (!typing)
              _mapHeader(
                _showAllDays
                    ? [for (var index = 0; index < _days.length; index++) ..._scheduleForDay(index, schedule)]
                    : schedule,
                _showAllDays ? ('전체', '${_days.length}일 일정') : day,
              ),
            if (!typing) _daySelector(),
            Expanded(
              child: _showAllDays
                  ? ListView(
                      padding: listPadding,
                      children: [
                        _actionCard(),
                        if (showPlanWarnings && _plan != null && _plan!.warnings.isNotEmpty)
                          _planWarningsCard(_plan!.warnings),
                        if (_pendingPreview != null && _plan != null)
                          _previewCard(_plan!),
                        if (widget.changeNotice != null)
                          _changeNoticeBanner(widget.changeNotice!),
                        if (appliedChanges.isNotEmpty) _appliedChangesCard(),
                        for (var index = 0; index < _days.length; index++)
                          _allDaysSection(index, _scheduleForDay(index, schedule)),
                      ],
                    )
                  : GestureDetector(
                      // Swipe the list (not the map) to the previous/next day.
                      behavior: HitTestBehavior.translucent,
                      onHorizontalDragEnd: (details) {
                        final velocity = details.primaryVelocity ?? 0;
                        if (velocity.abs() < 300) return;
                        _setSelectedDay(selectedDay + (velocity < 0 ? 1 : -1));
                      },
                      child: ListView(
                // A new day, or a newly applied plan (계획 2 → 이 일정으로
                // 변경), opens at its top, not at the last offset.
                key: ValueKey('day-list-$selectedDay-$_listRevision'),
                padding: listPadding,
                children: [
                  _actionCard(),
                  if (showPlanWarnings && _plan != null && _plan!.warnings.isNotEmpty)
                    _planWarningsCard(_plan!.warnings),
                  if (_pendingPreview != null && _plan != null)
                    _previewCard(_plan!),
                  if (widget.changeNotice != null)
                    _changeNoticeBanner(widget.changeNotice!),
                  if (appliedChanges.isNotEmpty) _appliedChangesCard(),
                  if (alternativesOpen && _plan == null) _alternativePlans(),
                  const SizedBox(height: 18),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      Expanded(
                        child: Text(
                          day.$1,
                          style: const TextStyle(
                            fontSize: 23,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                      ),
                      Semantics(
                        button: true,
                        label: '여행 일정 공유하기',
                        child: SizedBox(
                          width: 136,
                          height: 50,
                          child: Material(
                            color: const Color(0xFFD9363E),
                            elevation: 3,
                            shadowColor: const Color(0x55D9363E),
                            borderRadius: BorderRadius.circular(14),
                            child: InkWell(
                              onTap: _showShareSheet,
                              borderRadius: BorderRadius.circular(14),
                              child: const Center(
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Icon(
                                      Icons.ios_share_rounded,
                                      size: 19,
                                      color: Colors.white,
                                    ),
                                    SizedBox(width: 8),
                                    Text(
                                      '공유하기',
                                      style: TextStyle(
                                        color: Colors.white,
                                        fontSize: 15,
                                        fontWeight: FontWeight.w900,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'AI 추천 코스 · ${day.$2}',
                    style: const TextStyle(color: Color(0xFF6B7280)),
                  ),
                  const SizedBox(height: 10),
                  for (var index = 0; index < schedule.length; index++) ...[
                    _swipeToRemove(
                      schedule[index],
                      _ScheduleItem(
                        key: index == firstAttractionIndex
                            ? _selectedScheduleItemKey
                            : null,
                        index: index + 1,
                        data: schedule[index],
                        editable: courseEditOpen,
                        editingBy: editingScheduleIndex == index ? '나' : null,
                        editingDetail: editingScheduleIndex == index
                            ? '일정 내용'
                            : null,
                        onEdit: courseEditOpen
                            ? () => _startEditingScheduleItem(schedule, index)
                            : null,
                      ),
                    ),
                    if (editingScheduleIndex == index)
                      _inlineEditPanel(schedule, index),
                    // Local comfort changes drop or add stops, so the
                    // server's travel times no longer match them.
                    if (index < schedule.length - 1)
                      hasAppliedComfortReasons
                          ? const SizedBox(height: 10)
                          : _travelLine(schedule[index + 1]),
                  ],
                  if (courseEditOpen && _addingPlace) _inlineAddPanel(schedule),
                  const SizedBox(height: 8),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: () => setState(() {
                        courseEditOpen = !courseEditOpen;
                        if (!courseEditOpen) {
                          editingScheduleIndex = null;
                          _addingPlace = false;
                        }
                      }),
                      icon: Icon(
                        courseEditOpen
                            ? Icons.edit_rounded
                            : Icons.edit_outlined,
                      ),
                      label: Text(courseEditOpen ? '코스 수정 중' : '코스 수정'),
                    ),
                  ),
                  if (courseEditOpen) _courseEditActions(schedule),
                  const SizedBox(height: 10),
                  FilledButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => TodayTravelScreen(
                          title: '${day.$1} · ${day.$2} 일정',
                          itinerary: [
                            for (final stop in schedule)
                              TodayScheduleEntry(
                                time: stop.time,
                                emoji: stop.emoji,
                                place: stop.place,
                                description: stop.description,
                                position: stop.position,
                                // Same rule as the travel line above: only the
                                // server's travel, and none once local comfort
                                // changes no longer match it.
                                travel: hasAppliedComfortReasons
                                    ? null
                                    : stop.travel,
                                travelMode: stop.travelMode,
                              ),
                          ],
                        ),
                      ),
                    ),
                    style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(54),
                      backgroundColor: AppColors.primary,
                    ),
                    child: const Text('오늘의 여행 보기'),
                  ),
                ],
              ),
                    ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: const AppBottomNavigation(selectedIndex: 0),
    );
  }

  /// One day's stops, the same source the DAY tab uses for that day.
  List<_PlanStop> _scheduleForDay(int index, List<_PlanStop> selectedSchedule) {
    if (index == selectedDay) return selectedSchedule;
    final manual = _manualSchedules[index];
    if (manual != null) return manual;
    final aiDays = _generatedDays;
    if (aiDays != null) return aiDays[index];
    return _buildConfirmedDay(plans[(selectedPlan + index) % plans.length], index);
  }

  /// A foldable day section of the '전체' tab (read-only; edit on its DAY tab).
  Widget _allDaysSection(int index, List<_PlanStop> schedule) {
    final day = _days[index];
    final folded = _foldedDays.contains(index);
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            onTap: () => setState(() => folded ? _foldedDays.remove(index) : _foldedDays.add(index)),
            borderRadius: BorderRadius.circular(12),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(
                children: [
                  Text(day.$1, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '${day.$2} · ${schedule.length}개 일정',
                      style: const TextStyle(color: Color(0xFF6B7280)),
                    ),
                  ),
                  TextButton(
                    onPressed: () => _setSelectedDay(index),
                    child: const Text('상세'),
                  ),
                  Icon(folded ? Icons.expand_more_rounded : Icons.expand_less_rounded),
                ],
              ),
            ),
          ),
          if (!folded)
            for (var item = 0; item < schedule.length; item++) ...[
              _ScheduleItem(index: item + 1, data: schedule[item], editable: false),
              if (item < schedule.length - 1)
                hasAppliedComfortReasons && index == selectedDay
                    ? const SizedBox(height: 10)
                    : _travelLine(schedule[item + 1]),
            ],
        ],
      ),
    );
  }

  Widget _mapHeader(List<_PlanStop> schedule, (String, String) day) =>
      Container(
        color: Colors.white,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 8),
              child: Row(
                children: [
                  IconButton(
                    onPressed: () => Navigator.of(context).maybePop(),
                    icon: const Icon(Icons.chevron_left_rounded),
                    tooltip: '이전',
                  ),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          // "강릉 여행 일정": the trip's own name when this is the
                          // saved trip, not its first stop ("정동진 해변 여행").
                          _plan != null && _plan!.planId == ActiveTripService.planId && ActiveTripService.name != null
                              ? '${ActiveTripService.name} 일정'
                              : widget.places.isEmpty
                              ? '전체 일정'
                              : '${widget.places.first} 여행 일정',
                          style: TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        Text(
                          '${day.$1} · ${day.$2}',
                          style: const TextStyle(
                            fontSize: 13,
                            color: Color(0xFF6B7280),
                          ),
                        ),
                      ],
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.all(3),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF3F4F6),
                      borderRadius: BorderRadius.circular(11),
                    ),
                    child: Row(
                      children: [
                        _mapTypeButton(
                          '일반',
                          !satellite,
                          () => setState(() => satellite = false),
                        ),
                        _mapTypeButton(
                          '위성',
                          satellite,
                          () => setState(() => satellite = true),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            if (_showAllDays ? _mapOpenInAllDays : !_mapFolded)
              ItineraryRouteMap(
                points: schedule
                    .where((item) => item.position != null)
                    .map((item) => ItineraryMapPoint(item.place, item.position!))
                    .toList(),
                satellite: satellite,
                height: 208,
                label: '번호는 아래 일정 순서와 같아요.',
              ),
            InkWell(
              onTap: () => setState(() {
                if (_showAllDays) {
                  _mapOpenInAllDays = !_mapOpenInAllDays;
                } else {
                  _mapFolded = !_mapFolded;
                }
              }),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(
                      (_showAllDays ? _mapOpenInAllDays : !_mapFolded)
                          ? Icons.expand_less_rounded
                          : Icons.expand_more_rounded,
                      size: 20,
                      color: const Color(0xFF6B7280),
                    ),
                    Text(
                      (_showAllDays ? _mapOpenInAllDays : !_mapFolded) ? '지도 접기' : '지도 펼치기',
                      style: const TextStyle(fontSize: 12, color: Color(0xFF6B7280), fontWeight: FontWeight.w700),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      );
  Widget _mapTypeButton(String label, bool selected, VoidCallback onTap) =>
      TextButton(
        onPressed: onTap,
        style: TextButton.styleFrom(
          minimumSize: const Size(48, 36),
          padding: const EdgeInsets.symmetric(horizontal: 10),
          foregroundColor: selected
              ? AppColors.primary
              : const Color(0xFF4B5563),
          backgroundColor: selected ? Colors.white : Colors.transparent,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
        child: Text(
          label,
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800),
        ),
      );

  Widget _daySelector() => Container(
    height: 70,
    color: Colors.white,
    child: Row(
      children: [
        IconButton(
          onPressed: selectedDay == 0 || _showAllDays
              ? null
              : () => _setSelectedDay(selectedDay - 1),
          icon: const Icon(Icons.chevron_left_rounded),
          tooltip: '이전 날짜',
        ),
        Expanded(
          child: SingleChildScrollView(
            controller: _dayScrollController,
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                SizedBox(
                  width: 72,
                  child: TextButton(
                    onPressed: () => setState(() => _showAllDays = true),
                    style: TextButton.styleFrom(
                      foregroundColor: _showAllDays ? AppColors.primary : const Color(0xFF6B7280),
                      backgroundColor: _showAllDays ? AppColors.soft : Colors.transparent,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                    ),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Text('전체', style: TextStyle(fontWeight: FontWeight.w900)),
                        const SizedBox(height: 2),
                        Text('${_days.length}일', style: const TextStyle(fontSize: 11)),
                      ],
                    ),
                  ),
                ),
                ..._days.asMap().entries.map((entry) {
                final selected = !_showAllDays && selectedDay == entry.key;
                return SizedBox(
                  width: 88,
                  child: TextButton(
                    onPressed: () => _setSelectedDay(entry.key),
                    style: TextButton.styleFrom(
                      foregroundColor: selected
                          ? AppColors.primary
                          : const Color(0xFF6B7280),
                      backgroundColor: selected
                          ? AppColors.soft
                          : Colors.transparent,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14),
                      ),
                    ),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          entry.value.$1,
                          style: const TextStyle(fontWeight: FontWeight.w900),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          entry.value.$2,
                          style: const TextStyle(fontSize: 11),
                        ),
                      ],
                    ),
                  ),
                );
              }),
              ],
            ),
          ),
        ),
        IconButton(
          onPressed: selectedDay == _days.length - 1 || _showAllDays
              ? null
              : () => _setSelectedDay(selectedDay + 1),
          icon: const Icon(Icons.chevron_right_rounded),
          tooltip: '다음 날짜',
        ),
      ],
    ),
  );
  Widget _previewCard(GeneratedPlan plan) {
    final preview = _pendingPreview!;
    final proposedItems = _proposedItems(preview);
    final preservedAnchors = _preservedAnchors(preview);
    final expires = preview.expiresAt == null
        ? null
        : '${preview.expiresAt!.month}/${preview.expiresAt!.day} ${preview.expiresAt!.hour.toString().padLeft(2, '0')}:${preview.expiresAt!.minute.toString().padLeft(2, '0')}';
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED),
        border: Border.all(color: const Color(0xFFFDBA74)),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Row(
            children: [
              Icon(Icons.compare_arrows_rounded, color: Color(0xFFC2410C)),
              SizedBox(width: 8),
              Text(
                '일정 수정안',
                style: TextStyle(fontWeight: FontWeight.w900, fontSize: 17),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            '아직 기존 일정에는 적용되지 않았어요.',
            style: TextStyle(color: Color(0xFF7C2D12)),
          ),
          if (expires != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                '만료: $expires',
                style: const TextStyle(fontSize: 12, color: Color(0xFF9A3412)),
              ),
            ),
          if (preview.validationStatus == 'UNKNOWN')
            const Padding(
              padding: EdgeInsets.only(top: 8),
              child: Text(
                '방문 가능 여부 또는 이동시간에 미확인 정보가 있을 수 있어요.',
                style: TextStyle(fontSize: 12, color: Color(0xFF9A3412)),
              ),
            ),
          const SizedBox(height: 12),
          if (preview.diff.isEmpty)
            const Text('실제 일정 항목 변경은 없어요.', style: TextStyle(fontSize: 13))
          else
            ...preview.diff.map(
              (row) => Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text(
                  '• ${_diffLabel(row)}',
                  style: const TextStyle(fontSize: 13),
                ),
              ),
            ),
          if (proposedItems.isNotEmpty) ...[
            const SizedBox(height: 10),
            const Text(
              '수정 후 일정',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
            ),
            const SizedBox(height: 4),
            ...proposedItems.map(
              (item) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  '· ${_proposedItemLabel(item)}',
                  style: const TextStyle(fontSize: 12),
                ),
              ),
            ),
          ],
          if (preservedAnchors.isNotEmpty) ...[
            const SizedBox(height: 10),
            const Text(
              '\uBCF4\uC874\uB41C \uD544\uC218 \uC7A5\uC18C',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
            ),
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: preservedAnchors
                  .map((name) => Chip(label: Text(name)))
                  .toList(),
            ),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _approvingPreview || _cancellingPreview
                      ? null
                      : () => _cancelPreview(plan),
                  child: Text(_cancellingPreview ? '취소 중...' : '취소'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: FilledButton(
                  onPressed: _approvingPreview || _cancellingPreview
                      ? null
                      : () => _approvePreview(plan),
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.primary,
                  ),
                  child: Text(_approvingPreview ? '적용 중...' : '이 일정으로 변경'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _actionCard() => Container(
    decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(20),
      border: Border.all(color: const Color(0xFFE5E7EB)),
    ),
    child: Column(
      children: [
        ListTile(
          onTap: () => setState(() {
            hardOpen = !hardOpen;
            if (hardOpen) alternativesOpen = false;
          }),
          leading: const Icon(
            Icons.sentiment_dissatisfied_outlined,
            color: AppColors.primary,
          ),
          title: const Text(
            '일정이 힘들어요',
            style: TextStyle(fontWeight: FontWeight.w900),
          ),
          subtitle: hasAppliedComfortReasons
              ? Text(
                  '\uC801\uC6A9 \uC911 · ${appliedComfortReasons.map(_comfortReasonLabel).join(', ')}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: AppColors.primary),
                )
              : null,
          trailing: Icon(hardOpen ? Icons.expand_less : Icons.expand_more),
        ),
        if (hardOpen)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  '어떤 점이 힘드세요? 선택한 이유에 맞춰 일정을 새로 바꿔요.',
                  style: TextStyle(color: Color(0xFF4B5563)),
                ),
                const SizedBox(height: 12),
                GridView.builder(
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  itemCount: _comfortOptions.length,
                  gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 2,
                    mainAxisExtent: 44,
                    crossAxisSpacing: 8,
                    mainAxisSpacing: 8,
                  ),
                  itemBuilder: (context, index) {
                    final option = _comfortOptions[index];
                    final selected = selectedComfortReasons.contains(option.$1);
                    return InkWell(
                      onTap: () => setState(() {
                        if (selected) {
                          selectedComfortReasons.remove(option.$1);
                        } else {
                          selectedComfortReasons.add(option.$1);
                        }
                      }),
                      borderRadius: BorderRadius.circular(22),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 9),
                        decoration: BoxDecoration(
                          color: selected
                              ? const Color(0xFFFFEDD5)
                              : Colors.white,
                          borderRadius: BorderRadius.circular(22),
                          border: Border.all(
                            color: selected
                                ? const Color(0xFFFB923C)
                                : const Color(0xFFE5E7EB),
                          ),
                        ),
                        child: Row(
                          children: [
                            SizedBox(
                              width: 18,
                              child: selected
                                  ? const Icon(
                                      Icons.check_circle,
                                      size: 16,
                                      color: Color(0xFFC2410C),
                                    )
                                  : null,
                            ),
                            const SizedBox(width: 3),
                            Expanded(
                              child: Text(
                                option.$2,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: selected
                                      ? FontWeight.w800
                                      : FontWeight.w600,
                                  color: selected
                                      ? const Color(0xFF9A3412)
                                      : const Color(0xFF4B5563),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: rebuilding || selectedComfortReasons.isEmpty
                      ? null
                      : _rebuild,
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.primary,
                  ),
                  child: Text(
                    rebuilding ? 'AI가 일정을 다시 만들고 있어요...' : '일정 다시 만들기',
                  ),
                ),
              ],
            ),
          ),
        if (_plan == null) const Divider(height: 1),
        if (_plan == null)
          ListTile(
            onTap: () => setState(() {
              alternativesOpen = !alternativesOpen;
              hardOpen = false;
            }),
            leading: const Icon(
              Icons.compare_arrows_outlined,
              color: AppColors.primary,
            ),
            title: const Text(
              '다른 일정 보기',
              style: TextStyle(fontWeight: FontWeight.w900),
            ),
            trailing: Icon(
              alternativesOpen ? Icons.expand_less : Icons.expand_more,
            ),
          ),
      ],
    ),
  );

  Widget _appliedChangesCard() => Container(
    margin: const EdgeInsets.only(top: 12),
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: const Color(0xFFEFF6FF),
      borderRadius: BorderRadius.circular(18),
      border: Border.all(color: const Color(0xFFBFDBFE)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.check_circle, color: AppColors.primary, size: 19),
            const SizedBox(width: 7),
            Text(
              hasAppliedComfortReasons
                  ? '\uC77C\uC815 \uBD80\uB2F4 \uC644\uD654\uAC00 \uC801\uC6A9 \uC911\uC774\uC5D0\uC694'
                  : '\uC77C\uC815 \uBCC0\uACBD\uC774 \uBC18\uC601\uB418\uC5C8\uC5B4\uC694',
              style: const TextStyle(fontWeight: FontWeight.w900),
            ),
          ],
        ),
        const SizedBox(height: 8),
        if (hasAppliedComfortReasons) ...[
          const Text(
            '\uC801\uC6A9 \uC911\uC778 \uC870\uAC74',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: appliedComfortReasons
                .map(
                  (reason) => Chip(
                    label: Text(_comfortReasonLabel(reason)),
                    backgroundColor: Colors.white,
                    side: const BorderSide(color: Color(0xFF93C5FD)),
                    visualDensity: VisualDensity.compact,
                  ),
                )
                .toList(),
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: _clearComfortChanges,
              icon: const Icon(Icons.restart_alt_rounded),
              label: const Text('\uC801\uC6A9 \uD574\uC9C0'),
            ),
          ),
          const SizedBox(height: 10),
        ],
        ...appliedChanges.map(
          (change) => Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('•  '),
                Expanded(child: Text(change)),
              ],
            ),
          ),
        ),
      ],
    ),
  );

  Widget _alternativePlans() => Padding(
    padding: const EdgeInsets.only(top: 10),
    child: Column(
      children: alternativeScheduleIds
          .asMap()
          .entries
          .map(
            (entry) => Card(
              elevation: 0,
              child: InkWell(
                onTap: () => _selectAlternative(entry.key),
                borderRadius: BorderRadius.circular(12),
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              entry.value == 0
                                  ? '✨ 다른 일정 ${entry.key + 1} · 추천 일정'
                                  : entry.value == 1
                                  ? '🌿 다른 일정 1 · 자연 중심 코스'
                                  : '🍲 다른 일정 2 · 맛집 집중 코스',
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              textAlign: TextAlign.left,
                              style: const TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              entry.value == 0
                                  ? '처음 추천해드린 일정으로 돌아가요.'
                                  : entry.value == 1
                                  ? '산책과 휴식 시간을 넉넉하게 반영해요.'
                                  : '식사와 카페 방문 중심으로 구성해요.',
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              textAlign: TextAlign.left,
                              style: const TextStyle(
                                fontSize: 12,
                                color: Color(0xFF6B7280),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 82,
                        child: Center(
                          child: Text(
                            '선택하기 →',
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              color: AppColors.primary,
                              fontSize: 12,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          )
          .toList(),
    ),
  );
}

class _ScheduleItem extends StatelessWidget {
  const _ScheduleItem({
    super.key,
    required this.index,
    required this.data,
    this.editable = false,
    this.editingBy,
    this.editingDetail,
    this.onEdit,
  });

  final int index;
  final _PlanStop data;
  final bool editable;
  final String? editingBy;
  final String? editingDetail;
  final VoidCallback? onEdit;

  bool get isEditing => editingBy != null;

  // 이름을 노출하지 않아도 카드 색으로 수정자를 구분합니다.
  Color get _editingColor => switch (editingBy) {
    '나' => const Color(0xFF2563EB),
    _ => AppColors.primary,
  };
  Color get _editingSoftColor => switch (editingBy) {
    '나' => const Color(0xFFDBEAFE),
    _ => const Color(0xFFFFE4E6),
  };
  Color get _editingDetailColor => switch (editingBy) {
    '나' => const Color(0xFF1D4ED8),
    _ => const Color(0xFF9A3412),
  };

  String get _editingUserName => editingBy == '나'
      ? (AuthSession.shortLabel.isEmpty ? '나' : AuthSession.shortLabel)
      : editingBy ?? '사용자';

  void _showEditingUser(BuildContext context) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text('$_editingUserName님이 수정 중입니다.')));
  }

  @override
  Widget build(BuildContext context) =>
      isEditing ? _editingCard(context) : _normalCard();

  /// 공동 수정 중인 장소를 이미지처럼 별도 편집 카드로 강조합니다.
  Widget _editingCard(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 10),
    decoration: BoxDecoration(
      color: Colors.white,
      border: Border.all(color: _editingColor, width: 2),
      borderRadius: BorderRadius.circular(18),
    ),
    child: InkWell(
      onTap: onEdit,
      borderRadius: BorderRadius.circular(16),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 12, 13),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  data.time,
                  style: TextStyle(
                    color: _editingColor,
                    fontSize: 13,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const Spacer(),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 5,
                  ),
                  decoration: BoxDecoration(
                    color: _editingSoftColor,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      InkWell(
                        onTap: () => _showEditingUser(context),
                        borderRadius: BorderRadius.circular(7),
                        child: Container(
                          width: 20,
                          height: 20,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            color: _editingColor,
                            borderRadius: BorderRadius.all(Radius.circular(7)),
                          ),
                          child: Text(
                            _editingUserName.characters.first,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 11,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 5),
                      Text(
                        '수정 중',
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w900,
                          color: _editingColor,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 7),
                const Icon(
                  Icons.edit_rounded,
                  size: 20,
                  color: Color(0xFF6B7280),
                ),
              ],
            ),
            const SizedBox(height: 9),
            Text(
              '${data.emoji}  ${data.place}',
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: 4),
            Text(
              '${editingDetail ?? '일정'} 수정 중 · ${data.time}',
              style: TextStyle(
                fontSize: 12,
                color: _editingDetailColor,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    ),
  );

  Widget _normalCard() => Card(
    margin: const EdgeInsets.only(bottom: 10),
    elevation: 0,
    color: Colors.white,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(18),
      side: const BorderSide(color: Color(0xFFEDEFF4)),
    ),
    child: ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
      leading: CircleAvatar(
        backgroundColor: index == 1
            ? const Color(0xFF16A34A)
            : AppColors.primary,
        child: Text(
          '$index',
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
      title: Text(
        '${data.emoji}  ${data.place}',
        style: const TextStyle(fontWeight: FontWeight.w900),
      ),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Text('${data.time} · ${data.description}'),
      ),
      trailing: editable
          ? IconButton(
              onPressed: onEdit,
              icon: const Icon(Icons.edit_rounded, color: Color(0xFF6B7280)),
              tooltip: '${data.place} 수정',
            )
          : null,
    ),
  );
}

/// One AI plan day as [TodayTravelScreen] entries, labelled exactly as the
/// itinerary shows them (time, emoji, description, coordinates, travel).
List<TodayScheduleEntry> todayEntriesForPlanDay(GeneratedPlanDay day) => [
  for (final item in day.items)
    TodayScheduleEntry(
      time: _ItineraryScreenState._generatedTime(item),
      emoji: _ItineraryScreenState._generatedEmoji(item),
      place: item.name,
      description: _ItineraryScreenState._generatedDescription(item),
      position: _ItineraryScreenState._generatedPosition(item),
      travel: item.travelLabel,
      travelMode: item.transportModeFromPrevious,
    ),
];

class _PlanStop {
  const _PlanStop(
    this.time,
    this.emoji,
    this.place,
    this.description,
    this.position, {
    this.travel,
    this.travelMode,
    this.itemId,
    this.isPlace = false,
  });

  /// Server plan item; null for the built-in sample schedule.
  final int? itemId;

  /// A verified place keeps its name; only rests can be renamed.
  final bool isPlace;

  final String time;
  final String emoji;
  final String place;
  final String description;

  /// 좌표를 모르는 일정(휴식·자유 시간 등)은 null이며 지도에 표시하지 않습니다.
  final LatLng? position;

  /// Travel label from the previous item (see [planTravelLabel]), or null.
  final String? travel;
  final String? travelMode;

  _PlanStop copyWith({
    String? time,
    String? emoji,
    String? place,
    String? description,
    LatLng? position,
  }) => _PlanStop(
    time ?? this.time,
    emoji ?? this.emoji,
    place ?? this.place,
    description ?? this.description,
    position ?? this.position,
    travel: travel,
    travelMode: travelMode,
    itemId: itemId,
    isPlace: isPlace,
  );
}

/// Accepts digits only and displays up to four of them as an HH:mm time.
class _TimeInputFormatter extends TextInputFormatter {
  const _TimeInputFormatter();

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final digits = newValue.text.replaceAll(RegExp(r'[^0-9]'), '');
    var limitedDigits = digits.length > 4 ? digits.substring(0, 4) : digits;

    if (limitedDigits.isNotEmpty && int.parse(limitedDigits[0]) > 2) {
      limitedDigits = '';
    } else if (limitedDigits.length >= 2 &&
        int.parse(limitedDigits.substring(0, 2)) > 23) {
      limitedDigits = limitedDigits.substring(0, 1);
    } else if (limitedDigits.length >= 3 && int.parse(limitedDigits[2]) > 5) {
      limitedDigits = limitedDigits.substring(0, 2);
    }

    final formatted = limitedDigits.length > 2
        ? '${limitedDigits.substring(0, 2)}:${limitedDigits.substring(2)}'
        : limitedDigits;

    return TextEditingValue(
      text: formatted,
      selection: TextSelection.collapsed(offset: formatted.length),
    );
  }
}
