import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/layout/app_responsive.dart';
import '../../core/theme/app_theme.dart';
import '../../data/travel_taste_options.dart';
import '../../widgets/ai_working_indicator.dart';
import '../../widgets/app_bottom_navigation.dart';
import '../../services/active_trip_service.dart';
import '../../services/plan_service.dart';
import '../../models/trip_transport_mode.dart';
import '../../services/trip_draft_store.dart';
import '../../services/trip_taste_preferences.dart';
import '../../services/trip_service.dart';
import 'plan_draft_screen.dart';

/// 여행 생성의 모든 입력 단계를 관리하는 화면입니다.
class TripPlacesScreen extends StatefulWidget {
  const TripPlacesScreen({
    super.key,
    this.preferredTastes = const {},
    this.initialPlaces = const {},
    this.initialPlaceIds = const {},
    this.destination,
    this.photoPlan = false,
  });

  /// 취향 확인에서 전달된 장소 추천 기준입니다.
  final Set<String> preferredTastes;

  /// 장소 상세 등에서 여행 만들기를 시작할 때 참고한 장소 이름입니다.
  /// 맥락 안내에만 쓰고, id로 보내거나 지역을 추측하는 데 쓰지 않습니다.
  final Set<String> initialPlaces;

  /// Verified backend place IDs selected by a search result.  Display-only
  /// names from image, YouTube, and legacy screens are deliberately not
  /// converted by name: that could anchor a different place with the same
  /// name.
  final Set<int> initialPlaceIds;

  /// 실제 API 등 신뢰 가능한 원천에서 전달된 여행 목적지 지역입니다.
  final String? destination;

  final bool photoPlan;

  @override
  State<TripPlacesScreen> createState() => _TripPlacesScreenState();
}

