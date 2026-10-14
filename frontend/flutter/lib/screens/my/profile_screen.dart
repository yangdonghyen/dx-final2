import 'package:flutter/material.dart';

import 'upcoming_trips_screen.dart';
import '../../core/layout/app_responsive.dart';
import '../../core/theme/app_theme.dart';
import '../../services/auth_service.dart';
import '../../services/trip_service.dart';
import '../../services/youtube_saved_discovery_service.dart';
import '../auth/login_screen.dart';
import '../preference/youtube_saved_screen.dart';
import '../travel/today_travel_screen.dart';
import 'past_trips_screen.dart';

/// 웹 앱의 최신 마이페이지 구조를 반영한 Flutter 화면이다.
class ProfileScreen extends StatefulWidget {
  const ProfileScreen({
    super.key,
    this.senior = false,
    this.onModeChanged,
    this.onBack,
  });
  final bool senior;
  final ValueChanged<bool>? onModeChanged;
  final VoidCallback? onBack;
  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late bool senior = widget.senior;

  final TripService _tripService = TripService();
  int? _pastTripCount;
  int? _upcomingTripCount;
  int? _savedPlaceCount;

  final YouTubeSavedDiscoveryService _savedDiscoveryService =
      YouTubeSavedDiscoveryService();
  @override
  void didUpdateWidget(covariant ProfileScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    senior = widget.senior;
  }

  /// 프로필 동그라미에 넣는 이름 첫 글자입니다.
  String get _nameInitial {
    final label = AuthSession.shortLabel;
    return label.isEmpty ? '' : label.characters.first.toUpperCase();
  }

  /// 현재 표시 모드를 기본 모드와 편한 모드 사이에서 전환합니다.
  void _toggleDisplayMode() {
    final nextMode = !senior;
    if (widget.onModeChanged != null) {
      widget.onModeChanged!(nextMode);
    } else {
      setState(() => senior = nextMode);
    }
  }

