import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../../core/theme/app_theme.dart';
import '../../services/place_search_service.dart';
import '../../services/youtube_saved_discovery_service.dart';
import '../preference/youtube_recommended_place_detail_screen.dart'
    show regionFromAddress;
import '../preference/youtube_saved_detail_screen.dart';
import '../discovery/camera_screen.dart';
import '../preference/youtube_saved_screen.dart';
import '../trip/trip_places_screen.dart';

enum _SearchMode { region, link }

/// 직접 입력 검색. 지역·장소는 서버의 실제 장소 검색(GET /api/v1/places/search)
/// 결과만 보여 주고, 목업 장소나 확인하지 않은 시설 정보는 만들지 않는다.
class TextSearchScreen extends StatefulWidget {
  const TextSearchScreen({
    super.key,
    this.initialQuery = '',
    this.startWithLink = false,
    this.initialLink = '',
    this.resultsOnly = false,
  });

  final String initialQuery;
  final bool startWithLink;
  final String initialLink;
  final bool resultsOnly;

  @override
  State<TextSearchScreen> createState() => _TextSearchScreenState();
}

class _TextSearchScreenState extends State<TextSearchScreen> {
  final controller = TextEditingController();
  final linkController = TextEditingController();

  _SearchMode mode = _SearchMode.region;
  String query = '';
  bool linkSubmitted = false;
  String? linkError;
  bool linkLoading = false;

  final PlaceSearchService _placeSearch = PlaceSearchService();
  Future<List<PlaceSearchResult>>? _searchFuture;
  String _searchedQuery = '';

  /// 입력을 마쳤을 때만 서버에 검색합니다(글자마다 호출하지 않음).
  void _startSearch(String value) {
    final trimmed = value.trim();
    setState(() {
      query = value;
      _searchedQuery = trimmed;
      _searchFuture = trimmed.isEmpty ? null : _placeSearch.search(trimmed);
    });
  }

