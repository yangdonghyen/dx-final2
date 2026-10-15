import 'package:flutter/material.dart';

import '../../core/layout/app_responsive.dart';
import '../../core/theme/app_theme.dart';
import '../../services/display_mode_service.dart';
import '../../services/youtube_saved_discovery_service.dart';
import '../../widgets/app_bottom_navigation.dart';
import 'saved_photo_places_screen.dart';
import 'youtube_saved_detail_screen.dart';

class YoutubeSavedScreen extends StatefulWidget {
  const YoutubeSavedScreen({
    super.key,
    this.selectedTab = 2,
    this.showBottomNavigation = true,
    this.onBack,
  });

  final int selectedTab;
  final bool showBottomNavigation;
  final VoidCallback? onBack;

  @override
  State<YoutubeSavedScreen> createState() => _YoutubeSavedScreenState();
}

class _YoutubeSavedScreenState extends State<YoutubeSavedScreen> {
  final YouTubeSavedDiscoveryService _service = YouTubeSavedDiscoveryService();
  /// One card per video: the newest save of it (a video paused at several
  /// points used to show up once per pause).
  List<YouTubeSavedDiscovery> _discoveries = const [];
  List<YouTubeSavedDiscovery> _allSaves = const [];

  static List<YouTubeSavedDiscovery> latestPerVideo(List<YouTubeSavedDiscovery> saves) {
    final seen = <String>{};
    return [for (final save in saves) if (seen.add(save.videoId)) save];
  }
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _loadSavedDiscoveries();
  }

  Future<void> _loadSavedDiscoveries() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final discoveries = await _service.list();
      if (!mounted) return;
      setState(() {
        _allSaves = discoveries;
        _discoveries = latestPerVideo(discoveries);
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error;
        _loading = false;
      });
    }
  }

  Future<void> _confirmDelete(YouTubeSavedDiscovery item) async {
    final shouldDelete = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('저장한 영상을 삭제할까요?'),
        content: Text(item.title),
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
            child: const Text('삭제하기'),
          ),
        ],
      ),
    );
    if (shouldDelete != true || !mounted) return;
    try {
      // The card stands for every save of this video, so all of them go.
      for (final save in _allSaves.where((saved) => saved.videoId == item.videoId)) {
        await _service.delete(save.savedDiscoveryId);
      }
      if (!mounted) return;
      setState(() {
        _allSaves = _allSaves.where((saved) => saved.videoId != item.videoId).toList();
        _discoveries = latestPerVideo(_allSaves);
      });
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('저장한 영상을 삭제하지 못했어요. 다시 시도해 주세요.')),
      );
    }
  }

  void _push(BuildContext context, Widget screen) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));

  void _openDetail(YouTubeSavedDiscovery item) {
    _push(context, YouTubeSavedDetailScreen(discovery: item));
  }

  void _handleBack(BuildContext context) {
    final onBack = widget.onBack;
    if (onBack != null) {
      onBack();
      return;
    }
    Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) => DisplayModeService.seniorMode
      ? _comfortSavedPage(context)
      : _basicSavedPage(context);

  void _openPhotoPlaces(BuildContext context) =>
      _push(context, SavedPhotoPlacesScreen(selectedTab: widget.selectedTab));

  /// 편한 모드에서 큰 2열 카드로 저장한 영상을 보여줍니다.
  Widget _comfortSavedPage(BuildContext context) => Scaffold(
    backgroundColor: const Color(0xFFF7F8FF),
    body: SafeArea(
      child: Column(
        children: [
          Padding(
            padding: EdgeInsets.fromLTRB(
              ResponsiveLayout.pageHorizontal(context),
              24,
              ResponsiveLayout.pageHorizontal(context),
              12,
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                IconButton(
                  onPressed: () => _handleBack(context),
                  tooltip: '뒤로가기',
                  icon: const Icon(Icons.chevron_left_rounded),
                ),
                const SizedBox(width: 4),
                const Expanded(
                  child: Text(
                    '내가 발견한 여행지',
                    style: TextStyle(
                      fontSize: 24,
                      fontWeight: FontWeight.w800,
                      color: AppColors.ink,
                    ),
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.only(top: 4),
                  child: Row(
                    children: [
                      Icon(
                        Icons.play_circle_fill,
                        color: Color(0xFFEF4444),
                        size: 16,
                      ),
                      SizedBox(width: 4),
                      Text(
                        'YouTube 저장',
                        style: TextStyle(
                          fontSize: 12,
                          color: Color(0xFF9CA3AF),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: _ActionCard(onTap: () => _openPhotoPlaces(context)),
          ),
          Expanded(child: _comfortBody()),
        ],
      ),
    ),
    bottomNavigationBar: widget.showBottomNavigation
        ? AppBottomNavigation(selectedIndex: widget.selectedTab)
        : null,
  );

  Widget _comfortBody() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return _errorState();
    if (_discoveries.isEmpty) return _emptyState();
    return RefreshIndicator(
      onRefresh: _loadSavedDiscoveries,
      child: GridView.builder(
        padding: EdgeInsets.fromLTRB(
          ResponsiveLayout.pageHorizontal(context),
          0,
          ResponsiveLayout.pageHorizontal(context),
          20,
        ),
        itemCount: _discoveries.length,
        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: ResponsiveLayout.twoColumnCount(context),
          crossAxisSpacing: 12,
          mainAxisSpacing: 12,
          mainAxisExtent: ResponsiveLayout.savedPlaceExtent(context),
        ),
        itemBuilder: (context, index) => _comfortCard(_discoveries[index]),
      ),
    );
  }

  Widget _comfortCard(YouTubeSavedDiscovery item) => Material(
    color: Colors.white,
    borderRadius: BorderRadius.circular(16),
    child: InkWell(
      onTap: () => _openDetail(item),
      borderRadius: BorderRadius.circular(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 4,
            child: Stack(
              fit: StackFit.expand,
              children: [
                _thumbnail(
                  item,
                  borderRadius: const BorderRadius.vertical(
                    top: Radius.circular(16),
                  ),
                ),
                const Positioned(top: 8, left: 8, child: _YoutubeIcon()),
              ],
            ),
          ),
          Expanded(
            flex: 5,
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: _videoText(item, compact: true)),
                  Align(
                    alignment: Alignment.centerRight,
                    child: _DeleteButton(
                      onPressed: () => _confirmDelete(item),
                      compact: true,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    ),
  );

  /// 기본 모드에서 저장한 영상을 빠르게 훑을 수 있는 세로 목록입니다.
  Widget _basicSavedPage(BuildContext context) => Scaffold(
    backgroundColor: const Color(0xFFF7F8FC),
    body: SafeArea(
      child: RefreshIndicator(
        onRefresh: _loadSavedDiscoveries,
        child: ListView(
          padding: EdgeInsets.fromLTRB(
            ResponsiveLayout.pageHorizontal(context),
            24,
            ResponsiveLayout.pageHorizontal(context),
            28,
          ),
          children: [
            Row(
              children: [
                IconButton(
                  onPressed: () => _handleBack(context),
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
                  '저장한 장소',
                  style: TextStyle(fontSize: 26, fontWeight: FontWeight.w900),
                ),
              ],
            ),
            const SizedBox(height: 5),
            Text(
              _loading
                  ? 'YouTube에서 저장한 여행 영상을 불러오는 중이에요'
                  : 'YouTube에서 저장한 여행 영상 ${_discoveries.length}개',
              style: const TextStyle(color: Color(0xFF6B7280)),
            ),
            const SizedBox(height: 18),
            Material(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
              child: InkWell(
                onTap: () => _openPhotoPlaces(context),
                borderRadius: BorderRadius.circular(16),
                child: const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 16, vertical: 13),
                  child: Row(
                    children: [
                      Icon(
                        Icons.photo_library_outlined,
                        color: AppColors.primary,
                        size: 30,
                      ),
                      SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          '저장 장소 보기',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ),
                      Icon(
                        Icons.chevron_right_rounded,
                        color: AppColors.primary,
                      ),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(height: 20),
            const Text(
              '전체',
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 10),
            if (_loading)
              const Padding(
                padding: EdgeInsets.all(32),
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_error != null)
              _errorState()
            else if (_discoveries.isEmpty)
              _emptyState()
            else
              ..._discoveries.map(_basicSavedCard),
          ],
        ),
      ),
    ),
    bottomNavigationBar: widget.showBottomNavigation
        ? AppBottomNavigation(selectedIndex: widget.selectedTab)
        : null,
  );

  /// 기본 모드 저장 목록의 한 항목입니다. 상세 이동과 삭제를 처리합니다.
  Widget _basicSavedCard(YouTubeSavedDiscovery item) => Padding(
    padding: const EdgeInsets.only(bottom: 10),
    child: Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        onTap: () => _openDetail(item),
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Row(
            children: [
              SizedBox(
                width: 76,
                height: 76,
                child: _thumbnail(
                  item,
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(child: _videoText(item)),
              _DeleteButton(onPressed: () => _confirmDelete(item)),
            ],
          ),
        ),
      ),
    ),
  );

  Widget _videoText(YouTubeSavedDiscovery item, {bool compact = false}) =>
      Column(
        mainAxisAlignment: compact
            ? MainAxisAlignment.start
            : MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            _destinationTitle(item),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: compact ? 15 : 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            item.title,
            maxLines: compact ? 2 : 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: compact ? 12 : 13,
              color: compact
                  ? const Color(0xFF9CA3AF)
                  : const Color(0xFF6B7280),
            ),
          ),
          if (item.channelTitle != null && item.channelTitle!.isNotEmpty) ...[
            SizedBox(height: compact ? 5 : 8),
            _Tag(item.channelTitle!),
          ],
        ],
      );

  Widget _thumbnail(
    YouTubeSavedDiscovery item, {
    required BorderRadius borderRadius,
  }) {
    final url = item.representativeImageUrl?.isNotEmpty == true
        ? item.representativeImageUrl
        : item.thumbnailUrl;
    return ClipRRect(
      borderRadius: borderRadius,
      child: url == null || url.isEmpty
          ? _thumbnailPlaceholder()
          : Image.network(
              url,
              fit: BoxFit.cover,
              errorBuilder: (_, _, _) => _thumbnailPlaceholder(),
            ),
    );
  }

  Widget _thumbnailPlaceholder() => Container(
    color: AppColors.soft,
    alignment: Alignment.center,
    child: const Icon(
      Icons.play_circle_fill,
      color: Color(0xFFEF4444),
      size: 42,
    ),
  );

  Widget _emptyState() => const Padding(
    padding: EdgeInsets.all(32),
    child: Center(child: Text('아직 저장한 YouTube 여행 영상이 없어요.')),
  );

  Widget _errorState() => Padding(
    padding: const EdgeInsets.all(32),
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('저장한 YouTube 영상을 불러오지 못했어요.'),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _loadSavedDiscoveries,
            child: const Text('다시 시도'),
          ),
        ],
      ),
    ),
  );

  String _destinationTitle(YouTubeSavedDiscovery item) {
    final destinationName = item.destinationName?.trim();
    return destinationName == null || destinationName.isEmpty
        ? item.title
        : destinationName;
  }
}