  /// 마이페이지 메뉴에서 선택한 상세 화면으로 이동합니다.
  void _push(Widget screen) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));

  /// 로그아웃을 확인한 뒤 인증 정보를 비우고 로그인 화면으로 돌아갑니다.
  void _handleBack() {
    final onBack = widget.onBack;
    if (onBack != null) {
      onBack();
      return;
    }
    Navigator.of(context).maybePop();
  }

  Future<void> _confirmLogout() async {
    final shouldLogout = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('로그아웃할까요?'),
        content: const Text('다시 이용하려면 로그인해야 합니다.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('로그아웃'),
          ),
        ],
      ),
    );
    if (shouldLogout != true || !mounted) return;
    await AuthSession.clear();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  /// 두 마이페이지의 맨 아래에 공통으로 표시하는 로그아웃 버튼입니다.
  Widget _logoutButton() => SizedBox(
    width: double.infinity,
    height: senior ? 56 : 48,
    child: FilledButton.icon(
      onPressed: _confirmLogout,
      icon: Icon(Icons.logout_rounded, size: senior ? 24 : 21),
      label: Text(
        '로그아웃',
        style: TextStyle(
          fontSize: senior ? 18 : 15,
          fontWeight: FontWeight.w800,
        ),
      ),
      style: FilledButton.styleFrom(
        backgroundColor: const Color(0xFFD92D20),
        foregroundColor: Colors.white,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    ),
  );

  /// 회원 탈퇴 의사를 한 번 더 확인하고, 현재 앱의 로그인 정보를 정리합니다.
  @override
  void initState() {
    super.initState();
    _loadTripStats();
    _loadSavedPlaceCount();
  }

  Future<void> _loadTripStats() async {
    try {
      final trips = await _tripService.list();

      final now = DateTime.now();
      final today = DateTime(now.year, now.month, now.day);

      final pastCount = trips.where((trip) {
        final endDate = trip.endDate;
        if (endDate == null) {
          return false;
        }

        final endDay = DateTime(endDate.year, endDate.month, endDate.day);

        return endDay.isBefore(today);
      }).length;

      final upcomingCount = trips.where((trip) {
        final startDate = trip.startDate;
        if (startDate == null) {
          return false;
        }

        final status = trip.status.toUpperCase();

        if (status == 'CANCELLED' ||
            status == 'COMPLETED' ||
            status == 'IN_PROGRESS' ||
            status == 'ARCHIVED') {
          return false;
        }

        final startDay = DateTime(
          startDate.year,
          startDate.month,
          startDate.day,
        );

        return !startDay.isBefore(today);
      }).length;

      if (!mounted) {
        return;
      }

      setState(() {
        _pastTripCount = pastCount;
        _upcomingTripCount = upcomingCount;
      });
    } catch (_) {
      // 최초 조회 실패 시 "-" 표시.
      // 재조회 실패 시에는 이전 성공값을 유지합니다.
    }
  }

  Future<void> _loadSavedPlaceCount() async {
    try {
      final savedItems = await _savedDiscoveryService.list();

      if (!mounted) {
        return;
      }

      setState(() {
        _savedPlaceCount = savedItems.length;
      });
    } catch (_) {
      // 최초 조회 실패 시 "-" 표시.
      // 재조회 실패 시에는 이전 성공값을 유지합니다.
    }
  }

  Future<void> _openPastTrips() async {
    await Navigator.of(
      context,
    ).push(MaterialPageRoute(builder: (_) => const PastTripsScreen()));

    await _loadTripStats();
    _loadSavedPlaceCount();
  }

  Future<void> _openSavedPlaces() async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => const YoutubeSavedScreen(selectedTab: 3),
      ),
    );

    await _loadSavedPlaceCount();
  }

  Future<void> _confirmWithdrawal() async {
    const reasons = <String>[
      '서비스를 자주 사용하지 않아요',
      '원하는 여행 정보를 찾기 어려워요',
      '앱 사용이 불편해요',
      '다른 서비스를 이용하고 있어요',
      '기타',
    ];
    String? selectedReason;

    final reason = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) => StatefulBuilder(
        builder: (context, setSheetState) => SafeArea(
          child: Container(
            padding: EdgeInsets.fromLTRB(ResponsiveLayout.pageHorizontal(context), 12, ResponsiveLayout.pageHorizontal(context), 20),
            decoration: const BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    width: 40,
                    height: 4,
                    decoration: BoxDecoration(
                      color: const Color(0xFFD1D5DB),
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                const Text(
                  '떠나시는 이유를 알려주세요',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 6),
                const Text(
                  '더 나은 여행 서비스를 만드는 데 참고할게요.',
                  style: TextStyle(color: Color(0xFF6B7280)),
                ),
                const SizedBox(height: 12),
                RadioGroup<String>(
                  groupValue: selectedReason,
                  onChanged: (value) =>
                      setSheetState(() => selectedReason = value),
                  child: Column(
                    children: reasons
                        .map(
                          (reason) => RadioListTile<String>(
                            value: reason,
                            contentPadding: EdgeInsets.zero,
                            activeColor: AppColors.primary,
                            title: Text(
                              reason,
                              style: const TextStyle(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                        )
                        .toList(),
                  ),
                ),
                const SizedBox(height: 8),
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: FilledButton(
                    onPressed: selectedReason == null
                        ? null
                        : () => Navigator.pop(sheetContext, selectedReason),
                    child: const Text('다음'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
    if (reason == null || !mounted) return;

    final shouldWithdraw = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('정말 탈퇴하실 건가요?'),
        content: Text('선택한 사유: $reason\n\n탈퇴하면 현재 앱의 로그인 정보가 삭제됩니다.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFD92D20),
            ),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('탈퇴하기'),
          ),
        ],
      ),
    );
    if (shouldWithdraw != true || !mounted) return;
    await AuthSession.clear();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  Widget _withdrawalButton() => Center(
    child: TextButton(
      onPressed: _confirmWithdrawal,
      style: TextButton.styleFrom(
        foregroundColor: const Color(0xFFB42318),
        minimumSize: Size.zero,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
      child: Text(
        '회원 탈퇴',
        style: TextStyle(
          fontSize: senior ? 14 : 12,
          decoration: TextDecoration.underline,
        ),
      ),
    ),
  );
  @override
  Widget build(BuildContext context) =>
      senior ? _comfortProfile() : _basicProfile();

  /// 편한 모드용 큰 카드·격자형 마이페이지를 구성합니다.
  Widget _comfortProfile() => Container(
    decoration: const BoxDecoration(
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color(0xFFF3F7FF), Color(0xFFF9F5FF), Color(0xFFF2FBF8)],
      ),
    ),
    child: ListView(
      padding: EdgeInsets.fromLTRB(ResponsiveLayout.pageHorizontal(context), 12, ResponsiveLayout.pageHorizontal(context), 10),
      children: [
        Row(
          children: [
            IconButton(
              onPressed: _handleBack,
              tooltip: '뒤로가기',
              icon: const Icon(Icons.chevron_left_rounded),
              style: IconButton.styleFrom(
                padding: EdgeInsets.zero,
                minimumSize: const Size(36, 36),
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
            ),
            const SizedBox(width: 2),
            const Text(
              '마이페이지',
              style: TextStyle(fontSize: 27, fontWeight: FontWeight.w900),
            ),
          ],
        ),
        const SizedBox(height: 16),
        _profileSummary(),
        const SizedBox(height: 16),
        Container(
          padding: EdgeInsets.all(ResponsiveLayout.cardPadding(context)),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(24),
          ),
          child: Column(
            children: [
              GridView.count(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisCount: ResponsiveLayout.twoColumnCount(context),
                mainAxisSpacing: ResponsiveLayout.gap(context),
                crossAxisSpacing: ResponsiveLayout.gap(context),
                mainAxisExtent: ResponsiveLayout.profileMenuExtent(context),
                children: [
                  _menu(
                    Icons.calendar_month_outlined,
                    '내 여행 일정',
                    const Color(0xFF4169D8),
                    () => _push(const TodayTravelScreen()),
                  ),
                  _menu(
                    Icons.flight_takeoff_outlined,
                    '지난 여행',
                    const Color(0xFF8B5E3C),
                    _openPastTrips,
                  ),
                  _menu(
                    Icons.bookmark_outline,
                    '저장한 장소',
                    const Color(0xFFD14D72),
                    _openSavedPlaces,
                  ),
                  _seniorMenu(),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _logoutButton(),
        const SizedBox(height: 4),
        _withdrawalButton(),
      ],
    ),
  );

  /// 기본 모드용 목록형 마이페이지를 구성합니다.
  Widget _basicProfile() => Container(
    color: const Color(0xFFF7F8FC),
    child: ListView(
      padding: EdgeInsets.fromLTRB(ResponsiveLayout.pageHorizontal(context), 14, ResponsiveLayout.pageHorizontal(context), 12),
      children: [
        Row(
          children: [
            IconButton(
              onPressed: _handleBack,
              tooltip: '뒤로가기',
              icon: const Icon(Icons.chevron_left_rounded),
              style: IconButton.styleFrom(
                padding: EdgeInsets.zero,
                minimumSize: const Size(36, 36),
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
            ),
            const SizedBox(width: 2),
            const Text(
              '마이페이지',
              style: TextStyle(fontSize: 26, fontWeight: FontWeight.w900),
            ),
          ],
        ),
        const SizedBox(height: 12),
        _basicProfileCard(),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: _BasicStat(
                value: _pastTripCount?.toString() ?? '-',
                label: '지난 여행',
              ),
            ),
            SizedBox(width: 12),
            Expanded(
              child: _BasicStat(
                value: _savedPlaceCount?.toString() ?? '-',
                label: '저장 장소',
              ),
            ),
            SizedBox(width: 12),
            Expanded(
              child: InkWell(
                borderRadius: BorderRadius.circular(14),
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const UpcomingTripsScreen()),
                ),
                child: _BasicStat(
                  value: _upcomingTripCount?.toString() ?? '-',
                  label: '예정 여행',
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        const _SectionTitle('여행 관리'),
        const SizedBox(height: 10),
        _basicMenuGroup([
          _basicMenu(
            Icons.calendar_month_outlined,
            '내 여행 일정',
            () => _push(const TodayTravelScreen()),
          ),
          _basicMenu(Icons.flight_takeoff_outlined, '지난 여행', _openPastTrips),
          _basicMenu(Icons.bookmark_outline, '저장한 장소', _openSavedPlaces),
        ]),
        const SizedBox(height: 16),
        const _SectionTitle('앱 설정'),
        const SizedBox(height: 10),
        _basicMenuGroup([
          _basicMenu(
            Icons.text_fields_rounded,
            '편한 모드로 전환',
            _toggleDisplayMode,
          ),
        ]),
        const SizedBox(height: 12),
        _logoutButton(),
        const SizedBox(height: 4),
        _withdrawalButton(),
      ],
    ),
  );

  Widget _basicProfileCard() => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(18),
    ),
    child: Row(
      children: [
        Container(
          width: 46,
          height: 46,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: AppColors.primary,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Text(
            _nameInitial,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 22,
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
                AuthSession.profileTitle,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 3),
              const Text(
                '다음 여행을 준비하고 있어요',
                style: TextStyle(color: Color(0xFF6B7280)),
              ),
            ],
          ),
        ),
      ],
    ),
  );

  Widget _basicMenu(IconData icon, String label, VoidCallback onTap) =>
      ListTile(
        dense: true,
        visualDensity: VisualDensity.compact,
        leading: Icon(icon, color: AppColors.primary),
        title: Text(label, style: const TextStyle(fontWeight: FontWeight.w700)),
        trailing: const Icon(Icons.chevron_right, color: Color(0xFF9CA3AF)),
        onTap: onTap,
      );

  /// 관련 메뉴 항목을 구분선이 있는 하나의 목록 카드로 묶습니다.
  Widget _basicMenuGroup(List<Widget> items) => Container(
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(18),
    ),
    child: Column(
      children: [
        for (var index = 0; index < items.length; index++) ...[
          items[index],
          if (index < items.length - 1)
            const Divider(height: 1, indent: 56, endIndent: 16),
        ],
      ],
    ),
  );
  Widget _profileSummary() => Container(
    padding: EdgeInsets.all(ResponsiveLayout.cardPadding(context)),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(24),
    ),
    child: Column(
      children: [
        Row(
          children: [
            Container(
              width: 56,
              height: 56,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: AppColors.primary,
                borderRadius: BorderRadius.circular(18),
              ),
              child: Text(
                _nameInitial,
                style: const TextStyle(
                  fontSize: 24,
                  color: Colors.white,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ),
            const SizedBox(width: 13),
            Expanded(child: Text(
              AuthSession.profileTitle,
              style: TextStyle(
                fontSize: senior ? 22 : 20,
                fontWeight: FontWeight.w900,
              ),
            ),
          ),
          ],
        ),
        const SizedBox(height: 14),
        Row(
          children: [
            Expanded(
              child: _Stat(
                '지난 여행',
                _pastTripCount == null ? '-' : '$_pastTripCount회',
              ),
            ),
            SizedBox(height: 38, child: VerticalDivider()),
            Expanded(
              child: _Stat(
                '저장 장소',
                _savedPlaceCount == null ? '-' : '$_savedPlaceCount곳',
              ),
            ),
          ],
        ),
      ],
    ),
  );

  Widget _menu(IconData icon, String label, Color color, VoidCallback tap) =>
      Material(
        color: const Color(0xFFF9FAFF),
        borderRadius: BorderRadius.circular(20),
        child: InkWell(
          onTap: tap,
          borderRadius: BorderRadius.circular(20),
          child: Padding(
            padding: const EdgeInsets.all(13),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Container(
                  width: 52,
                  height: 52,
                  decoration: BoxDecoration(
                    color: color,
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Icon(icon, color: Colors.white, size: 28),
                ),
                Text(
                  label,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: senior ? 16 : 15,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ],
            ),
          ),
        ),
      );

  Widget _seniorMenu() => Material(
    color: senior ? AppColors.soft : const Color(0xFFF9FAFF),
    borderRadius: BorderRadius.circular(20),
    child: InkWell(
      onTap: _toggleDisplayMode,
      borderRadius: BorderRadius.circular(20),
      child: Padding(
        padding: const EdgeInsets.all(13),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Container(
              width: 52,
              height: 52,
              decoration: BoxDecoration(
                color: const Color(0xFF0F766E),
                borderRadius: BorderRadius.circular(16),
              ),
              child: const Icon(
                Icons.text_fields_rounded,
                color: Colors.white,
                size: 28,
              ),
            ),
            Text(
              senior ? '기본 모드로 전환' : '편한 모드로 전환',
              style: TextStyle(
                fontSize: senior ? 16 : 15,
                fontWeight: FontWeight.w900,
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class _Stat extends StatelessWidget {
  const _Stat(this.label, this.value);
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Column(
    children: [
      Text(
        label,
        style: const TextStyle(fontSize: 12, color: Color(0xFF6B7280)),
      ),
      const SizedBox(height: 4),
      Text(
        value,
        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900),
      ),
    ],
  );
}

class _BasicStat extends StatelessWidget {
  const _BasicStat({required this.value, required this.label});
  final String value;
  final String label;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(vertical: 10),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(14),
    ),
    child: Column(
      children: [
        Text(
          value,
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 3),
        Text(
          label,
          style: const TextStyle(fontSize: 12, color: Color(0xFF6B7280)),
        ),
      ],
    ),
  );
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Text(
    text,
    style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
  );
}