  @override
  void initState() {
    super.initState();
    query = widget.initialQuery;
    controller.text = query;
    if (query.trim().isNotEmpty) {
      _searchedQuery = query.trim();
      _searchFuture = _placeSearch.search(_searchedQuery);
    }
    mode = widget.startWithLink ? _SearchMode.link : _SearchMode.region;
    if (widget.initialLink.isNotEmpty) {
      linkController.text = widget.initialLink;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _searchLink();
      });
    }
  }

  @override
  void dispose() {
    controller.dispose();
    linkController.dispose();
    super.dispose();
  }

  /// YouTube 주소에서 영상 ID를 꺼냅니다. YouTube 링크가 아니면 null입니다.
  static String? _youtubeVideoId(Uri uri) {
    final host = uri.host.toLowerCase().replaceFirst(
      RegExp(r'^(www|m|music)\.'),
      '',
    );
    final segments = uri.pathSegments.where((part) => part.isNotEmpty).toList();
    String? id;
    if (host == 'youtu.be') {
      id = segments.isEmpty ? null : segments.first;
    } else if (host == 'youtube.com' || host == 'youtube-nocookie.com') {
      if (segments.isNotEmpty && segments.first == 'watch') {
        id = uri.queryParameters['v'];
      } else if (segments.length >= 2 &&
          const {'shorts', 'live', 'embed', 'v'}.contains(segments.first)) {
        id = segments[1];
      }
    }
    if (id == null || !RegExp(r'^[A-Za-z0-9_-]{11}$').hasMatch(id)) return null;
    return id;
  }

  /// 링크의 t= 값(90, 90s, 1m30s, 1h2m3s)을 초로 바꿉니다. 없으면 0초입니다.
  static int _startSeconds(Uri uri) {
    final raw = uri.queryParameters['t'] ?? uri.queryParameters['start'];
    if (raw == null || raw.isEmpty) return 0;
    final plain = int.tryParse(raw.replaceAll('s', ''));
    if (plain != null) return plain;
    final match = RegExp(
      r'^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$',
    ).firstMatch(raw);
    if (match == null) return 0;
    int part(int index) => int.tryParse(match.group(index) ?? '') ?? 0;
    return part(1) * 3600 + part(2) * 60 + part(3);
  }

  /// 키 없이 쓰는 YouTube oEmbed로 제목·채널·썸네일을 가져옵니다. 실패하면 빈 값입니다.
  static Future<Map<String, String?>> _videoMetadata(String videoId) async {
    try {
      final response = await http
          .get(
            Uri.https('www.youtube.com', '/oembed', {
              'url': 'https://www.youtube.com/watch?v=$videoId',
              'format': 'json',
            }),
          )
          .timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) return const {};
      final json = jsonDecode(utf8.decode(response.bodyBytes));
      if (json is! Map<String, dynamic>) return const {};
      return {
        'title': json['title']?.toString(),
        'channel_title': json['author_name']?.toString(),
        'thumbnail_url': json['thumbnail_url']?.toString(),
      };
    } catch (_) {
      return const {};
    }
  }

  Future<void> _searchLink() async {
    if (linkLoading) return;
    final uri = Uri.tryParse(linkController.text.trim());
    if (uri == null ||
        (uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.isEmpty) {
      setState(() {
        linkSubmitted = true;
        linkError = 'http:// 또는 https://로 시작하는 링크를 입력해주세요.';
      });
      return;
    }
    final videoId = _youtubeVideoId(uri);
    if (videoId == null) {
      setState(() {
        linkSubmitted = true;
        linkError = '지금은 YouTube 영상 링크만 찾을 수 있어요.';
      });
      return;
    }

    setState(() {
      linkSubmitted = true;
      linkError = null;
      linkLoading = true;
    });
    try {
      final metadata = await _videoMetadata(videoId);
      final saved = await YouTubeSavedDiscoveryService().save({
        'video_id': videoId,
        'position_sec': _startSeconds(uri),
        'page_url': uri.toString(),
        ...metadata,
      });
      if (!mounted) return;
      setState(() => linkLoading = false);
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => YouTubeSavedDetailScreen(discovery: saved),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() {
        linkLoading = false;
        linkError = error is StateError
            ? '로그인이 필요해요. 다시 로그인한 뒤 시도해주세요.'
            : '영상 정보를 가져오지 못했어요. 잠시 후 다시 시도해주세요.';
      });
    }
  }

  Widget _inputMethod({
    required IconData icon,
    required String title,
    required String description,
    bool selected = false,
    Color? iconColor,
    VoidCallback? onTap,
  }) => Material(
    color: selected ? AppColors.soft : Colors.white,
    borderRadius: BorderRadius.circular(16),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: selected ? AppColors.primary : const Color(0xFFE5E7EB),
            width: selected ? 2 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(icon, color: iconColor ?? AppColors.primary, size: 27),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: const TextStyle(fontWeight: FontWeight.w900),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    description,
                    style: const TextStyle(
                      fontSize: 13,
                      color: Color(0xFF6B7280),
                    ),
                  ),
                ],
              ),
            ),
            Icon(
              selected
                  ? Icons.check_circle_rounded
                  : Icons.chevron_right_rounded,
              color: AppColors.primary,
            ),
          ],
        ),
      ),
    ),
  );

  /// 검색어와 같은 도시·지역이 실제 결과 주소에 있을 때만 그 지역을 돌려줍니다.
  String? _matchedRegion(List<PlaceSearchResult> places) {
    final wanted = _searchedQuery
        .replaceAll(RegExp(r'\s+'), '')
        .replaceFirst(RegExp(r'(특별자치시|특별자치도|특별시|광역시|시|군|도)$'), '');
    if (wanted.length < 2) return null;
    for (final place in places) {
      final region = regionFromAddress(place.address);
      if (region != null && (region == wanted || wanted.startsWith(region))) {
        return region;
      }
    }
    return null;
  }

  void _openTrip({
    String? destination,
    Set<PlaceSearchResult> places = const {},
  }) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) =>
            TripPlacesScreen(
              destination: destination,
              initialPlaces: {for (final place in places) place.name},
              initialPlaceIds: {for (final place in places) place.placeId},
            ),
      ),
    );
  }

  Widget _searchResults() => FutureBuilder<List<PlaceSearchResult>>(
    future: _searchFuture,
    builder: (context, snapshot) {
      if (_searchFuture == null) {
        return const Text('가고 싶은 여행지 이름이나 지역을 입력해주세요.');
      }
      if (snapshot.connectionState != ConnectionState.done) {
        return const Padding(
          padding: EdgeInsets.symmetric(vertical: 32),
          child: Center(child: CircularProgressIndicator()),
        );
      }
      if (snapshot.hasError) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('장소를 검색하지 못했어요. 인터넷 연결이나 로그인을 확인한 뒤 다시 시도해 주세요.'),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: () => _startSearch(_searchedQuery),
              child: const Text('다시 검색'),
            ),
          ],
        );
      }
      final places = snapshot.data ?? const <PlaceSearchResult>[];
      final region = _matchedRegion(places);
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (region != null) ...[
            _RegionResult(
              region: region,
              onTap: () => _openTrip(destination: region),
            ),
            const SizedBox(height: 18),
          ],
          Text(
            '관련 장소 ${places.length}곳',
            style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 12),
          if (places.isEmpty)
            const Text('일치하는 장소가 없어요. 다른 지역이나 짧은 검색어로 찾아보세요.')
          else
            ...places.map(
              (place) =>
                  _PlaceResult(place: place, onTap: () => _showPlace(place)),
            ),
        ],
      );
    },
  );

  /// 검색 결과의 이름·주소만 보여 줍니다. 영업시간·시설 정보는 확인되지 않아 표시하지 않습니다.
  void _showPlace(PlaceSearchResult place) {
    final region = regionFromAddress(place.address);
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                place.name,
                style: const TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                place.address ?? place.region ?? '주소 정보 없음',
                style: const TextStyle(color: Color(0xFF6B7280)),
              ),
              const SizedBox(height: 10),
              const Text(
                '지도 검색으로 확인된 장소예요. 영업시간·시설 정보는 아직 확인되지 않았어요.',
                style: TextStyle(fontSize: 13, color: Color(0xFF6B7280)),
              ),
              const SizedBox(height: 18),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () {
                    Navigator.of(sheetContext).pop();
                    _openTrip(destination: region, places: {place});
                  },
                  style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(54),
                  ),
                  child: Text(
                    region == null ? '이 장소로 여행 만들기' : '$region 여행 만들기',
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final normalized = query.trim();

    if (widget.resultsOnly) {
      return Scaffold(
        appBar: AppBar(
          leading: IconButton(
            onPressed: () => Navigator.of(context).maybePop(),
            icon: const Icon(Icons.chevron_left_rounded),
            tooltip: '뒤로가기',
          ),
          title: const Text('검색 결과'),
          backgroundColor: Colors.white,
        ),
        body: ListView(
          padding: const EdgeInsets.all(20),
          children: [_searchResults()],
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          onPressed: () => Navigator.of(context).maybePop(),
          icon: const Icon(Icons.chevron_left_rounded),
          tooltip: '뒤로가기',
        ),
        title: const Text('여행지 검색'),
        backgroundColor: Colors.white,
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          SegmentedButton<_SearchMode>(
            segments: const [
              ButtonSegment(
                value: _SearchMode.region,
                label: Text('지역'),
                icon: Icon(Icons.place_outlined),
              ),
              ButtonSegment(
                value: _SearchMode.link,
                label: Text('링크'),
                icon: Icon(Icons.link_rounded),
              ),
            ],
            selected: {mode},
            onSelectionChanged: (selection) {
              setState(() => mode = selection.first);
            },
          ),
          const SizedBox(height: 20),
          if (mode == _SearchMode.region) ...[
            TextField(
              controller: controller,
              textInputAction: TextInputAction.search,
              onChanged: (value) => setState(() => query = value),
              onSubmitted: _startSearch,
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: '예: 강릉, 제주, 안목해변',
                suffixIcon: IconButton(
                  onPressed: () {
                    controller.clear();
                    _startSearch('');
                  },
                  icon: const Icon(Icons.close),
                ),
              ),
            ),
            const SizedBox(height: 20),
            if (normalized.isEmpty)
              const Text(
                '가고 싶은 여행지 이름이나 지역을 입력해주세요.',
                style: TextStyle(color: Color(0xFF6B7280)),
              )
            else if (_searchFuture == null || normalized != _searchedQuery)
              const Text(
                '검색 버튼(엔터)을 누르면 실제 장소를 찾아드려요.',
                style: TextStyle(color: Color(0xFF6B7280)),
              )
            else
              _searchResults(),
          ] else ...[
            TextField(
              controller: linkController,
              keyboardType: TextInputType.url,
              textInputAction: TextInputAction.search,
              onChanged: (_) => setState(() {
                linkSubmitted = false;
                linkError = null;
              }),
              onSubmitted: (_) => _searchLink(),
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.link_rounded),
                hintText: 'YouTube 영상 링크',
                suffixIcon: IconButton(
                  onPressed: () {
                    linkController.clear();
                    setState(() {
                      linkSubmitted = false;
                      linkError = null;
                    });
                  },
                  icon: const Icon(Icons.close),
                ),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: linkLoading ? null : _searchLink,
                icon: linkLoading
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.search),
                label: Text(linkLoading ? '영상 지역을 확인하는 중이에요' : '링크 검색'),
              ),
            ),
            const SizedBox(height: 20),
            if (!linkSubmitted || linkLoading)
              const Text(
                'YouTube 영상 링크를 붙여 넣으면 영상 정보로 여행 지역을 찾아드려요.',
                style: TextStyle(color: Color(0xFF6B7280)),
              )
            else if (linkError != null)
              Text(linkError!, style: const TextStyle(color: Colors.red)),
          ],
          const SizedBox(height: 28),
          const Text(
            '장소 입력 방식',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 6),
          const Text(
            '원하는 방법으로 여행지를 찾아보세요.',
            style: TextStyle(color: Color(0xFF6B7280)),
          ),
          const SizedBox(height: 14),
          _inputMethod(
            icon: Icons.play_circle_fill,
            title: 'YouTube로 장소 찾기',
            description: '저장해 둔 장소에서 선택',
            iconColor: const Color(0xFFEF4444),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const YoutubeSavedScreen()),
            ),
          ),
          const SizedBox(height: 10),
          _inputMethod(
            icon: Icons.image_search_outlined,
            title: '이미지에서 장소 찾기',
            description: '사진에서 장소를 추출',
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => const CameraScreen(galleryOnly: true),
              ),
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

class _RegionResult extends StatelessWidget {
  const _RegionResult({required this.region, required this.onTap});

  final String region;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: const Color(0xFFEFF0FF),
    borderRadius: BorderRadius.circular(20),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(
          children: [
            const Icon(
              Icons.location_city_rounded,
              color: AppColors.primary,
              size: 32,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    region,
                    style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 2),
                  const Text(
                    '이 지역으로 여행 만들기',
                    style: TextStyle(
                      color: AppColors.primary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right_rounded, color: AppColors.primary),
          ],
        ),
      ),
    ),
  );
}

class _PlaceResult extends StatelessWidget {
  const _PlaceResult({required this.place, required this.onTap});

  final PlaceSearchResult place;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(20),
        side: const BorderSide(color: Color(0xFFE5E7EB)),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '📍  ${place.name}',
                style: const TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                place.address ?? place.region ?? '주소 정보 없음',
                style: const TextStyle(color: Color(0xFF6B7280)),
              ),
              const SizedBox(height: 10),
              const Text(
                '장소 확인하기 →',
                style: TextStyle(
                  color: AppColors.primary,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