class _YoutubeIcon extends StatelessWidget {
  const _YoutubeIcon();
  @override
  Widget build(BuildContext context) => const SizedBox(
    width: 40,
    height: 40,
    child: Material(
      color: Color(0xEFFFFFFF),
      shape: CircleBorder(),
      child: Center(
        child: Icon(Icons.play_circle_fill, color: Color(0xFFEF4444), size: 24),
      ),
    ),
  );
}

class _ActionCard extends StatelessWidget {
  const _ActionCard({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.transparent,
    child: Ink(
      decoration: const BoxDecoration(color: Color(0xFFE3EFFF)),
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          width: double.infinity,
          height: 99,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Row(
              children: [
                Container(
                  width: 64,
                  height: 64,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(18),
                  ),
                  child: const Icon(
                    Icons.photo_library_outlined,
                    color: AppColors.primary,
                    size: 42,
                  ),
                ),
                const SizedBox(width: 16),
                const Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '저장 장소 보기',
                        style: TextStyle(
                          color: AppColors.ink,
                          fontSize: 20,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      SizedBox(height: 4),
                      Text(
                        '사진으로 찾은 장소를 모아보세요',
                        style: TextStyle(
                          color: Color(0xFF52658A),
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                const Icon(
                  Icons.arrow_forward_ios_rounded,
                  color: AppColors.primary,
                  size: 20,
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class _DeleteButton extends StatelessWidget {
  const _DeleteButton({required this.onPressed, this.compact = false});
  final VoidCallback onPressed;
  final bool compact;

  @override
  Widget build(BuildContext context) => TextButton(
    onPressed: onPressed,
    style: TextButton.styleFrom(
      foregroundColor: const Color(0xFFD9363E),
      minimumSize: compact ? const Size(36, 28) : const Size(44, 36),
      padding: EdgeInsets.zero,
      tapTargetSize: compact
          ? MaterialTapTargetSize.shrinkWrap
          : MaterialTapTargetSize.padded,
    ),
    child: Text(
      '삭제',
      style: TextStyle(
        fontSize: compact ? 12 : 14,
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}

class _Tag extends StatelessWidget {
  const _Tag(this.label);
  final String label;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
    decoration: BoxDecoration(
      color: AppColors.soft,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Text(
      label,
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: const TextStyle(
        fontSize: 10,
        color: Color(0xFF2F4FBF),
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}
