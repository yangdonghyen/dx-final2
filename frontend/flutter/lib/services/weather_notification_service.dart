import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'notification_service.dart';
import 'weather_service.dart';

/// Android 시스템 알림 전용 서비스입니다. 앱 내부 여행 알림과 분리합니다.
class WeatherNotificationService {
  WeatherNotificationService._();

  static final WeatherNotificationService instance =
      WeatherNotificationService._();

  static const _channelId = 'weather_alerts';
  static const _channelName = '날씨 알림';
  static const _channelDescription = '현재 위치의 강수 예보 알림';
  static const _sentKeyPrefix = 'weather_notification_sent';
  static const _precipitationConditions = {'비', '비/눈', '눈', '소나기'};

  final FlutterLocalNotificationsPlugin _notifications =
      FlutterLocalNotificationsPlugin();
  Future<void>? _initialization;

  /// The weather plan to open after the user taps a weather notification
  /// (app running or cold start): 2 for rain, 3 for a heat wave, 0 for none.
  /// Home opens it once signed in, then resets it.
  final ValueNotifier<int> weatherPlanRequested = ValueNotifier(0);

  static const _payload = 'weather';
  static const _heatPayload = 'weather_heat';

  void _onTap(NotificationResponse response) {
    if (response.payload == _payload) weatherPlanRequested.value = 2;
    if (response.payload == _heatPayload) weatherPlanRequested.value = 3;
  }

  Future<void> initialize() => _ensureInitialized();

  Future<void> notifyForWeather(
    WeatherData weather, {
    DateTime? now,
    bool requestPermission = false,
  }) async {
    final heat = !isRainyWeather(weather) && isHeatWave(weather);
    final condition = heat ? '폭염' : weather.current.condition;
    if (condition == null || !(heat || _precipitationConditions.contains(condition))) {
      return;
    }

    // The bell (알림함) keeps today's alert too, even without OS permission.
    final today = now ?? DateTime.now();
    final bellContent = _notificationContent(condition);
    NotificationService.setWeatherNotice(
      plan: heat ? 3 : 2,
      day: '${today.year}${today.month}${today.day}',
      title: bellContent.title,
      body: bellContent.body,
    );

    try {
      await _ensureInitialized();

      final android = _notifications
          .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin
          >();
      final permissionGranted = requestPermission
          ? await android?.requestNotificationsPermission() ?? false
          : await android?.areNotificationsEnabled() ?? false;
      if (!permissionGranted) return;

      final date = now ?? DateTime.now();
      final sentKey = _sentKey(date, condition);
      final preferences = await SharedPreferences.getInstance();
      // Once a day, except in the filming build where every take needs it.
      if (!demoWeatherOn && (preferences.getBool(sentKey) ?? false)) return;

      final content = _notificationContent(condition);
      await _notifications.show(
        id: _notificationId(sentKey),
        title: content.title,
        body: content.body,
        notificationDetails: const NotificationDetails(
          android: AndroidNotificationDetails(
            _channelId,
            _channelName,
            channelDescription: _channelDescription,
            importance: Importance.high,
            priority: Priority.high,
          ),
        ),
        payload: heat ? _heatPayload : _payload,
      );
      await preferences.setBool(sentKey, true);
    } catch (_) {
      // 알림 권한/플랫폼 오류는 날씨 조회 결과에 영향을 주지 않습니다.
    }
  }

  /// A companion joined or edited the trip: a phone notification too.
  Future<void> showTripUpdate(String title, String body) async {
    try {
      await _ensureInitialized();
      await _notifications.show(
        id: DateTime.now().millisecondsSinceEpoch ~/ 1000 % 100000,
        title: title,
        body: body,
        notificationDetails: const NotificationDetails(
          android: AndroidNotificationDetails(
            'trip_updates',
            '동행자 알림',
            channelDescription: '동행자가 여행에 참여하거나 일정을 수정했을 때',
            importance: Importance.high,
            priority: Priority.high,
          ),
        ),
      );
    } catch (_) {
      // The popup in the app still shows it.
    }
  }

  Future<void> _ensureInitialized() =>
      _initialization ??= _initializeNotifications();

  Future<void> _initializeNotifications() async {
    const settings = InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    );
    await _notifications.initialize(
      settings: settings,
      onDidReceiveNotificationResponse: _onTap,
    );
    final launch = await _notifications.getNotificationAppLaunchDetails();
    final response = launch?.notificationResponse;
    if ((launch?.didNotificationLaunchApp ?? false) && response != null) {
      _onTap(response);
    }

    final android = _notifications
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >();
    await android?.createNotificationChannel(
      const AndroidNotificationChannel(
        _channelId,
        _channelName,
        description: _channelDescription,
        importance: Importance.high,
      ),
    );
  }

  String _sentKey(DateTime date, String condition) {
    final day =
        '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
    return '$_sentKeyPrefix:$day:$condition';
  }

  int _notificationId(String value) => value.codeUnits.fold(
    0,
    (hash, codeUnit) => (hash * 31 + codeUnit) & 0x7fffffff,
  );

  _NotificationContent _notificationContent(String condition) =>
      switch (condition) {
        '비' => const _NotificationContent(
          '오늘 비가 와요',
          '현재 위치에 비 예보가 있어요. 실내 중심 여행 계획을 확인해보세요.',
        ),
        '비/눈' => const _NotificationContent(
          '오늘 비와 눈이 와요',
          '현재 위치에 비와 눈 예보가 있어요. 실내 중심 여행 계획을 확인해보세요.',
        ),
        '눈' => const _NotificationContent(
          '오늘 눈이 와요',
          '현재 위치에 눈 예보가 있어요. 실내 중심 여행 계획을 확인해보세요.',
        ),
        '소나기' => const _NotificationContent(
          '오늘 소나기가 와요',
          '현재 위치에 소나기 예보가 있어요. 실내 중심 여행 계획을 확인해보세요.',
        ),
        '폭염' => const _NotificationContent(
          '오늘 폭염이에요',
          '현재 위치의 기온이 매우 높아요. 실내 중심 계획 3을 확인해보세요.',
        ),
        _ => throw ArgumentError.value(condition, 'condition'),
      };
}

class _NotificationContent {
  const _NotificationContent(this.title, this.body);

  final String title;
  final String body;
}
