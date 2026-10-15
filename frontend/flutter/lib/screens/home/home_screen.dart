import 'dart:async';

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:flutter/services.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;

import '../../core/layout/app_responsive.dart';
import '../../core/theme/app_theme.dart';
import '../../services/active_trip_service.dart';
import '../../services/auth_service.dart';
import '../../services/display_mode_service.dart';
import '../../services/invite_link_service.dart';
import '../../services/notification_service.dart';
import '../../services/weather_notification_service.dart';
import '../../services/weather_service.dart';
import '../../app.dart' show appRouteObserver;
import '../../services/youtube_bridge_service.dart';
import '../../services/youtube_saved_discovery_service.dart';
import '../discovery/camera_screen.dart';
import '../discovery/map_screen.dart';
import '../my/notifications_screen.dart';
import '../my/profile_screen.dart';
import '../preference/youtube_saved_screen.dart';
import '../search/text_search_screen.dart';
import '../travel/today_travel_screen.dart';
import '../travel/weather_screen.dart';
import '../trip/invite_join_dialog.dart';
import '../trip/itinerary_screen.dart';
import '../trip/trip_places_screen.dart';

/// React 홈 화면과 같은 큰 터치 영역의 시니어 친화 홈이다.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, this.seniorMode, this.initialTab = 0});
  final bool? seniorMode;
  final int initialTab;
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver, RouteAware {
  int _tab = 0;
  bool _seniorMode = false;
  final ItinerarySession _itinerarySession = ItinerarySession();
  final stt.SpeechToText _speech = stt.SpeechToText();
  final WeatherService _weatherService = WeatherService();
  final TextEditingController _basicSearchController = TextEditingController();
  final FocusNode _basicSearchFocusNode = FocusNode();
  bool _basicSearchOpening = false;
  late final AnimationController _voicePulseController;
  int _voiceSession = 0;
  bool _voiceOverlayVisible = false;
  bool _voiceListening = false;
  bool _voiceBusy = false;
  bool _voiceOpeningResults = false;
  String _voiceTranscript = '';
  String _voiceMessage = '마이크를 준비하고 있어요.';
  bool _youtubePlanOpening = false;
  bool _showRainAlert = false;
  Timer? _rainAlertTimer;
  StreamSubscription<Map<String, dynamic>>? _youtubeSubscription;
  // YouTube pause events are received only while the Home tab is the visible
  // page and the app is in the foreground (see _syncYoutubeBridge).
  bool _routeVisible = true;
  bool _appForeground = true;
  bool _youtubeBridgeActive = false;
  bool _routeObserved = false;
  String? _lastYoutubeEventKey;
  DateTime? _lastYoutubeEventAt;
  BuildContext? _youtubeDialogContext;
  _HomeWeatherState _homeWeatherState = _HomeWeatherState.loading;
  WeatherData? _homeWeather;

  @override
  void initState() {
    super.initState();
    _basicSearchFocusNode.onKeyEvent = (node, event) {
      if (event is KeyDownEvent &&
          (event.logicalKey == LogicalKeyboardKey.enter ||
              event.logicalKey == LogicalKeyboardKey.numpadEnter)) {
        scheduleMicrotask(() {
          if (mounted) _submitBasicSearch(_basicSearchController.text);
        });
      }
      return KeyEventResult.ignored;
    };
    _voicePulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 850),
    );
    _tab = widget.initialTab.clamp(0, 3).toInt();
    _seniorMode = widget.seniorMode ?? DisplayModeService.seniorMode;
    DisplayModeService.seniorMode = _seniorMode;
    if (!_seniorMode) unawaited(_loadHomeWeather());
    NotificationService.readIds.addListener(_refreshNotificationBadge);
    AuthSession.loadDisplayNameIfMissing().then((_) {
      if (mounted) setState(() {});
    });
    InviteLinkService.pendingToken.addListener(_openPendingInvite);
    WidgetsBinding.instance.addPostFrameCallback((_) => _openPendingInvite());
    WeatherNotificationService.instance.rainPlanRequested.addListener(_openRequestedRainPlan);
    WidgetsBinding.instance.addPostFrameCallback((_) => _openRequestedRainPlan());
    NotificationService.refreshFromTrips().catchError((_) {});
    WidgetsBinding.instance.addObserver(this);
    _youtubeSubscription = YoutubeBridgeService.instance.events.listen((event) {
      if (!mounted) return;
      // A late frame from a socket that is closing must not pop up on
      // another screen or after the app returns from the background.
      if (!_youtubeBridgeActive) {
        debugPrint('[YouTube Bridge] HOME ignored (home inactive) video_id=${event['video_id']}');
        return;
      }
      final eventKey = event['event_id']?.toString() ??
          '${event['video_id']}@${event['position_sec']}';
      final now = DateTime.now();
      if (eventKey == _lastYoutubeEventKey &&
          _lastYoutubeEventAt != null &&
          now.difference(_lastYoutubeEventAt!) < const Duration(seconds: 30)) {
        debugPrint('[YouTube Bridge] HOME ignored (duplicate) key=$eventKey');
        return;
      }
      _lastYoutubeEventKey = eventKey;
      _lastYoutubeEventAt = now;
      // A newer pause replaces the dialog of an older one.
      final openDialog = _youtubeDialogContext;
      if (openDialog != null && openDialog.mounted) {
        Navigator.of(openDialog).pop();
      }

      final positionSec = event['position_sec'] is int
          ? event['position_sec'] as int
          : int.tryParse(event['position_sec']?.toString() ?? '') ?? 0;

      final minutes = positionSec ~/ 60;
      final seconds = positionSec % 60;
      final position =
          '${minutes.toString().padLeft(2, '0')}:${seconds.toString().padLeft(2, '0')}';

      final title = event['title']?.toString() ?? '여행 영상을 발견했어요';
      final channelTitle = event['channel_title']?.toString() ?? '';
      final thumbnailUrl = event['thumbnail_url']?.toString();

      debugPrint(
        '[YouTube Bridge] VIDEO_INFO_DISPLAYED event_id=${event['event_id']} '
        'video_id=${event['video_id']} position_sec=$positionSec',
      );
      final dialog = showDialog<void>(
        context: context,
        barrierDismissible: true,
        builder: (dialogContext) {
          _youtubeDialogContext = dialogContext;
          // Saving resolves the video's region on the server (several seconds),
          // so the buttons show progress and lock until it answers.
          String? busy;
          String? failure;
          return StatefulBuilder(builder: (_, setDialogState) => AlertDialog(
            insetPadding: const EdgeInsets.symmetric(
              horizontal: 24,
              vertical: 24,
            ),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(24),
            ),
            title: Row(
              children: [
                const Icon(Icons.tv, size: 28),
                const SizedBox(width: 10),
                const Expanded(
                  child: Text(
                    'TV에서 여행 영상을 발견했어요',
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                  ),
                ),
                IconButton(
                  tooltip: '닫기',
                  onPressed: () {
                    Navigator.of(dialogContext).pop();
                  },
                  icon: const Icon(Icons.close, size: 28),
                ),
              ],
            ),
            content: SizedBox(
              width: 420,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (thumbnailUrl != null && thumbnailUrl.isNotEmpty)
                    ClipRRect(
                      borderRadius: BorderRadius.circular(16),
                      child: AspectRatio(
                        aspectRatio: 16 / 9,
                        child: Image.network(
                          thumbnailUrl,
                          fit: BoxFit.cover,
                          errorBuilder: (context, error, stackTrace) {
                            return Container(
                              alignment: Alignment.center,
                              color: Colors.black12,
                              child: const Icon(
                                Icons.image_not_supported_outlined,
                                size: 48,
                              ),
                            );
                          },
                        ),
                      ),
                    ),
                  const SizedBox(height: 18),
                  Text(
                    title,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 19,
                      fontWeight: FontWeight.w700,
                      height: 1.35,
                    ),
                  ),
                  if (channelTitle.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      channelTitle,
                      style: const TextStyle(
                        fontSize: 16,
                        color: Colors.black54,
                      ),
                    ),
                  ],
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      const Icon(Icons.schedule, size: 20),
                      const SizedBox(width: 8),
                      Text(
                        '재생 위치 $position',
                        style: const TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                  if (failure != null) ...[
                    const SizedBox(height: 12),
                    Text(
                      failure!,
                      style: const TextStyle(fontSize: 15, color: Color(0xFFDC2626)),
                    ),
                  ],
                ],
              ),
            ),
            actionsPadding: const EdgeInsets.fromLTRB(24, 0, 24, 20),
            actions: [
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: busy != null ? null : () async {
                        setDialogState(() {
                          busy = 'save';
                          failure = null;
                        });
                        try {
                          final saved = await YouTubeSavedDiscoveryService()
                              .save(event);

                          debugPrint(
                            '[YouTube Bridge] SAVED id=${saved.savedDiscoveryId}',
                          );

                          if (!mounted || !dialogContext.mounted) return;

                          Navigator.of(dialogContext).pop();

                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text('저장했어요.')),
                          );
                        } catch (error) {
                          debugPrint('[YouTube Bridge] SAVE failed: $error');
                          if (!dialogContext.mounted) return;
                          // Shown in the dialog: a SnackBar would sit behind it.
                          setDialogState(() {
                            busy = null;
                            failure = '저장하지 못했어요. 잠시 후 다시 눌러주세요.';
                          });
                        }
                      },
                      icon: busy == 'save'
                          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.bookmark_border),
                      label: Text(
                        busy == 'save' ? '저장 중…' : '저장하기',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: busy != null ? null : () async {
                        if (_youtubePlanOpening) return;
                        _youtubePlanOpening = true;
                        setDialogState(() {
                          busy = 'plan';
                          failure = null;
                        });
                        debugPrint('[YouTube Bridge] PLAN requested: $event');
                        // 저장(서버가 같은 영상·위치는 중복 저장하지 않음)하면서 서버가
                        // 영상으로 확인한 지역을 받아, 여행 만들기의 날짜 선택부터 엽니다.
                        try {
                          final saved = await YouTubeSavedDiscoveryService()
                              .save(event);
                          if (!mounted || !dialogContext.mounted) return;
                          Navigator.of(dialogContext).pop();
                          final destination = saved.destinationName?.trim();
                          final known =
                              destination != null && destination.isNotEmpty;
                          debugPrint(
                            '[YouTube Bridge] PLAN destination=${known ? destination : 'unknown'}',
                          );
                          _push(
                            TripPlacesScreen(
                              destination: known ? destination : null,
                              initialPlaces: {known ? destination : saved.title},
                            ),
                          );
                          if (!known) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content: Text(
                                  '영상에서 지역을 확인하지 못했어요. 여행지는 직접 입력해주세요.',
                                ),
                              ),
                            );
                          }
                        } catch (error) {
                          debugPrint('[YouTube Bridge] PLAN failed: $error');
                          if (!dialogContext.mounted) return;
                          setDialogState(() {
                            busy = null;
                            failure = '여행 계획을 시작하지 못했어요. 다시 눌러주세요.';
                          });
                        } finally {
                          _youtubePlanOpening = false;
                        }
                      },
                      icon: busy == 'plan'
                          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                          : const Icon(Icons.route),
                      label: Text(
                        busy == 'plan' ? '여행지 확인 중…' : '여행 계획하기',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ));
        },
      );
      dialog.whenComplete(() {
        if (_youtubeDialogContext?.mounted != true) _youtubeDialogContext = null;
      });
    });

    _syncYoutubeBridge();
    ActiveTripService.revision.addListener(_refreshActiveTrip);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (!_routeObserved && route is PageRoute) {
      appRouteObserver.subscribe(this, route);
      _routeObserved = true;
    }
  }

  // Another page pushed over Home, or Home popped/replaced: stop receiving.
  @override
  void didPushNext() => _setRouteVisible(false);

  @override
  void didPopNext() => _setRouteVisible(true);

  @override
  void didPop() => _setRouteVisible(false);

  void _setRouteVisible(bool visible) {
    _routeVisible = visible;
    _syncYoutubeBridge();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // `inactive` (permission sheets, notification shade) keeps the socket.
    if (state == AppLifecycleState.resumed) {
      _appForeground = true;
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden ||
        state == AppLifecycleState.detached) {
      _appForeground = false;
    } else {
      return;
    }
    _syncYoutubeBridge();
  }

  /// Starts or stops the YouTube bridge so it runs only while the Home tab is
  /// visible in the foreground.  Events sent while it is stopped are never
  /// replayed, so an old pause cannot appear after returning to Home.
  void _syncYoutubeBridge() {
    final wanted = mounted && _tab == 0 && _routeVisible && _appForeground;
    if (wanted == _youtubeBridgeActive) return;
    _youtubeBridgeActive = wanted;
    debugPrint(
      '[YouTube Bridge] HOME ${wanted ? 'active' : 'inactive'} '
      'tab=$_tab route_visible=$_routeVisible foreground=$_appForeground',
    );
    if (wanted) {
      unawaited(YoutubeBridgeService.instance.start());
    } else {
      unawaited(YoutubeBridgeService.instance.stop());
    }
  }

  @override
  void dispose() {
    _rainAlertTimer?.cancel();
    _youtubeSubscription?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    if (_routeObserved) appRouteObserver.unsubscribe(this);
    if (_youtubeBridgeActive) {
      _youtubeBridgeActive = false;
      unawaited(YoutubeBridgeService.instance.stop());
    }
    NotificationService.readIds.removeListener(_refreshNotificationBadge);
    InviteLinkService.pendingToken.removeListener(_openPendingInvite);
    WeatherNotificationService.instance.rainPlanRequested.removeListener(_openRequestedRainPlan);
    ActiveTripService.revision.removeListener(_refreshActiveTrip);
    _voiceSession++;
    _speech.cancel();
    _basicSearchController.dispose();
    _basicSearchFocusNode.dispose();
    _voicePulseController.dispose();
    super.dispose();
  }

  /// 초대 링크로 앱이 열렸으면 참여 창을 띄웁니다. 로그인 전이면 로그인 후 홈에서 띄웁니다.
  void _openPendingInvite() {
    if (!mounted || !AuthSession.isLoggedIn) return;
    final token = InviteLinkService.take();
    if (token == null) return;
    unawaited(showInviteJoinDialog(context, token));
  }

  /// 홈 위에 뜬 비 알림을 닫고 자동 닫힘 타이머를 정리합니다.
  void _refreshNotificationBadge() {
    if (mounted) setState(() {});
  }

  Future<void> _loadHomeWeather() async {
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        throw StateError('Location service is disabled.');
      }

      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        throw StateError('Location permission is unavailable.');
      }

      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
        ),
      );
      final weather = await _weatherService.getWeatherAt(
        latitude: position.latitude,
        longitude: position.longitude,
      );
      if (!mounted) return;
      final rainy = const {'비', '비/눈', '눈', '소나기'}.contains(weather.current.condition);
      setState(() {
        _homeWeather = weather;
        _homeWeatherState = _HomeWeatherState.loaded;
        // Rain on the trip: the alert card on Home and the phone notification
        // both lead to the rain plan (계획 2).
        if (rainy) _showRainAlert = true;
      });
      if (rainy) {
        unawaited(WeatherNotificationService.instance.notifyForWeather(weather, requestPermission: true));
      }
    } catch (_) {
      if (!mounted) return;
      setState(() => _homeWeatherState = _HomeWeatherState.error);
    }
  }

  void _refreshActiveTrip() {
    if (mounted) setState(() {});
  }

  void _dismissRainAlert() {
    _rainAlertTimer?.cancel();
    if (mounted && _showRainAlert) setState(() => _showRainAlert = false);
  }

  void _submitBasicSearch(String value) {
    if (_basicSearchOpening) return;
    final query = value.trim();
    if (query.isEmpty) return;
    _basicSearchOpening = true;
    _basicSearchFocusNode.unfocus();
    _basicSearchController.clear();
    _dismissRainAlert();
    Navigator.of(context)
        .push(
          MaterialPageRoute(
            builder: (_) =>
                TextSearchScreen(initialQuery: query, resultsOnly: true),
          ),
        )
        .whenComplete(() => _basicSearchOpening = false);
  }

  void _showYoutubeSearchOptions() {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => _YoutubeSearchSheet(
        onSearch: (url) {
          Navigator.of(sheetContext).pop();
          _push(TextSearchScreen(startWithLink: true, initialLink: url));
        },
        onSavedPlaces: () {
          Navigator.of(sheetContext).pop();
          _push(const YoutubeSavedScreen());
        },
      ),
    );
  }

  /// 하위 화면으로 이동합니다. 이동 전에 홈의 비 알림을 함께 닫습니다.
  void _push(Widget screen) {
    _dismissRainAlert();
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));
  }

  bool _voiceSessionActive(int session) =>
      mounted && _voiceOverlayVisible && _voiceSession == session && _tab == 0;

  void _closeVoiceSearch() {
    _voiceSession++;
    _voicePulseController.stop();
    _speech.cancel();
    if (!mounted) return;
    setState(() {
      _voiceOverlayVisible = false;
      _voiceListening = false;
      _voiceBusy = false;
    });
  }

  Future<void> _startVoiceSearch() async {
    if (_voiceBusy || _voiceOpeningResults) return;
    _dismissRainAlert();
    final session = ++_voiceSession;
    setState(() {
      _voiceOverlayVisible = true;
      _voiceListening = false;
      _voiceBusy = true;
      _voiceTranscript = '';
      _voiceMessage = '마이크 연결 중이에요. 권한 요청이 뜨면 허용해주세요.';
    });

    try {
      final available = await _speech.initialize(
        options: [stt.SpeechToText.androidNoBluetooth],
        onStatus: (status) {
          if (!_voiceSessionActive(session)) return;
          if (status == 'done' || status == 'notListening') {
            _voicePulseController.stop();
            setState(() {
              _voiceListening = false;
              _voiceMessage = _voiceTranscript.isEmpty
                  ? '음성을 듣지 못했어요. 다시 말하기를 눌러주세요.'
                  : '인식한 내용으로 검색할 수 있어요.';
            });
          }
        },
        onError: (_) {
          if (!_voiceSessionActive(session)) return;
          _voicePulseController.stop();
          setState(() {
            _voiceListening = false;
            _voiceBusy = false;
            _voiceMessage = '음성을 인식하지 못했어요. 마이크 권한을 확인하거나 다시 시도해주세요.';
          });
        },
      );
      if (!_voiceSessionActive(session)) return;
      if (!available) {
        setState(() {
          _voiceMessage = '음성 검색을 사용할 수 없어요. 마이크 권한을 확인해주세요.';
        });
        return;
      }

      final locales = await _speech.locales();
      if (!_voiceSessionActive(session)) return;
      final koreanLocales = locales.where(
        (locale) => locale.localeId.toLowerCase().startsWith('ko'),
      );
      await _speech.listen(
        listenOptions: stt.SpeechListenOptions(
          localeId: koreanLocales.isEmpty ? null : koreanLocales.first.localeId,
        ),
        onResult: (result) {
          if (!_voiceSessionActive(session)) return;
          final recognized = result.recognizedWords.trim();
          setState(() {
            _voiceTranscript = recognized;
            if (result.finalResult) {
              _voiceMessage = recognized.isEmpty
                  ? '음성을 듣지 못했어요. 다시 말하기를 눌러주세요.'
                  : '검색 결과를 열고 있어요.';
            }
          });
          if (result.finalResult && recognized.isNotEmpty) {
            _openVoiceResults(recognized);
          }
        },
      );
      if (!_voiceSessionActive(session)) return;
      setState(() {
        _voiceListening = _speech.isListening;
        if (_voiceListening) _voiceMessage = '음성 인식 중이에요. 여행지를 말씀해주세요.';
      });
      if (_voiceListening) _voicePulseController.repeat(reverse: true);
    } catch (_) {
      if (!_voiceSessionActive(session)) return;
      _voicePulseController.stop();
      setState(() {
        _voiceListening = false;
        _voiceMessage = '마이크를 시작할 수 없어요. 다시 시도해주세요.';
      });
    } finally {
      if (_voiceSessionActive(session)) setState(() => _voiceBusy = false);
    }
  }

  Future<void> _stopVoiceListening() async {
    if (_voiceBusy || !_voiceListening) return;
    final session = _voiceSession;
    await _speech.stop();
    if (!_voiceSessionActive(session)) return;
    _voicePulseController.stop();
    setState(() {
      _voiceListening = false;
      _voiceMessage = _voiceTranscript.isEmpty
          ? '음성 입력을 멈췄어요. 다시 말하기를 눌러주세요.'
          : '인식한 내용으로 검색할 수 있어요.';
    });
  }

  Future<void> _openVoiceResults(String query) async {
    if (query.isEmpty || _voiceOpeningResults) return;
    _voiceOpeningResults = true;
    _voiceSession++;
    _voicePulseController.stop();
    setState(() {
      _voiceOverlayVisible = false;
      _voiceListening = false;
      _voiceBusy = false;
    });
    try {
      await _speech.stop();
      if (!mounted) return;
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => TextSearchScreen(initialQuery: query),
        ),
      );
    } finally {
      _voiceOpeningResults = false;
    }
  }

  Widget _voiceSearchOverlay() => Align(
    alignment: Alignment.bottomCenter,
    child: Padding(
      padding: EdgeInsets.fromLTRB(ResponsiveLayout.pageHorizontal(context), 0, ResponsiveLayout.pageHorizontal(context), 20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Material(
          color: Colors.white,
          elevation: 18,
          borderRadius: BorderRadius.circular(28),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(22, 16, 22, 22),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '말로 찾기',
                        style: TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    IconButton(
                      onPressed: _closeVoiceSearch,
                      icon: const Icon(Icons.close_rounded),
                      tooltip: '음성 검색 닫기',
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                AnimatedBuilder(
                  animation: _voicePulseController,
                  builder: (context, child) => Transform.scale(
                    scale: _voiceListening
                        ? 1 + 0.08 * _voicePulseController.value
                        : 1,
                    child: child,
                  ),
                  child: Container(
                    width: 88,
                    height: 88,
                    decoration: const BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: LinearGradient(
                        colors: [AppColors.primary, AppColors.purple],
                      ),
                      boxShadow: [
                        BoxShadow(
                          color: Color(0x554169D8),
                          blurRadius: 24,
                          spreadRadius: 4,
                        ),
                      ],
                    ),
                    child: _voiceBusy
                        ? const Center(
                            child: CircularProgressIndicator(
                              color: Colors.white,
                            ),
                          )
                        : const Icon(
                            Icons.mic_rounded,
                            size: 42,
                            color: Colors.white,
                          ),
                  ),
                ),
                const SizedBox(height: 18),
                Semantics(
                  liveRegion: true,
                  child: Text(
                    _voiceMessage,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                if (_voiceTranscript.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Text(
                    '“$_voiceTranscript”',
                    textAlign: TextAlign.center,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppColors.primary,
                      fontSize: 18,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ],
                SizedBox(height: ResponsiveLayout.sectionSpacing(context)),
                SizedBox(
                  width: double.infinity,
                  height: 48,
                  child: _voiceListening
                      ? FilledButton.tonalIcon(
                          onPressed: _stopVoiceListening,
                          icon: const Icon(Icons.stop_rounded),
                          label: const Text('음성 입력 중지'),
                        )
                      : _voiceTranscript.isNotEmpty
                      ? FilledButton(
                          onPressed: () => _openVoiceResults(_voiceTranscript),
                          child: const Text('이 내용으로 검색'),
                        )
                      : FilledButton.tonalIcon(
                          onPressed: _voiceBusy ? null : _startVoiceSearch,
                          icon: const Icon(Icons.mic_rounded),
                          label: const Text('다시 말하기'),
                        ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );

  /// 기본 모드와 편한 모드를 전환하고 홈 탭으로 돌아갑니다.
  void _changeDisplayMode(bool seniorMode) {
    if (_seniorMode == seniorMode) return;
    setState(() {
      _seniorMode = seniorMode;
      DisplayModeService.seniorMode = seniorMode;
      _tab = 0;
      if (!seniorMode && _homeWeatherState != _HomeWeatherState.loaded) {
        _homeWeatherState = _HomeWeatherState.loading;
      }
    });
    if (!seniorMode && _homeWeatherState == _HomeWeatherState.loading) {
      unawaited(_loadHomeWeather());
    }
  }

  /// The phone's rain notification was tapped: same screen as the in-app alert.
  void _openRequestedRainPlan() {
    final request = WeatherNotificationService.instance.rainPlanRequested;
    if (!mounted || !request.value) return;
    request.value = false;
    _openRainPlan();
  }

  /// 비 알림을 누르면 비 오는 날에 맞춘 날씨·일정 화면을 엽니다.
  void _openRainPlan() {
    _dismissRainAlert();
    _push(const WeatherScreen(initialPlan: 2));
  }

  @override
  Widget build(BuildContext context) {
    // The tab changes in several places; follow it after this frame.
    if ((_tab == 0 && _routeVisible && _appForeground) != _youtubeBridgeActive) {
      scheduleMicrotask(() {
        if (mounted) _syncYoutubeBridge();
      });
    }
    final pages = <Widget>[
      _seniorMode ? _homeBody() : _basicHomeBody(),
      MapScreen(onBack: () => setState(() => _tab = 0)),
      YoutubeSavedScreen(
        showBottomNavigation: false,
        onBack: () => setState(() => _tab = 0),
      ),
      ProfileScreen(
        senior: _seniorMode,
        onModeChanged: _changeDisplayMode,
        onBack: () => setState(() => _tab = 0),
      ),
    ];
    return Scaffold(
      body: SafeArea(
        child: Stack(
          children: [
            pages[_tab],
            if (_tab == 0 && _showRainAlert)
              Positioned(
                top: 16,
                left: 16,
                right: 16,
                child: Material(
                  color: Colors.transparent,
                  child: InkWell(
                    onTap: _openRainPlan,
                    borderRadius: BorderRadius.circular(16),
                    child: Ink(
                      padding: EdgeInsets.all(ResponsiveLayout.cardPadding(context)),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(16),
                        border: Border.all(color: const Color(0x334169D8)),
                        boxShadow: const [
                          BoxShadow(
                            color: Color(0x26000000),
                            blurRadius: 14,
                            offset: Offset(0, 5),
                          ),
                        ],
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('🌧️', style: TextStyle(fontSize: 30)),
                          SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '날씨 알림',
                                  style: TextStyle(
                                    fontSize: 14,
                                    fontWeight: FontWeight.w900,
                                    color: AppColors.primary,
                                  ),
                                ),
                                SizedBox(height: 4),
                                Text(
                                  '${_homeWeather?.current.condition ?? '비'} 예보가 있어요.',
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                                SizedBox(height: 4),
                                Text(
                                  '강수확률 ${_homeWeather?.current.precipitationProbability ?? '-'}% · 실내 중심 계획 2를 확인해보세요.',
                                  style: TextStyle(
                                    fontSize: 13,
                                    color: Color(0xFF4B5563),
                                    height: 1.35,
                                  ),
                                ),
                                SizedBox(height: 7),
                                Text(
                                  '눌러서 오늘 일정 확인하기',
                                  style: TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w800,
                                    color: AppColors.primary,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            if (_tab == 0 && _voiceOverlayVisible) ...[
              Positioned.fill(
                child: GestureDetector(
                  onTap: _closeVoiceSearch,
                  child: const ColoredBox(color: Color(0x770C1734)),
                ),
              ),
              _voiceSearchOverlay(),
            ],
          ],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (value) {
          if (_voiceOverlayVisible) _closeVoiceSearch();
          _dismissRainAlert();
          setState(() => _tab = value);
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home),
            label: '홈',
          ),
          NavigationDestination(
            icon: Icon(Icons.map_outlined),
            selectedIcon: Icon(Icons.map),
            label: '탐색',
          ),
          NavigationDestination(
            icon: Icon(Icons.bookmark_outline),
            selectedIcon: Icon(Icons.bookmark),
            label: '저장',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: '마이',
          ),
        ],
      ),
    );
  }

  /// 기본 모드는 빠른 탐색과 여행 시작에 집중한 컴팩트한 홈입니다.
  /// 기본 모드에서 검색·날씨·일정·여행 만들기를 조합하는 홈 화면입니다.
  Widget _basicHomeBody() {
    final (weatherHeadline, weatherDetail) = _basicWeatherText;
    final hasTrip = ActiveTripService.places.isNotEmpty;
    final tripDates = ActiveTripService.dates;
    final departure = tripDates?.start;
    final today = DateUtils.dateOnly(DateTime.now());
    final departureDay = departure == null
        ? null
        : DateUtils.dateOnly(departure);
    final daysUntilDeparture = departureDay?.difference(today).inDays;
    final dDayLabel = daysUntilDeparture == null || daysUntilDeparture < 0
        ? null
        : daysUntilDeparture == 0
        ? 'D-Day'
        : 'D-$daysUntilDeparture';
    final tripName = hasTrip ? '${ActiveTripService.places.first} 여행' : '새 여행';
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFFF4F6FF), Color(0xFFF9FAFF), Color(0xFFF4FBFA)],
        ),
      ),
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(ResponsiveLayout.pageHorizontal(context), 14, ResponsiveLayout.pageHorizontal(context), 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '보고가고 🚀',
                        style: TextStyle(
                          fontSize: 15,
                          color: AppColors.primary,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      SizedBox(height: 3),
                      Text(
                        AuthSession.greeting,
                        style: const TextStyle(
                          fontSize: 23,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ],
                  ),
                ),
                IconButton.filledTonal(
                  onPressed: () => _push(const NotificationsScreen()),
                  icon: Stack(
                    clipBehavior: Clip.none,
                    children: [
                      Icon(Icons.notifications_none_rounded, size: 29),
                      if (NotificationService.unreadCount > 0)
                        Positioned(
                          top: -4,
                          right: -5,
                          child: CircleAvatar(
                            radius: 8,
                            backgroundColor: Color(0xFFD9363E),
                            child: Text(
                              '${NotificationService.unreadCount}',
                              style: TextStyle(
                                fontSize: 10,
                                color: Colors.white,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                  tooltip: '알림',
                  style: IconButton.styleFrom(fixedSize: const Size(48, 48)),
                ),
              ],
            ),
            SizedBox(height: ResponsiveLayout.sectionSpacing(context)),
            // 오늘 날씨를 요약하고, 누르면 7일 예보 화면으로 이동합니다.
            Material(
              color: const Color(0xFFE9F1FF),
              borderRadius: BorderRadius.circular(20),
              child: InkWell(
                onTap: () => _push(const WeatherScreen()),
                borderRadius: BorderRadius.circular(20),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 18,
                    vertical: 16,
                  ),
                  child: Row(
                    children: [
                      const Icon(
                        Icons.thunderstorm_rounded,
                        color: Color(0xFF4169D8),
                        size: 34,
                      ),
                      const SizedBox(width: 13),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '오늘 날씨',
                              style: TextStyle(
                                fontSize: 14,
                                color: Color(0xFF4169D8),
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            SizedBox(height: 3),
                            Text(
                              weatherHeadline,
                              style: TextStyle(
                                fontSize: ResponsiveLayout.isCompact(context) ? 16 : 18,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                            SizedBox(height: 2),
                            Text(
                              weatherDetail,
                              style: TextStyle(
                                fontSize: 12,
                                color: Color(0xFF4B5563),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const Icon(Icons.chevron_right, color: Color(0xFF4169D8)),
                    ],
                  ),
                ),
              ),
            ),
            SizedBox(height: ResponsiveLayout.sectionSpacing(context)),
            Container(
              width: double.infinity,
              padding: EdgeInsets.all(ResponsiveLayout.pageHorizontal(context)),
              decoration: BoxDecoration(
                color: const Color(0xFF192B61),
                borderRadius: BorderRadius.circular(24),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '여행 계획을 더 쉽게',
                    style: TextStyle(
                      color: Color(0xFFC7D4F8),
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 5),
                  const Text(
                    '나에게 맞는 여행 코스',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 7),
                  const Text(
                    '저장한 장소를 바탕으로 나만의 여행을 만들어보세요.',
                    style: TextStyle(color: Color(0xFFE0E7FF), fontSize: 14),
                  ),
                  SizedBox(height: ResponsiveLayout.sectionSpacing(context)),
                  Material(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(17),
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(16, 6, 8, 6),
                      child: Row(
                        children: [
                          const Icon(Icons.search_rounded, size: 25),
                          const SizedBox(width: 10),
                          Expanded(
                            child: TextField(
                              controller: _basicSearchController,
                              focusNode: _basicSearchFocusNode,
                              textInputAction: TextInputAction.search,
                              onSubmitted: _submitBasicSearch,
                              decoration: const InputDecoration(
                                hintText: '여행지나 장소를 검색해보세요',
                                hintStyle: TextStyle(
                                  color: Color(0xFF9CA3AF),
                                  fontSize: 14,
                                ),
                                border: InputBorder.none,
                                isDense: true,
                              ),
                            ),
                          ),
                          IconButton.filled(
                            onPressed: _startVoiceSearch,
                            icon: const Icon(Icons.mic_none_rounded),
                            tooltip: '음성으로 찾기',
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: _BasicSearchShortcut(
                          icon: Icons.play_circle_fill_rounded,
                          label: 'YouTube',
                          color: const Color(0xFFEF4444),
                          onTap: _showYoutubeSearchOptions,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: _BasicSearchShortcut(
                          icon: Icons.image_search_outlined,
                          label: '앨범에서 찾기',
                          color: const Color(0xFF4169D8),
                          onTap: () =>
                              _push(const CameraScreen(galleryOnly: true)),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: _BasicSearchShortcut(
                          icon: Icons.camera_alt_outlined,
                          label: '사진으로 찾기',
                          color: const Color(0xFF0F766E),
                          onTap: () => _push(const CameraScreen()),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            SizedBox(height: ResponsiveLayout.sectionSpacing(context)),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [Color(0xFF4169D8), Color(0xFF6E8DFA)],
                ),
                borderRadius: BorderRadius.circular(22),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Text(
                              '다가오는 여행',
                              style: TextStyle(
                                color: Color(0xFFDCE6FF),
                                fontSize: 13,
                              ),
                            ),
                            if (dDayLabel != null) ...[
                              const SizedBox(width: 8),
                              Text(
                                dDayLabel,
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontSize: 13,
                                  fontWeight: FontWeight.w900,
                                ),
                              ),
                            ],
                          ],
                        ),
                        const SizedBox(height: 5),
                        Text(
                          tripName,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 20,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        const SizedBox(height: 5),
                        Text(
                          hasTrip
                              ? '확정한 일정과 이동 경로를 확인하세요.'
                              : '지금 여행 계획을 시작해보세요.',
                          style: const TextStyle(
                            color: Color(0xFFE7EDFF),
                            fontSize: 13,
                          ),
                        ),
                      ],
                    ),
                  ),
                  TextButton(
                    onPressed: () => hasTrip
                        ? _push(
                            ItineraryScreen(
                              session: _itinerarySession,
                              tripDates: ActiveTripService.dates,
                              transport: ActiveTripService.transport,
                              places: ActiveTripService.places,
                            ),
                          )
                        : _push(const TripPlacesScreen()),
                    style: TextButton.styleFrom(foregroundColor: Colors.white),
                    child: Text(hasTrip ? '일정 확인 →' : '시작하기 →'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 편한 모드에서 큰 검색 버튼과 메뉴 카드를 보여주는 홈 화면입니다.
  (String, String) get _basicWeatherText {
    switch (_homeWeatherState) {
      case _HomeWeatherState.loading:
        return ('현재 위치 날씨를 확인하고 있어요', '잠시만 기다려주세요');
      case _HomeWeatherState.error:
        return ('날씨 정보를 확인할 수 없어요', '카드를 눌러 현재 위치 날씨 보기');
      case _HomeWeatherState.loaded:
        final weather = _homeWeather!;
        final temperature = weather.current.temperature;
        final condition = weather.current.condition;
        final temperatureText = temperature == null
            ? '--'
            : '${temperature.toStringAsFixed(temperature == temperature.roundToDouble() ? 0 : 1)}°C';
        final conditionText = condition == null || condition.isEmpty
            ? ''
            : ' · $condition';
        final precipitation = weather.current.precipitationProbability;
        return (
          '${weather.locationName}  $temperatureText$conditionText',
          precipitation == null ? '강수확률 --' : '강수확률 $precipitation%',
        );
    }
  }

  Widget _homeBody() {
    final menus = <_HomeMenu>[
      _HomeMenu(
        Icons.calendar_month_outlined,
        '전체 일정',
        () => _push(
          ItineraryScreen(
            session: _itinerarySession,
            tripDates: ActiveTripService.dates,
            transport: ActiveTripService.transport,
          ),
        ),
      ),
      _HomeMenu(
        Icons.today_outlined,
        '오늘의 일정',
        () => _push(const TodayTravelScreen()),
      ),
      _HomeMenu(
        Icons.camera_alt_outlined,
        '사진으로 찾기',
        () => _push(const CameraScreen()),
      ),
      _HomeMenu(
        Icons.cloud_outlined,
        '오늘 날씨',
        () => _push(const WeatherScreen()),
      ),
    ];
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFFF3F7FF), Color(0xFFF9F5FF), Color(0xFFF2FBF8)],
        ),
      ),
      child: Padding(
        padding: EdgeInsets.fromLTRB(ResponsiveLayout.pageHorizontal(context), ResponsiveLayout.sectionSpacing(context), ResponsiveLayout.pageHorizontal(context), 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '보고가고 ✨',
                      style: TextStyle(
                        fontSize: 16,
                        color: AppColors.primary,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    SizedBox(height: 4),
                    Text(
                      AuthSession.greeting,
                      style: const TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ],
                ),
                ),
                IconButton.filledTonal(
                  onPressed: () => _push(const NotificationsScreen()),
                  icon: Stack(
                    clipBehavior: Clip.none,
                    children: [
                      Icon(Icons.notifications_none, size: 29),
                      if (NotificationService.unreadCount > 0)
                        Positioned(
                          top: -4,
                          right: -5,
                          child: CircleAvatar(
                            radius: 8,
                            backgroundColor: Color(0xFFD9363E),
                            child: Text(
                              '${NotificationService.unreadCount}',
                              style: TextStyle(
                                fontSize: 10,
                                color: Colors.white,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                  tooltip: '알림',
                  style: IconButton.styleFrom(fixedSize: const Size(48, 48)),
                ),
              ],
            ),
            SizedBox(height: ResponsiveLayout.sectionSpacing(context)),
            _section(
              title: '어디로 여행 갈까요?',
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: _SearchTile(
                          icon: Icons.search,
                          label: '직접 입력',
                          color: AppColors.soft,
                          onTap: () => _push(const TextSearchScreen()),
                        ),
                      ),
                      SizedBox(width: ResponsiveLayout.gap(context)),
                      Expanded(
                        child: _SearchTile(
                          icon: Icons.mic_none_rounded,
                          label: '말로 찾기',
                          color: AppColors.soft,
                          onTap: _startVoiceSearch,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            SizedBox(height: ResponsiveLayout.sectionSpacing(context)),
            const Text(
              '무엇을 도와드릴까요?',
              style: TextStyle(fontSize: 21, fontWeight: FontWeight.w900),
            ),
            SizedBox(height: ResponsiveLayout.gap(context)),
            Expanded(
              child: GridView.builder(
                itemCount: menus.length,
                gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: ResponsiveLayout.twoColumnCount(context),
                  mainAxisSpacing: ResponsiveLayout.gap(context),
                  crossAxisSpacing: ResponsiveLayout.gap(context),
                  mainAxisExtent: ResponsiveLayout.homeMenuExtent(context),
                ),
                itemBuilder: (context, index) {
                  final menu = menus[index];
                  const menuColors = <Color>[
                    Color(0xFF4169D8),
                    Color(0xFFF05A2A),
                    Color(0xFF7043C9),
                    Color(0xFFF59E0B),
                  ];
                  final menuColor = menuColors[index];
                  return InkWell(
                    onTap: menu.onTap,
                    borderRadius: BorderRadius.circular(24),
                    child: Ink(
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(24),
                        boxShadow: const [
                          BoxShadow(
                            color: Color(0x0D000000),
                            blurRadius: 8,
                            offset: Offset(0, 2),
                          ),
                        ],
                      ),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Container(
                            width: ResponsiveLayout.isCompact(context) ? 48 : 58,
                            height: ResponsiveLayout.isCompact(context) ? 48 : 58,
                            decoration: BoxDecoration(
                              color: AppColors.soft,
                              shape: BoxShape.circle,
                            ),
                            child: Icon(menu.icon, size: ResponsiveLayout.isCompact(context) ? 27 : 31, color: menuColor),
                          ),
                          SizedBox(height: ResponsiveLayout.gap(context)),
                          Text(
                            menu.label,
                            style: TextStyle(
                              fontSize: ResponsiveLayout.isCompact(context) ? 16 : 18,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 제목과 콘텐츠를 흰 카드 안에 담는 편한 모드용 공통 섹션입니다.
  Widget _section({required String title, required Widget child}) => Container(
    padding: EdgeInsets.all(ResponsiveLayout.cardPadding(context)),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(24),
      boxShadow: const [BoxShadow(color: Color(0x0D000000), blurRadius: 8)],
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
        ),
        SizedBox(height: ResponsiveLayout.gap(context)),
        child,
      ],
    ),
  );
}

class _YoutubeSearchSheet extends StatefulWidget {
  const _YoutubeSearchSheet({
    required this.onSearch,
    required this.onSavedPlaces,
  });

  final ValueChanged<String> onSearch;
  final VoidCallback onSavedPlaces;

  @override
  State<_YoutubeSearchSheet> createState() => _YoutubeSearchSheetState();
}

class _YoutubeSearchSheetState extends State<_YoutubeSearchSheet> {
  final _urlController = TextEditingController();
  final _urlFocusNode = FocusNode();
  bool _showUrlField = false;
  String? _error;

  @override
  void dispose() {
    _urlController.dispose();
    _urlFocusNode.dispose();
    super.dispose();
  }

  void _openUrlField() {
    setState(() => _showUrlField = true);
    Future<void>.delayed(const Duration(milliseconds: 280), () {
      if (mounted && _showUrlField) _urlFocusNode.requestFocus();
    });
  }

  void _submitUrl() {
    final url = _urlController.text.trim();
    final uri = Uri.tryParse(url);
    if (uri == null ||
        (uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.isEmpty) {
      setState(() => _error = 'http:// 또는 https://로 시작하는 링크를 입력해주세요.');
      return;
    }
    widget.onSearch(url);
  }

  @override
  Widget build(BuildContext context) => SafeArea(
    child: Padding(
      padding: EdgeInsets.fromLTRB(
        20,
        4,
        20,
        24 + MediaQuery.viewInsetsOf(context).bottom,
      ),
      child: SingleChildScrollView(
        child: AnimatedSize(
          duration: const Duration(milliseconds: 260),
          curve: Curves.easeInOut,
          child: ClipRect(
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 260),
              switchInCurve: Curves.easeInOut,
              switchOutCurve: Curves.easeInOut,
              transitionBuilder: (child, animation) => SlideTransition(
                position: Tween<Offset>(
                  begin: child.key == const ValueKey('url')
                      ? const Offset(1, 0)
                      : const Offset(-1, 0),
                  end: Offset.zero,
                ).animate(animation),
                child: child,
              ),
              child: _showUrlField
                  ? Column(
                      key: const ValueKey('url'),
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            IconButton(
                              onPressed: () {
                                _urlFocusNode.unfocus();
                                setState(() => _showUrlField = false);
                              },
                              icon: const Icon(Icons.chevron_left_rounded),
                              tooltip: '이전',
                            ),
                            const SizedBox(width: 4),
                            const Text(
                              'YouTube URL 붙여넣기',
                              style: TextStyle(
                                fontSize: 20,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                          ],
                        ),
                        SizedBox(height: ResponsiveLayout.sectionSpacing(context)),
                        TextField(
                          controller: _urlController,
                          focusNode: _urlFocusNode,
                          keyboardType: TextInputType.url,
                          textInputAction: TextInputAction.search,
                          onChanged: (_) {
                            if (_error != null) setState(() => _error = null);
                          },
                          onSubmitted: (_) => _submitUrl(),
                          decoration: InputDecoration(
                            prefixIcon: const Icon(Icons.link_rounded),
                            hintText: 'YouTube URL을 붙여넣어 주세요',
                            errorText: _error,
                            suffixIcon: IconButton(
                              onPressed: _submitUrl,
                              icon: const Icon(Icons.search),
                              tooltip: '링크 검색',
                            ),
                          ),
                        ),
                      ],
                    )
                  : Column(
                      key: const ValueKey('options'),
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'YouTube로 장소 찾기',
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        const SizedBox(height: 6),
                        const Text(
                          '새 영상 링크를 분석하거나 저장한 장소를 확인할 수 있어요.',
                          style: TextStyle(color: Color(0xFF6B7280)),
                        ),
                        SizedBox(height: ResponsiveLayout.gap(context)),
                        ListTile(
                          leading: const Icon(
                            Icons.link_rounded,
                            color: Color(0xFFEF4444),
                          ),
                          title: const Text('YouTube URL 붙여넣기'),
                          subtitle: const Text('영상 링크에서 장소 찾기'),
                          onTap: _openUrlField,
                        ),
                        ListTile(
                          leading: const Icon(
                            Icons.bookmark_outline_rounded,
                            color: AppColors.primary,
                          ),
                          title: const Text('저장한 YouTube 장소 보기'),
                          subtitle: const Text('저장해 둔 여행지 확인'),
                          onTap: widget.onSavedPlaces,
                        ),
                      ],
                    ),
            ),
          ),
        ),
      ),
    ),
  );
}

/// 편한 모드 홈에서 직접 검색 또는 음성 검색을 여는 버튼 카드입니다.
enum _HomeWeatherState { loading, loaded, error }

class _BasicSearchShortcut extends StatelessWidget {
  const _BasicSearchShortcut({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.white,
    borderRadius: BorderRadius.circular(14),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: SizedBox(
        height: 58,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 22, color: color),
            const SizedBox(height: 3),
            Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800),
            ),
          ],
        ),
      ),
    ),
  );
}

class _SearchTile extends StatelessWidget {
  const _SearchTile({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Material(
    color: color,
    borderRadius: BorderRadius.circular(18),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(18),
      child: SizedBox(
        height: 64,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, color: AppColors.primary, size: 26),
            const SizedBox(height: 2),
            Text(
              label,
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w800,
                color: AppColors.primary,
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

/// 편한 모드 홈의 메뉴 카드에 사용할 아이콘·이름·동작을 묶은 데이터입니다.
class _HomeMenu {
  const _HomeMenu(this.icon, this.label, this.onTap);
  final IconData icon;
  final String label;
  final VoidCallback onTap;
}
