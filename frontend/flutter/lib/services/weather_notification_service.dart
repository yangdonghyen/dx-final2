import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';

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

  /// True after the user taps a rain notification (app running or cold
  /// start).  Home opens the rain plan (계획 2) once signed in, then resets it.
  final ValueNotifier<bool> rainPlanRequested = ValueNotifier(false);

  static const _payload = 'weather';

  void _onTap(NotificationResponse response) {
    if (response.payload == _payload) rainPlanRequested.value = true;
  }

  Future<void> initialize() => _ensureInitialized();

  Future<void> notifyForWeather(
    WeatherData weather, {
    DateTime? now,
    bool requestPermission = false,
  }) async {
    final condition = weather.current.condition;
    if (condition == null || !_precipitationConditions.contains(condition)) {
      return;
    }

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
      if (!demoRain && (preferences.getBool(sentKey) ?? false)) return;

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
        payload: _payload,
      );
      await preferences.setBool(sentKey, true);
    } catch (_) {
      // 알림 권한/플랫폼 오류는 날씨 조회 결과에 영향을 주지 않습니다.
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
        _ => throw ArgumentError.value(condition, 'condition'),
      };
}

class _NotificationContent {
  const _NotificationContent(this.title, this.body);

  final String title;
  final String body;
}