class _TripPlacesScreenState extends State<TripPlacesScreen>
    with WidgetsBindingObserver {
  int _step = 1;

  /// 작성 중 입력값 자동 저장(TripDraftStore). 복원이 끝나기 전에는 저장하지
  /// 않아 빈 초기값이 기존 초안을 덮어쓰지 않고, 여행 생성이 끝나 초안을
  /// 지운 뒤에는 다시 저장하지 않습니다.
  bool _draftReady = false;
  bool _draftFinished = false;
  Timer? _draftTimer;

  /// 목적지를 모를 때 "어디로 가세요?" 단계에서 입력받는 도시·지역 이름입니다.
  final TextEditingController _destinationController = TextEditingController();
  DateTimeRange? _dates;
  bool _selectingEndDate = false;
  late DateTime _visibleMonth = DateTime(
    DateTime.now().year,
    DateTime.now().month,
  );
  String _travelStyle = '';
  final Set<String> _travelTastes = <String>{};
  bool _loadingTripTaste = true;
  bool _savingTripTaste = false;
  final Set<String> _transport = <String>{};
  final List<_CompanionProfile> _registeredCompanions = [
    const _CompanionProfile(name: '엄마'),
  ];
  int? _selectedCompanionIndex = 0;
  final Set<int> _selectedCompanionIndices = <int>{0};
  bool _generating = false;
  String? _generateError;

  /// 이미 만든 여행(trip_id)과 그때 보낸 입력 값입니다. 입력이 같으면
  /// 다시 시도할 때 같은 여행으로 일정 생성만 다시 요청합니다.
  int? _createdTripId;
  String? _createdTripSignature;

  final TripService _tripService = TripService();
  final PlanService _planService = PlanService();

  /// 여행 취향 라벨을 서버 interest_codes로 바꿉니다. 없는 라벨은 보내지 않습니다.
  static const _interestCodes = <String, String>{
    '바다': 'SEA',
    '자연': 'NATURE',
    '도시': 'CITY',
    '맛집': 'FOOD',
    '카페': 'CAFE',
    '전시': 'EXHIBITION',
    '체험': 'ACTIVITY',
    '휴식': 'REST',
    '전통문화': 'CULTURE',
  };

  /// UI labels are deliberately mapped to the API enum instead of relying on
  /// a server-side default. Unknown labels must be handled as invalid input.
  static const _travelStyleCodes = <String, String>{
    '여유롭게': 'SLOW',
    '알차게': 'STANDARD',
    '맛집 중심': 'FOOD_FOCUSED',
  };

  /// 신뢰 가능한 원천(저장한 영상 등)에서 전달된 목적지입니다.
  String? get _knownDestination {
    final destination = widget.destination?.trim();
    return destination == null || destination.isEmpty ? null : destination;
  }

  /// 목적지를 모르면 "어디로 가세요?" 단계를 보여줍니다.
  bool get _asksDestination => _knownDestination == null;

  /// 여행(trip)의 destination으로 보낼 값입니다.
  String? get _tripDestination {
    final known = _knownDestination;
    if (known != null) return known;
    final typed = _destinationController.text.trim();
    return typed.isEmpty ? null : typed;
  }

  /// 확인 화면 바로 앞 단계입니다 (목적지를 알면 동행자 단계).
  int get _lastInputStep => _asksDestination ? 5 : 4;

  List<String> get _selectedInterestCodes => [
    for (final taste in travelTasteOptions.map((option) => option.$2))
      if (_travelTastes.contains(taste) && _interestCodes.containsKey(taste))
        _interestCodes[taste]!,
  ];

  String? get _selectedTravelStyleCode => _travelStyleCodes[_travelStyle];

  /// WALK migration을 적용한 뒤에만 build-time flag로 도보 선택을 활성화합니다.
  static const bool _walkModeEnabled = bool.fromEnvironment(
    'TRIP_WALK_MODE_ENABLED',
    defaultValue: false,
  );

  /// Trip의 주 이동수단은 하나만 저장합니다. 기존 null 처리도 유지합니다.
  String? get _transportMode {
    return tripPrimaryTransportModeForSelection(
      _transport,
      walkEnabled: _walkModeEnabled,
    );
  }

  List<_TransportOption> get _transportOptions => [
        const _TransportOption('자동차', Icons.directions_car_outlined, '직접 운전'),
        if (_walkModeEnabled)
          const _TransportOption('도보', Icons.directions_walk_outlined, '걷기 좋은 코스'),
        const _TransportOption('대중교통', Icons.directions_bus_outlined, '버스·지하철'),
        const _TransportOption('택시', Icons.local_taxi_outlined, '빠르게 이동'),
      ];

  static const _styleOptions = ['여유롭게', '알차게', '맛집 중심'];
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _destinationController.addListener(_scheduleDraftSave);
    unawaited(_restoreInputs());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    // Leaving the screen keeps the draft: write the latest values now.
    _flushDraft();
    _destinationController.dispose();
    super.dispose();
  }

  @override
  void setState(VoidCallback fn) {
    super.setState(fn);
    _scheduleDraftSave();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) _flushDraft();
  }

  /// Confirmed tastes first, then the newer work-in-progress draft.
  Future<void> _restoreInputs() async {
    await _loadTripTaste();
    final draft = await TripDraftStore.load();
    if (!mounted) return;
    if (draft != null && _sameStart(draft)) {
      super.setState(() => _applyDraft(draft));
      debugPrint('[TripDraft] restored');
    }
    _draftReady = true;
  }

  /// A draft belongs to the trip it was started for: opening the screen from
  /// a new video, place or destination starts over instead of jumping to the
  /// old draft's step.
  bool _sameStart(Map<String, dynamic> draft) {
    String key(Iterable<Object?> values) =>
        (values.map((value) => value.toString()).toList()..sort()).join('|');
    final saved = draft['origin'];
    final current = key([...widget.initialPlaces, ?widget.destination]);
    return key(saved is List ? saved : const []) == current;
  }

  void _applyDraft(Map<String, dynamic> draft) {
    final today = DateUtils.dateOnly(DateTime.now());
    final start = DateTime.tryParse(draft['start_date']?.toString() ?? '');
    final end = DateTime.tryParse(draft['end_date']?.toString() ?? '');
    // A trip that would start in the past is not restored as dates.
    if (start != null && end != null && !end.isBefore(start) && !start.isBefore(today)) {
      _dates = DateTimeRange(start: start, end: end);
      _visibleMonth = DateTime(start.year, start.month);
    }
    final style = draft['travel_style']?.toString();
    if (style != null && _styleOptions.contains(style)) _travelStyle = style;
    final tastes = draft['tastes'];
    if (tastes is List) {
      final valid = travelTasteOptions.map((item) => item.$2).toSet();
      _travelTastes
        ..clear()
        ..addAll(tastes.map((value) => value.toString()).where(valid.contains));
    }
    final transport = draft['transport'];
    if (transport is List) {
      final valid = _transportOptions.map((option) => option.label).toSet();
      _transport
        ..clear()
        ..addAll(transport.map((value) => value.toString()).where(valid.contains));
    }
    final companions = draft['companions'];
    if (companions is List && companions.isNotEmpty) {
      final names = companions.map((value) => value.toString().trim()).where((name) => name.isNotEmpty).toList();
      if (names.isNotEmpty) {
        _registeredCompanions
          ..clear()
          ..addAll(names.map((name) => _CompanionProfile(name: name)));
        final selected = draft['selected_companions'];
        _selectedCompanionIndices.clear();
        if (selected is List) {
          _selectedCompanionIndices.addAll(
            selected.whereType<int>().where((index) => index >= 0 && index < names.length),
          );
        }
        final current = draft['current_companion'];
        _selectedCompanionIndex = current is int && current >= 0 && current < names.length ? current : null;
      }
    }
    final destination = draft['destination']?.toString();
    if (_asksDestination && destination != null && destination.isNotEmpty) {
      _destinationController.text = destination;
    }
    final step = draft['step'];
    if (step is int && step >= 1 && step <= 6 && (step != 5 || _asksDestination)) _step = step;
  }

  Map<String, dynamic> get _draft => {
    'origin': [...widget.initialPlaces, ?widget.destination],
    'step': _step,
    'start_date': _dates?.start.toIso8601String(),
    'end_date': _dates?.end.toIso8601String(),
    'travel_style': _travelStyle,
    'tastes': _travelTastes.toList(),
    'transport': _transport.toList(),
    'companions': _registeredCompanions.map((companion) => companion.name).toList(),
    'selected_companions': _selectedCompanionIndices.toList()..sort(),
    'current_companion': _selectedCompanionIndex,
    if (_asksDestination) 'destination': _destinationController.text.trim(),
  };

  void _scheduleDraftSave() {
    if (!_draftReady || _draftFinished) return;
    _draftTimer?.cancel();
    _draftTimer = Timer(const Duration(milliseconds: 400), _flushDraft);
  }

  void _flushDraft() {
    _draftTimer?.cancel();
    _draftTimer = null;
    if (!_draftReady || _draftFinished) return;
    unawaited(TripDraftStore.save(_draft));
  }

  Future<void> _loadTripTaste() async {
    try {
      final (style, tastes) = await TripTastePreferences.load();
      if (!mounted) return;
      setState(() {
        if (style != null && _styleOptions.contains(style)) {
          _travelStyle = style;
        }
        if (tastes != null) {
          final validTastes = travelTasteOptions.map((item) => item.$2).toSet();
          _travelTastes.addAll(tastes.where(validTastes.contains));
        }
        _loadingTripTaste = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _loadingTripTaste = false);
    }
  }

  String get _stepTitle => switch (_step) {
    1 => '날짜 선택',
    2 => '여행 취향',
    3 => '이동수단',
    4 => '동행자 정보',
    5 => '여행지',
    _ => '여행 확인',
  };

  bool get _canContinue => switch (_step) {
    1 => _dates != null,
    2 =>
      !_loadingTripTaste && _travelStyle.isNotEmpty && _travelTastes.isNotEmpty,
    3 => _transport.isNotEmpty,
    5 => _tripDestination != null,
    _ => true,
  };

  List<_CompanionProfile> get _selectedCompanions => _selectedCompanionIndices
      .where((index) => index < _registeredCompanions.length)
      .map((index) => _registeredCompanions[index])
      .toList();

  void _toggleCompanionSelection(int index, bool selected) {
    setState(() {
      if (selected) {
        _selectedCompanionIndices.add(index);
        _selectedCompanionIndex = index;
      } else {
        _selectedCompanionIndices.remove(index);
      }
    });
  }

  void _addCompanion() {
    setState(() {
      _registeredCompanions.add(
        _CompanionProfile(name: '동행자 ${_registeredCompanions.length + 1}'),
      );
      _selectedCompanionIndex = _registeredCompanions.length - 1;
      _selectedCompanionIndices.add(_selectedCompanionIndex!);
    });
  }

  Future<void> _renameCompanion(int index) async {
    final controller = TextEditingController(
      text: _registeredCompanions[index].name,
    );
    final name = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('동행자 이름 수정'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(hintText: '이름을 입력해주세요'),
          onSubmitted: (value) => Navigator.of(dialogContext).pop(value),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(controller.text),
            child: const Text('저장'),
          ),
        ],
      ),
    );
    final trimmedName = name?.trim();
    if (!mounted || trimmedName == null || trimmedName.isEmpty) return;
    setState(() {
      _registeredCompanions[index] = _registeredCompanions[index].copyWith(
        name: trimmedName,
      );
      _selectedCompanionIndex = index;
    });
  }

  void _goBack() {
    if (_generating) return;
    final previousStep = switch (_step) {
      2 => 1,
      3 => 2,
      4 => 3,
      5 => 4,
      6 => _lastInputStep,
      _ => null,
    };
    if (previousStep == null) {
      Navigator.of(context).maybePop();
    } else {
      setState(() => _step = previousStep);
    }
  }

  void _continue() {
    if (!_canContinue) return;
    if (_step == 1) {
      setState(() {
        _selectingEndDate = false;
        _step = 2;
      });
      return;
    }
    if (_step == 2) {
      setState(() => _step = 3);
      return;
    }
    if (_step == 3) {
      setState(() => _step = 4);
      return;
    }
    if (_step == 4) {
      setState(() => _step = _asksDestination ? 5 : 6);
      return;
    }
    if (_step < 6) setState(() => _step++);
  }

  void _selectDate(DateTime date) {
    final selected = DateUtils.dateOnly(date);
    if (_selectingEndDate && _dates != null) {
      final start = _dates!.start;
      setState(() {
        _dates = selected.isBefore(start)
            ? DateTimeRange(start: selected, end: start)
            : DateTimeRange(start: start, end: selected);
        _selectingEndDate = false;
      });
      return;
    }
    setState(() {
      _dates = DateTimeRange(start: selected, end: selected);
      _selectingEndDate = true;
    });
  }

  void _changeMonth(int offset) {
    final next = DateTime(_visibleMonth.year, _visibleMonth.month + offset);
    final today = DateUtils.dateOnly(DateTime.now());
    final firstCurrentMonth = DateTime(today.year, today.month);
    final lastAllowedMonth = DateTime(today.year + 1, today.month);
    if (next.isBefore(firstCurrentMonth) || next.isAfter(lastAllowedMonth)) {
      return;
    }
    setState(() => _visibleMonth = next);
  }

  /// 여행을 만들고(필요할 때만) 목적지 전체를 대상으로 AI 일정 생성을 요청합니다.
  Future<void> _confirmAndGenerate() async {
    final destination = _tripDestination;
    if (_savingTripTaste || _generating || destination == null) {
      return;
    }

    final travelStyle = _selectedTravelStyleCode;
    if (travelStyle == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('여행 스타일을 다시 선택해 주세요.')),
      );
      return;
    }

    setState(() => _savingTripTaste = true);

    try {
      await TripTastePreferences.save(
        style: _travelStyle,
        tastes: _travelTastes,
      );
    } catch (_) {
      if (!mounted) {
        return;
      }

      setState(() => _savingTripTaste = false);

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('여행 취향을 저장하지 못했어요. 다시 시도해주세요.')),
      );

      return;
    }

    final transportMode = _transportMode;
    final interestCodes = _selectedInterestCodes;
    final signature = [
      _dates?.start.toIso8601String(),
      _dates?.end.toIso8601String(),
      destination,
      transportMode,
      interestCodes.join(','),
      travelStyle,
    ].join('|');

    if (_createdTripId == null || _createdTripSignature != signature) {
      try {
        final createdTrip = await _tripService.create(
          startDate: _dates?.start,
          endDate: _dates?.end,
          destination: destination,
          transportMode: transportMode,
          interestCodes: interestCodes,
          travelStyle: travelStyle,
        );

        debugPrint(
          '[Trip] created trip_id=${createdTrip.tripId}, '
          'status=${createdTrip.status}',
        );
        _createdTripId = createdTrip.tripId;
        _createdTripSignature = signature;
      } catch (error) {
        debugPrint('[Trip] create failed: $error');

        if (!mounted) {
          return;
        }

        setState(() => _savingTripTaste = false);

        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('여행을 저장하지 못했어요. 다시 시도해주세요.')),
        );

        return;
      }
    }

    if (!mounted) {
      return;
    }

    setState(() => _savingTripTaste = false);
    await _generatePlan();
  }

  /// 같은 여행(trip_id)으로 일정 생성을 요청합니다. "다시 시도"도 여기로 옵니다.
  Future<void> _generatePlan() async {
    final tripId = _createdTripId;
    if (tripId == null || _generating) return;

    setState(() {
      _generating = true;
      _generateError = null;
    });

    GeneratedPlan plan;
    try {
      // 장소를 고르지 않고 목적지 전체 후보로 일정을 만듭니다. 연결이 끊기거나
      // 이미 만든 일정이 있으면 AI를 다시 부르지 않고 서버에 저장된 일정을 불러옵니다.
      plan = await _planService.generateOrRecover(
        tripId,
        widget.initialPlaceIds.toList(growable: false),
      );
    } catch (error) {
      debugPrint('[Plan] generate failed: $error');
      if (!mounted) return;
      setState(() {
        _generating = false;
        _generateError = planErrorMessage(error);
      });
      return;
    }

    debugPrint(
      '[Plan] generated plan_id=${plan.planId}, days=${plan.days.length}',
    );

    if (!mounted) {
      return;
    }

    if (plan.days.isEmpty) {
      setState(() {
        _generating = false;
        _generateError = 'AI가 만든 일정에 날짜별 일정이 없어요.';
      });
      return;
    }

    final planPlaceNames = _planPlaceNames(plan);

    // The trip and its plan exist now: the work-in-progress draft is done.
    _draftFinished = true;
    _draftTimer?.cancel();
    unawaited(TripDraftStore.clear());

    ActiveTripService.save(
      savedTripId: tripId,
      savedPlanId: plan.planId,
      tripDates: _dates,
      selectedTransport: _transport,
      selectedPlaces: planPlaceNames,
      selectedCompanions: _selectedCompanions.map(
        (companion) => ActiveTripCompanion(name: companion.name),
      ),
      tripName: ActiveTripService.nameFor(destination: _tripDestination),
    );

    // A new plan opens as the AI draft first; 확정하기 there leads to the
    // full itinerary screen as before.
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => PlanDraftScreen(
          plan: plan,
          tripDates: _dates,
          transport: _transport,
          places: planPlaceNames,
        ),
      ),
    );
  }

  /// AI 일정에 실제로 들어간 장소 이름입니다. 없으면 목적지 이름을 씁니다.
  List<String> _planPlaceNames(GeneratedPlan plan) {
    final names = <String>[];
    for (final day in plan.days) {
      for (final item in day.items) {
        final name = item.name.trim();
        if (item.placeId != null && name.isNotEmpty && !names.contains(name)) {
          names.add(name);
        }
      }
    }
    final destination = _tripDestination;
    if (names.isEmpty && destination != null) names.add(destination);
    return names;
  }

  @override
  Widget build(BuildContext context) {
    if (_generating || _generateError != null) {
      return PopScope(
        canPop: !_generating,
        child: Scaffold(
          backgroundColor: AppColors.bg,
          body: SafeArea(child: _generating ? _loading() : _generateFailed()),
        ),
      );
    }
    return _surveyScaffold();
  }

  Widget _surveyScaffold() => Scaffold(
    backgroundColor: AppColors.bg,
    appBar: AppBar(
      leading: IconButton(
        onPressed: _goBack,
        tooltip: _step == 1 ? '이전 화면으로 돌아가기' : '이전 단계로 돌아가기',
        icon: const Icon(Icons.chevron_left_rounded),
      ),
      title: Text(_stepTitle),
    ),
    body: SafeArea(
      top: false,
      child: Column(
        children: [
          _progress(),
          Expanded(child: _stepBody()),
          _actionBar(),
        ],
      ),
    ),
    bottomNavigationBar: const AppBottomNavigation(selectedIndex: 0),
  );

  int get _totalSteps => _lastInputStep;
  int get _displayStep => _step.clamp(1, _totalSteps);
  Widget _progress() => Container(
    color: Colors.white,
    padding: const EdgeInsets.fromLTRB(20, 8, 20, 14),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          _step < 6 ? '여행 만들기 $_displayStep/$_totalSteps' : '입력 내용 확인',
          style: const TextStyle(
            color: AppColors.primary,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(99),
          child: LinearProgressIndicator(
            value: _step < 6 ? _displayStep / _totalSteps : 1,
            minHeight: 6,
            backgroundColor: AppColors.soft,
            color: AppColors.primary,
          ),
        ),
      ],
    ),
  );

  Widget _stepBody() {
    if (_step == 2) {
      if (_loadingTripTaste) {
        return const Center(child: CircularProgressIndicator());
      }
      return ListView(
        padding: EdgeInsets.fromLTRB(
          ResponsiveLayout.pageHorizontal(context),
          12,
          ResponsiveLayout.pageHorizontal(context),
          16,
        ),
        children: [_tastesStep()],
      );
    }

    return ListView(
      padding: _step == 1
          ? const EdgeInsets.fromLTRB(20, 12, 20, 12)
          : const EdgeInsets.fromLTRB(20, 20, 20, 28),
      children: [
        switch (_step) {
          1 => _datesStep(),
          3 => _transportStep(),
          4 => _companionsStep(),
          5 => _destinationStep(),
          _ => _confirmStep(),
        },
      ],
    );
  }

  Widget _destinationStep() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        '어디로 가세요?',
        style: TextStyle(fontSize: 25, fontWeight: FontWeight.w900),
      ),
      const SizedBox(height: 6),
      const Text(
        '도시나 지역 이름을 적어주세요. 그 지역의 장소로 AI가 일정을 짜요.',
        style: TextStyle(fontSize: 16, color: Color(0xFF6B7280)),
      ),
      if (widget.initialPlaces.isNotEmpty) ...[
        const SizedBox(height: 8),
        Text(
          '참고한 장소: ${widget.initialPlaces.join(', ')}',
          style: const TextStyle(fontSize: 15, color: Color(0xFF6B7280)),
        ),
      ],
      const SizedBox(height: 16),
      Container(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: const Color(0xFFE5E7EB)),
        ),
        child: Row(
          children: [
            const Icon(Icons.place_outlined, color: Color(0xFF9CA3AF)),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: _destinationController,
                textInputAction: TextInputAction.done,
                onChanged: (_) => setState(() {}),
                onSubmitted: (_) => _continue(),
                decoration: const InputDecoration(
                  hintText: '예: 부산, 강릉, 제주',
                  border: InputBorder.none,
                ),
              ),
            ),
          ],
        ),
      ),
    ],
  );

  Widget _datesStep() {
    final today = DateUtils.dateOnly(DateTime.now());
    final firstDay = DateTime(_visibleMonth.year, _visibleMonth.month);
    final daysInMonth = DateTime(
      _visibleMonth.year,
      _visibleMonth.month + 1,
      0,
    ).day;
    final leadingEmptyDays = firstDay.weekday % 7;
    final selectedStart = _dates?.start;
    final selectedEnd = _selectingEndDate ? null : _dates?.end;
    final tripDays = selectedStart != null && selectedEnd != null
        ? selectedEnd.difference(selectedStart).inDays + 1
        : null;
    final nights = tripDays == null ? null : tripDays - 1;
    final monthNames = <String>[
      '1월',
      '2월',
      '3월',
      '4월',
      '5월',
      '6월',
      '7월',
      '8월',
      '9월',
      '10월',
      '11월',
      '12월',
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '언제 떠나세요?',
          style: TextStyle(fontSize: 23, fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 6),
        Text(
          _selectingEndDate
              ? '돌아오는 날을 선택하거나, 다음을 누르면 당일치기로 진행돼요.'
              : '출발일과 돌아오는 날을 선택해주세요.',
          style: const TextStyle(color: Color(0xFF6B7280)),
        ),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(20),
          ),
          child: Column(
            children: [
              Row(
                children: [
                  IconButton(
                    onPressed:
                        DateTime(
                          _visibleMonth.year,
                          _visibleMonth.month,
                        ).isAfter(DateTime(today.year, today.month))
                        ? () => _changeMonth(-1)
                        : null,
                    tooltip: '이전 달',
                    icon: const Icon(Icons.chevron_left, size: 32),
                  ),
                  Expanded(
                    child: Text(
                      '${_visibleMonth.year}년 ${monthNames[_visibleMonth.month - 1]}',
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: () => _changeMonth(1),
                    tooltip: '다음 달',
                    icon: const Icon(Icons.chevron_right, size: 32),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              const Row(
                children: [
                  _WeekdayLabel('일', Color(0xFFEF4444)),
                  _WeekdayLabel('월', Color(0xFF6B7280)),
                  _WeekdayLabel('화', Color(0xFF6B7280)),
                  _WeekdayLabel('수', Color(0xFF6B7280)),
                  _WeekdayLabel('목', Color(0xFF6B7280)),
                  _WeekdayLabel('금', Color(0xFF6B7280)),
                  _WeekdayLabel('토', Color(0xFF4169D8)),
                ],
              ),
              const SizedBox(height: 4),
              GridView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                itemCount: leadingEmptyDays + daysInMonth,
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 7,
                  childAspectRatio: 1.05,
                  mainAxisSpacing: 2,
                ),
                itemBuilder: (context, index) {
                  if (index < leadingEmptyDays) return const SizedBox.shrink();
                  final date = DateTime(
                    _visibleMonth.year,
                    _visibleMonth.month,
                    index - leadingEmptyDays + 1,
                  );
                  final beforeToday = date.isBefore(today);
                  final isStart =
                      selectedStart != null &&
                      DateUtils.isSameDay(date, selectedStart);
                  final isEnd =
                      selectedEnd != null &&
                      DateUtils.isSameDay(date, selectedEnd);
                  final between =
                      selectedStart != null &&
                      selectedEnd != null &&
                      date.isAfter(selectedStart) &&
                      date.isBefore(selectedEnd);
                  final selected = isStart || isEnd;
                  return Semantics(
                    button: !beforeToday,
                    selected: selected,
                    label:
                        '${date.month}월 ${date.day}일${beforeToday ? ', 선택할 수 없음' : ''}',
                    child: InkWell(
                      onTap: beforeToday ? null : () => _selectDate(date),
                      borderRadius: BorderRadius.circular(26),
                      child: Container(
                        alignment: Alignment.center,
                        margin: const EdgeInsets.all(1),
                        decoration: BoxDecoration(
                          color: selected
                              ? AppColors.primary
                              : between
                              ? AppColors.soft
                              : Colors.transparent,
                          shape: BoxShape.circle,
                        ),
                        child: Text(
                          '${date.day}',
                          style: TextStyle(
                            color: beforeToday
                                ? const Color(0xFFD1D5DB)
                                : selected
                                ? Colors.white
                                : AppColors.ink,
                            fontWeight: selected
                                ? FontWeight.w900
                                : FontWeight.w500,
                          ),
                        ),
                      ),
                    ),
                  );
                },
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: AppColors.soft,
            borderRadius: BorderRadius.circular(18),
          ),
          child: _dates == null
              ? const Text(
                  '출발일을 선택해주세요.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppColors.primary,
                    fontSize: 17,
                    fontWeight: FontWeight.w800,
                  ),
                )
              : _selectingEndDate
              ? Column(
                  children: [
                    Text(
                      _dateText(_dates!.start),
                      style: const TextStyle(
                        color: AppColors.primary,
                        fontSize: 22,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      '다음을 누르면 당일치기로 진행돼요.',
                      style: TextStyle(color: AppColors.primary),
                    ),
                  ],
                )
              : Column(
                  children: [
                    Text(
                      '${_dateText(_dates!.start)} ~ ${_dateText(_dates!.end)}',
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: AppColors.primary,
                        fontSize: 22,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          '$nights박 $tripDays일',
                          style: const TextStyle(
                            color: AppColors.primary,
                            fontSize: 19,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
        ),
      ],
    );
  }

  Widget _tastesStep() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        '어떤 여행을 좋아하세요?',
        style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
      ),
      const SizedBox(height: 7),
      const Text(
        '이번 여행에 맞는 스타일과 취향을 골라주세요.',
        style: TextStyle(fontSize: 16, color: Color(0xFF6B7280)),
      ),
      const SizedBox(height: 12),
      const Text(
        '여행 스타일',
        style: TextStyle(fontSize: 19, fontWeight: FontWeight.w900),
      ),
      const SizedBox(height: 6),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: _styleOptions.map((style) {
          final selected = _travelStyle == style;
          return ChoiceChip(
            label: Text(style),
            selected: selected,
            onSelected: (_) => setState(() => _travelStyle = style),
            selectedColor: AppColors.primary,
            labelStyle: TextStyle(
              color: selected ? Colors.white : AppColors.primary,
              fontWeight: FontWeight.w800,
            ),
          );
        }).toList(),
      ),
      const SizedBox(height: 12),
      Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(24),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '여행 취향 선택',
              style: TextStyle(fontSize: 19, fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: 4),
            const Text(
              '원하는 항목을 여러 개 골라주세요.',
              style: TextStyle(color: Color(0xFF6B7280)),
            ),
            const SizedBox(height: 10),
            GridView.builder(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: travelTasteOptions.length,
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: ResponsiveLayout.isCompact(context) ? 2 : 3,
                mainAxisSpacing: 10,
                crossAxisSpacing: 10,
                mainAxisExtent: ResponsiveLayout.isCompact(context) ? 92 : 96,
              ),
              itemBuilder: (context, index) {
                final item = travelTasteOptions[index];
                final selected = _travelTastes.contains(item.$2);
                return Material(
                  color: selected ? AppColors.soft : const Color(0xFFF9FAFF),
                  borderRadius: BorderRadius.circular(18),
                  child: InkWell(
                    onTap: () => setState(() {
                      if (selected) {
                        _travelTastes.remove(item.$2);
                      } else {
                        _travelTastes.add(item.$2);
                      }
                    }),
                    borderRadius: BorderRadius.circular(18),
                    child: Stack(
                      children: [
                        Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                item.$1,
                                style: const TextStyle(fontSize: 25),
                              ),
                              const SizedBox(height: 6),
                              Text(
                                item.$2,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w900,
                                  color: selected
                                      ? AppColors.primary
                                      : AppColors.ink,
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (selected)
                          const Positioned(
                            right: 7,
                            top: 7,
                            child: CircleAvatar(
                              radius: 10,
                              backgroundColor: AppColors.primary,
                              child: Icon(
                                Icons.check,
                                size: 14,
                                color: Colors.white,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ],
        ),
      ),
    ],
  );

  Widget _transportStep() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        '어떻게 이동하시나요?',
        style: TextStyle(fontSize: 25, fontWeight: FontWeight.w900),
      ),
      const SizedBox(height: 6),
      const Text(
        '하나만 선택해 주세요.',
        style: TextStyle(fontSize: 17, color: Color(0xFF6B7280)),
      ),
      const SizedBox(height: 18),
      GridView.count(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        crossAxisCount: ResponsiveLayout.twoColumnCount(context),
        mainAxisExtent: ResponsiveLayout.selectionCardExtent(context),
        mainAxisSpacing: 14,
        crossAxisSpacing: 14,
        children: _transportOptions.map((option) {
          final selected = _transport.contains(option.label);
          return Material(
            color: selected ? AppColors.soft : Colors.white,
            borderRadius: BorderRadius.circular(18),
            child: InkWell(
              onTap: () => setState(() {
                if (selected) {
                  _transport.remove(option.label);
                } else {
                  _transport
                    ..clear()
                    ..add(option.label);
                }
              }),
              borderRadius: BorderRadius.circular(18),
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Align(
                      alignment: Alignment.topRight,
                      child: Icon(
                        selected
                            ? Icons.check_circle
                            : Icons.radio_button_unchecked,
                        color: selected
                            ? AppColors.primary
                            : const Color(0xFF9CA3AF),
                      ),
                    ),
                    Icon(option.icon, size: 42, color: AppColors.primary),
                    Text(
                      option.label,
                      style: const TextStyle(
                        fontSize: 19,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    Text(
                      option.description,
                      style: const TextStyle(
                        fontSize: 15,
                        color: Color(0xFF6B7280),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }).toList(),
      ),
    ],
  );

  Widget _companionsStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '동행자 정보를 알려주세요',
          style: TextStyle(fontSize: 25, fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 7),
        const SizedBox(height: 22),

        const Text(
          '등록된 동행자',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 10),
        ...List.generate(
          _registeredCompanions.length,
          (index) => Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: _companionSelectorCard(index, _registeredCompanions[index]),
          ),
        ),
        SizedBox(
          width: double.infinity,
          height: 58,
          child: OutlinedButton.icon(
            onPressed: _addCompanion,
            icon: const Icon(Icons.add_circle_outline, size: 23),
            label: const Text(
              '동행자 추가',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
            ),
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.primary,
              side: const BorderSide(color: Color(0x664169D8), width: 2),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(18),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _companionSelectorCard(int index, _CompanionProfile companion) {
    final editing = index == _selectedCompanionIndex;
    final selected = _selectedCompanionIndices.contains(index);
    return Material(
      color: editing ? AppColors.soft : Colors.white,
      borderRadius: BorderRadius.circular(20),
      child: InkWell(
        onTap: () => setState(() => _selectedCompanionIndex = index),
        borderRadius: BorderRadius.circular(20),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(20),
            border: Border.all(
              color: editing ? AppColors.primary : Colors.transparent,
              width: 2,
            ),
          ),
          child: Row(
            children: [
              CircleAvatar(
                radius: 25,
                backgroundColor: const Color(0xFFDEE7FF),
                child: Text(
                  companion.name.characters.first,
                  style: const TextStyle(
                    color: AppColors.primary,
                    fontSize: 20,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      companion.name,
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ],
                ),
              ),
              IconButton(
                onPressed: () => _renameCompanion(index),
                tooltip: '${companion.name} 이름 수정',
                icon: const Icon(Icons.edit_outlined),
              ),
              Checkbox(
                value: selected,
                onChanged: (value) =>
                    _toggleCompanionSelection(index, value ?? false),
                semanticLabel: '${companion.name} 동행자 선택',
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _confirmStep() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        '이 내용으로 여행을 만들까요?',
        style: TextStyle(fontSize: 27, fontWeight: FontWeight.w900),
      ),
      const SizedBox(height: 24),
      if (_asksDestination)
        _editableCard(
          5,
          _summaryCard(
            Icons.location_on_outlined,
            '여행지',
            _tripDestination ?? '선택하지 않음',
          ),
        )
      else
        _summaryCard(
          Icons.location_on_outlined,
          '여행지',
          _tripDestination ?? '선택하지 않음',
        ),
      _editableCard(
        1,
        _summaryCard(
          Icons.calendar_month_outlined,
          '기간',
          _dates == null
              ? '선택하지 않음'
              : '${_dateText(_dates!.start)} ~ ${_dateText(_dates!.end)}',
        ),
      ),
      _editableCard(
        2,
        _summaryCard(Icons.tune_rounded, '여행 스타일', _travelStyle),
      ),
      _editableCard(
        2,
        _summaryCard(
          Icons.favorite_border_rounded,
          '여행 취향',
          _travelTastes.join(', '),
        ),
      ),
      _editableCard(
        3,
        _summaryCard(
          Icons.directions_car_outlined,
          '이동',
          _transport.join(', '),
        ),
      ),
      _editableCard(
        4,
        _summaryCard(
          Icons.accessibility_new_outlined,
          '동행자 조건',
          _selectedCompanions.isEmpty
              ? '선택하지 않음'
              : _selectedCompanions
                    .map((companion) => companion.name)
                    .join(', '),
        ),
      ),
    ],
  );

  Widget _editableCard(int step, Widget card) =>
      GestureDetector(onTap: () => setState(() => _step = step), child: card);
  Widget _summaryCard(IconData icon, String label, String value) => Padding(
    padding: const EdgeInsets.only(bottom: 14),
    child: Container(
      constraints: const BoxConstraints(minHeight: 86),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(22),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              color: AppColors.soft,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Icon(icon, color: AppColors.primary, size: 29),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: const TextStyle(
                    fontSize: 15,
                    color: Color(0xFF6B7280),
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  value,
                  style: const TextStyle(
                    fontSize: 19,
                    fontWeight: FontWeight.w900,
                    height: 1.25,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );
  Widget _actionBar() => SafeArea(
    top: false,
    child: Container(
      color: Colors.white,
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
      child: SizedBox(
        width: double.infinity,
        height: 56,
        child: FilledButton(
          onPressed: _step == 6
              ? (_savingTripTaste ? null : _confirmAndGenerate)
              : (_canContinue ? _continue : null),
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.primary,
            disabledBackgroundColor: const Color(0xFFCBD5E1),
          ),
          child: Text(
            _step == 6 ? (_savingTripTaste ? '저장 중...' : 'AI 일정 만들기') : '다음',
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
          ),
        ),
      ),
    ),
  );

  Widget _loading() =>
      const AiWorkingIndicator(title: 'AI가 일정을 짜고 있어요');

  Widget _generateFailed() => Center(
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(
            Icons.error_outline_rounded,
            size: 52,
            color: Color(0xFFD9363E),
          ),
          const SizedBox(height: 18),
          const Text(
            '일정을 만들지 못했어요',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 23, fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 10),
          Text(
            _generateError ?? '',
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 16, color: Color(0xFF4B5563)),
          ),
          const SizedBox(height: 28),
          SizedBox(
            height: 56,
            child: FilledButton(
              onPressed: _generatePlan,
              style: FilledButton.styleFrom(backgroundColor: AppColors.primary),
              child: const Text(
                '다시 시도',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
              ),
            ),
          ),
          const SizedBox(height: 10),
          SizedBox(
            height: 52,
            child: OutlinedButton(
              onPressed: () => setState(() => _generateError = null),
              child: const Text('입력 내용으로 돌아가기'),
            ),
          ),
        ],
      ),
    ),
  );

  String _dateText(DateTime date) =>
      '${date.year}.${date.month.toString().padLeft(2, '0')}.${date.day.toString().padLeft(2, '0')}';
}

class _CompanionProfile {
  const _CompanionProfile({required this.name});

  final String name;

  _CompanionProfile copyWith({String? name}) =>
      _CompanionProfile(name: name ?? this.name);
}

class _WeekdayLabel extends StatelessWidget {
  const _WeekdayLabel(this.label, this.color);
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Expanded(
    child: Center(
      child: Text(
        label,
        style: TextStyle(
          fontSize: 12,
          color: color,
          fontWeight: FontWeight.w700,
        ),
      ),
    ),
  );
}

class _TransportOption {
  const _TransportOption(this.label, this.icon, this.description);
  final String label;
  final IconData icon;
  final String description;
}
