import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';
import '../../services/notification_service.dart';
import '../../services/weather_notification_service.dart';

class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  bool _loading = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    // A companion may have joined or edited since Home last looked.
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadNotifications());
  }

  Future<void> _loadNotifications() async {
    setState(() {
      _loading = true;
      _errorMessage = null;
    });

    try {
      await NotificationService.refreshFromTrips();

      if (!mounted) {
        return;
      }

      setState(() {
        _loading = false;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }

      setState(() {
        _loading = false;
        _errorMessage = '알림을 불러오지 못했어요.';
      });
    }
  }

  // 실제 여행 알림(D-7/D-1/D-Day)은 특정 일정 화면으로 연결할 데이터가 없어
  // 읽음 처리만 합니다.
  void _openNotification(AppNotification item) {
    NotificationService.markRead(item.id);
    // 비·폭염 알림: Home opens 오늘 날씨 at the matching plan.
    final weatherPlan = NotificationService.weatherPlanOf(item.id);
    if (weatherPlan != 0) {
      WeatherNotificationService.instance.weatherPlanRequested.value = weatherPlan;
      Navigator.of(context).maybePop();
      return;
    }
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<Set<String>>(
      valueListenable: NotificationService.readIds,
      builder: (context, readIds, _) {
        final unreadCount = NotificationService.unreadCount;

        return Scaffold(
          backgroundColor: const Color(0xFFF7F8FF),
          appBar: AppBar(
            leading: IconButton(
              onPressed: () => Navigator.of(context).maybePop(),
              icon: const Icon(Icons.chevron_left_rounded),
              tooltip: '뒤로가기',
            ),
            title: const Text('알림'),
            backgroundColor: Colors.white,
            actions: [
              TextButton(
                onPressed: unreadCount > 0
                    ? NotificationService.markAllRead
                    : null,
                child: const Text('모두 읽음'),
              ),
            ],
          ),
          body: _buildBody(readIds),
        );
      },
    );
  }

  Widget _buildBody(Set<String> readIds) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_errorMessage != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.error_outline_rounded,
                size: 52,
                color: Color(0xFF9CA3AF),
              ),
              const SizedBox(height: 14),
              Text(
                _errorMessage!,
                style: const TextStyle(fontSize: 16, color: Color(0xFF6B7280)),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _loadNotifications,
                child: const Text('다시 시도'),
              ),
            ],
          ),
        ),
      );
    }

    if (NotificationService.notices.isEmpty) {
      return RefreshIndicator(
        onRefresh: _loadNotifications,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: const [
            SizedBox(height: 150),
            Icon(
              Icons.notifications_none_rounded,
              size: 62,
              color: Color(0xFFB8BFCC),
            ),
            SizedBox(height: 16),
            Center(
              child: Text(
                '새로운 알림이 없어요',
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                  color: AppColors.ink,
                ),
              ),
            ),
            SizedBox(height: 7),
            Center(
              child: Text(
                '여행 일정이 가까워지면 알려드릴게요.',
                style: TextStyle(fontSize: 14, color: Color(0xFF9CA3AF)),
              ),
            ),
          ],
        ),
      );
    }

    final unreadItinerary = NotificationService.unreadItineraryCount;
    final unreadGeneral = NotificationService.unreadGeneralCount;
    final hasUnread = unreadItinerary + unreadGeneral > 0;

    return RefreshIndicator(
      onRefresh: _loadNotifications,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(20),
        children: [
          Container(
            padding: const EdgeInsets.all(15),
            decoration: BoxDecoration(
              color: hasUnread ? const Color(0xFFFFF5F5) : AppColors.soft,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Row(
              children: [
                Icon(
                  hasUnread
                      ? Icons.notifications_active_rounded
                      : Icons.notifications_none_rounded,
                  color: hasUnread
                      ? const Color(0xFFD9363E)
                      : AppColors.primary,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    hasUnread
                        ? '일정 변경 $unreadItinerary건 · 일반 알림 $unreadGeneral건'
                        : '새 알림이 없어요',
                    style: const TextStyle(fontWeight: FontWeight.w900),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          ...NotificationService.notices.map((item) {
            final unread = !readIds.contains(item.id);
            final isItinerary = item.kind == NotificationKind.itineraryChange;

            return Card(
              margin: const EdgeInsets.only(bottom: 10),
              elevation: 0,
              color: unread
                  ? (isItinerary ? const Color(0xFFFFF5F5) : AppColors.soft)
                  : Colors.white,
              child: InkWell(
                borderRadius: BorderRadius.circular(16),
                onTap: () => _openNotification(item),
                child: Padding(
                  padding: const EdgeInsets.all(15),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(item.emoji, style: const TextStyle(fontSize: 26)),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              item.title,
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              item.body,
                              style: const TextStyle(
                                height: 1.4,
                                color: Color(0xFF4B5563),
                              ),
                            ),
                          ],
                        ),
                      ),
                      if (unread)
                        const Padding(
                          padding: EdgeInsets.only(top: 4),
                          child: CircleAvatar(
                            radius: 4,
                            backgroundColor: Color(0xFFD9363E),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            );
          }),
        ],
      ),
    );
  }
}
