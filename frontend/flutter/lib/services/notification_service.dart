import 'package:flutter/foundation.dart';

import '../data/api/api_client.dart';
import 'auth_service.dart';
import 'trip_service.dart';

enum NotificationKind { itineraryChange, general }

class AppNotification {
  const AppNotification({
    required this.id,
    required this.kind,
    required this.emoji,
    required this.title,
    required this.body,
  });

  final String id;
  final NotificationKind kind;
  final String emoji;
  final String title;
  final String body;
}

/// 홈 배지와 알림함이 함께 사용하는 앱 내부 알림 상태입니다.
///
/// 현재 MVP에서는 Backend에 실제 저장된 Trip의 시작일을 기준으로
/// D-7, D-1, D-Day 알림만 생성합니다.
class NotificationService {
  NotificationService._();

  static final List<AppNotification> notices = <AppNotification>[];

  static final ValueNotifier<Set<String>> _readIds = ValueNotifier(<String>{});

  static ValueListenable<Set<String>> get readIds => _readIds;

  static bool isUnread(String id) => !_readIds.value.contains(id);

  static int get unreadCount =>
      notices.where((item) => isUnread(item.id)).length;

  static int get unreadItineraryCount => notices
      .where(
        (item) =>
            item.kind == NotificationKind.itineraryChange && isUnread(item.id),
      )
      .length;

  static int get unreadGeneralCount => notices
      .where(
        (item) => item.kind == NotificationKind.general && isUnread(item.id),
      )
      .length;

  /// The newest companion news (joined / edited) that arrived since the
  /// last check; Home shows it as a popup.
  static final ValueNotifier<AppNotification?> companionAlert = ValueNotifier(null);
  static Set<String>? _knownServerIds;

  // Today's rain / heat alert, also shown in the bell (id: weather-2-… for
  // rain, weather-3-… for heat; the number is the weather plan to open).
  static AppNotification? _weatherNotice;

  static void setWeatherNotice({
    required int plan,
    required String day,
    required String title,
    required String body,
  }) {
    final notice = AppNotification(
      id: 'weather-$plan-$day',
      kind: NotificationKind.general,
      emoji: plan == 3 ? '🥵' : '🌧️',
      title: title,
      body: body,
    );
    _weatherNotice = notice;
    notices
      ..removeWhere((item) => item.id.startsWith('weather-'))
      ..insert(0, notice);
    _readIds.value = {..._readIds.value}; // redraw the bell badge
  }

  /// 2 (rain) or 3 (heat) for a weather notice id, otherwise 0.
  static int weatherPlanOf(String id) =>
      id.startsWith('weather-') ? int.tryParse(id.split('-')[1]) ?? 0 : 0;

  static Future<void> refreshFromTrips() async {
    final trips = await TripService().list();

    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);

    final nextNotices = <AppNotification>[];

    for (final trip in trips) {
      final startDate = trip.startDate;
      if (startDate == null) {
        continue;
      }

      final status = trip.status.toUpperCase();

      if (status == 'CANCELLED' ||
          status == 'COMPLETED' ||
          status == 'IN_PROGRESS' ||
          status == 'ARCHIVED') {
        continue;
      }

      final startDay = DateTime(startDate.year, startDate.month, startDate.day);

      final daysUntilStart = startDay.difference(today).inDays;
      final tripName = _tripName(trip);

      if (daysUntilStart == 7) {
        nextNotices.add(
          AppNotification(
            id: 'trip-${trip.tripId}-d7',
            kind: NotificationKind.general,
            emoji: '✈️',
            title: '여행 D-7',
            body: '$tripName이 7일 남았어요.',
          ),
        );
      } else if (daysUntilStart == 1) {
        nextNotices.add(
          AppNotification(
            id: 'trip-${trip.tripId}-d1',
            kind: NotificationKind.general,
            emoji: '🧳',
            title: '여행 D-1',
            body: '$tripName이 내일 시작돼요.',
          ),
        );
      } else if (daysUntilStart == 0) {
        nextNotices.add(
          AppNotification(
            id: 'trip-${trip.tripId}-day',
            kind: NotificationKind.general,
            emoji: '🎉',
            title: '오늘 여행이 시작돼요',
            body: '$tripName 일정이 오늘 시작돼요.',
          ),
        );
      }
    }

    // Shared-trip events from the server: a companion joined, the plan was
    // edited by someone else.  Read ones stay read across devices.
    final serverRead = <String>{};
    try {
      final token = AuthSession.accessToken;
      if (token != null) {
        final response = await ApiClient().get('/api/v1/notifications', accessToken: token);
        final rows = response['notifications'];
        if (rows is List) {
          // Newest companion news goes above the trip reminders.
          var serverIndex = 0;
          for (final row in rows.whereType<Map<String, dynamic>>()) {
            final id = 'srv-${row['notification_id']}';
            final kind = row['kind']?.toString();
            nextNotices.insert(serverIndex++, AppNotification(
              id: id,
              kind: kind == 'PLAN_EDITED' ? NotificationKind.itineraryChange : NotificationKind.general,
              emoji: kind == 'PLAN_EDITED' ? '📝' : kind == 'MEMBER_LEFT' ? '👋' : '🙋',
              title: row['title']?.toString() ?? '알림',
              body: row['body']?.toString() ?? '',
            ));
            if (row['read'] == true) serverRead.add(id);
          }
        }
      }
    } catch (error) {
      debugPrint('[Notifications] server list failed: $error');
    }

    final weather = _weatherNotice;
    if (weather != null) nextNotices.insert(0, weather);

    // First load only learns what is there; later loads pop up what is new.
    final serverNotices = nextNotices.where((item) => item.id.startsWith('srv-')).toList();
    final known = _knownServerIds;
    if (known != null) {
      final fresh = serverNotices.where((item) => !known.contains(item.id) && !serverRead.contains(item.id));
      if (fresh.isNotEmpty) companionAlert.value = fresh.first;
    }
    _knownServerIds = serverNotices.map((item) => item.id).toSet();

    notices
      ..clear()
      ..addAll(nextNotices);

    final activeIds = notices.map((item) => item.id).toSet();

    _readIds.value = {
      ..._readIds.value.where((id) => activeIds.contains(id)),
      ...serverRead,
    };
  }

  static String _tripName(TripListItem trip) {
    final title = trip.title?.trim();
    if (title != null && title.isNotEmpty) {
      return title;
    }

    final destination = trip.destination?.trim();
    if (destination != null && destination.isNotEmpty) {
      return '$destination 여행';
    }

    return '여행';
  }

  // 현재 실제 협업 일정 변경 이벤트가 없으므로
  // 기존 호출부 호환성만 유지하고 알림은 생성하지 않습니다.
  static void addEditStarted({required String place}) {}

  static void addEditCompleted({required String place}) {}

  static void markRead(String id) {
    if (!isUnread(id)) {
      return;
    }

    _readIds.value = {..._readIds.value, id};
  }

  static void markAllRead() {
    _readIds.value = notices.map((item) => item.id).toSet();
    final token = AuthSession.accessToken;
    if (token != null && notices.any((item) => item.id.startsWith('srv-'))) {
      ApiClient()
          .post('/api/v1/notifications/read-all', accessToken: token)
          .catchError((Object error) {
        debugPrint('[Notifications] read-all failed: $error');
        return <String, dynamic>{};
      });
    }
  }
}
