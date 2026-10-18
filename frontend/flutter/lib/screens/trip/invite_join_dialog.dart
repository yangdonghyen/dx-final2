import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';
import '../../data/api/api_client.dart';
import '../../services/active_trip_loader.dart';
import '../../services/trip_service.dart';

/// 초대 링크로 앱이 열렸을 때 여행 정보를 보여주고 참여를 묻습니다.
Future<void> showInviteJoinDialog(BuildContext context, String token) {
  return showDialog<void>(
    context: context,
    builder: (_) => _InviteJoinDialog(token: token),
  );
}

class _InviteJoinDialog extends StatefulWidget {
  const _InviteJoinDialog({required this.token});

  final String token;

  @override
  State<_InviteJoinDialog> createState() => _InviteJoinDialogState();
}

class _InviteJoinDialogState extends State<_InviteJoinDialog> {
  final TripService _tripService = TripService();
  SharedTrip? _trip;
  String? _error;
  bool _joining = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final trip = await _tripService.sharedTrip(widget.token);
      if (!mounted) return;
      setState(() {
        _trip = trip;
        if (!trip.isInvite) _error = '보기 전용 링크라 참여할 수 없어요.';
      });
    } catch (error) {
      debugPrint('[Invite] shared trip load failed: $error');
      if (mounted) setState(() => _error = _errorMessage(error));
    }
  }

  Future<void> _join() async {
    setState(() => _joining = true);
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    try {
      final joined = await _tripService.joinSharedTripWithId(widget.token);
      // The companion edits this trip next, so Home's 전체 일정 opens it
      // (not the companion's own trip).
      var opened = false;
      final tripId = joined.tripId;
      if (tripId != null) {
        try {
          final trip = await findServerTrip(tripId);
          if (trip != null) opened = await activateServerTrip(trip);
        } catch (error) {
          debugPrint('[Invite] could not open the joined trip: $error');
        }
      }
      navigator.pop();
      messenger.showSnackBar(
        SnackBar(
          content: Text(opened
              ? '여행에 참여했어요. 홈의 전체 일정에서 함께 수정할 수 있어요.'
              : joined.alreadyJoined
              ? '이미 참여한 여행이에요. 마이 > 내 여행 일정에서 볼 수 있어요.'
              : '여행에 참여했어요. 마이 > 내 여행 일정에서 함께 수정할 수 있어요.'),
        ),
      );
    } catch (error) {
      debugPrint('[Invite] join failed: $error');
      if (!mounted) return;
      setState(() {
        _joining = false;
        _error = _errorMessage(error);
      });
    }
  }

  static String _errorMessage(Object error) {
    if (error is StateError) return '로그인한 뒤 다시 링크를 열어주세요.';
    if (error is! ApiException) return '초대 정보를 불러오지 못했어요. 인터넷 연결을 확인해주세요.';
    final detail = error.body['error'];
    final code = detail is Map ? detail['code'] : null;
    switch (code) {
      case 'SHARE_LINK_EXPIRED':
        return '초대 링크가 만료됐어요. 친구에게 새 링크를 받아주세요.';
      case 'SHARE_LINK_NOT_FOUND':
        return '초대 링크를 찾을 수 없어요.';
      case 'SHARE_LINK_NOT_INVITE':
        return '보기 전용 링크라 참여할 수 없어요.';
      case 'OWNER_CANNOT_JOIN':
        return '내가 만든 여행이에요.';
    }
    if (error.statusCode == 401) return '로그인이 만료됐어요. 다시 로그인한 뒤 링크를 열어주세요.';
    return '참여하지 못했어요. 잠시 후 다시 시도해주세요.';
  }

  static String _date(DateTime date) =>
      '${date.year}.${date.month.toString().padLeft(2, '0')}.${date.day.toString().padLeft(2, '0')}';

  String _dates(SharedTrip trip) {
    final parts = [
      trip.startDate,
      trip.endDate,
    ].whereType<DateTime>().map(_date);
    return parts.isEmpty ? '날짜 미정' : parts.join(' ~ ');
  }

  String _title(SharedTrip trip) {
    final title = trip.title?.trim();
    if (title != null && title.isNotEmpty) return title;
    final destination = trip.destination?.trim();
    if (destination != null && destination.isNotEmpty) return '$destination 여행';
    return '여행';
  }

  @override
  Widget build(BuildContext context) {
    final trip = _trip;
    final canJoin = trip != null && trip.isInvite && _error == null;
    return AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      title: const Text(
        '여행 초대',
        style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
      ),
      content: SingleChildScrollView(
        child: trip == null && _error == null
            ? const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Center(child: CircularProgressIndicator()),
              )
            : Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (trip != null) ..._tripInfo(trip),
                  if (_error != null) ...[
                    if (trip != null) const SizedBox(height: 14),
                    Text(
                      _error!,
                      style: const TextStyle(
                        fontSize: 16,
                        color: Color(0xFFB91C1C),
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ],
              ),
      ),
      actions: [
        TextButton(
          onPressed: _joining ? null : () => Navigator.of(context).pop(),
          child: Text(
            canJoin ? '다음에' : '닫기',
            style: const TextStyle(fontSize: 16),
          ),
        ),
        if (canJoin)
          FilledButton(
            onPressed: _joining ? null : _join,
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.primary,
              minimumSize: const Size(110, 48),
            ),
            child: _joining
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Text(
                    '참여하기',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                  ),
          ),
      ],
    );
  }

  List<Widget> _tripInfo(SharedTrip trip) {
    final owner = trip.ownerNickname?.trim();
    return [
      Text(
        owner != null && owner.isNotEmpty
            ? '$owner님이 ${_title(trip)}에 초대했어요.'
            : '${_title(trip)}에 초대받았어요.',
        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
      ),
      const SizedBox(height: 6),
      Text(
        _dates(trip),
        style: const TextStyle(fontSize: 15, color: Color(0xFF6B7280)),
      ),
      const SizedBox(height: 14),
      _infoRow(
        '동행자',
        trip.companions.isEmpty ? '아직 동행자가 없어요' : trip.companions.join(', '),
      ),
      const SizedBox(height: 8),
      _infoRow('방문할 장소', _placesText(trip)),
    ];
  }

  /// Picked places first; a trip made without picking shows its itinerary.
  String _placesText(SharedTrip trip) {
    final places = trip.selectedPlaces.isNotEmpty ? trip.selectedPlaces : trip.planPlaces;
    if (places.isEmpty) return '아직 정해진 장소가 없어요';
    const shown = 4;
    if (places.length <= shown) return places.join(' · ');
    return '${places.take(shown).join(' · ')} 외 ${places.length - shown}곳';
  }

  Widget _infoRow(String label, String value) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        label,
        style: const TextStyle(fontSize: 14, color: Color(0xFF6B7280)),
      ),
      const SizedBox(height: 2),
      Text(
        value,
        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ],
  );
}
