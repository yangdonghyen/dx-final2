import 'dart:io';

import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';
import '../../services/favorite_places_service.dart';
import '../../services/scene_image_service.dart';
import '../../widgets/app_bottom_navigation.dart';
import '../../widgets/app_header.dart';
import '../trip/trip_places_screen.dart';
import 'camera_screen.dart';

/// 사진 분석으로 찾은 여행지의 결과와 여행 만들기 진입 화면입니다.
///
/// 장소 이름과 주소는 서버 분석 결과만 보여 줍니다. 찾지 못하면 다시 찍도록
/// 안내하고, 임의의 장소를 보여 주지 않습니다.
class PlaceResultScreen extends StatefulWidget {
  const PlaceResultScreen({
    super.key,
    required this.imagePath,
    required this.result,
  });
  final String imagePath;
  final SceneRecognitionResult result;

  @override
  State<PlaceResultScreen> createState() => _PlaceResultScreenState();
}

class _PlaceResultScreenState extends State<PlaceResultScreen> {
  static const _placeEmoji = '📍';

  SceneRecognitionResult get _result => widget.result;

  String? get _placeName => _result.recognized ? _result.placeName : null;

  String get _locationLabel =>
      _result.address ?? _result.areaLabel ?? '위치 정보 없음';

  void _savePlace(String placeName) {
    final saved = FavoritePlacesService.togglePhotoSaved(
      placeName,
      location: _locationLabel,
      emoji: _placeEmoji,
      tags: const [],
    );
    setState(() {});
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(saved ? '저장 목록에 장소를 추가했어요.' : '저장을 취소했어요.')),
    );
  }

  void _retake() {
    Navigator.of(
      context,
    ).pushReplacement(MaterialPageRoute(builder: (_) => const CameraScreen()));
  }

  @override
  Widget build(BuildContext context) {
    final placeName = _placeName;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            const AppHeader('장소 찾기 결과'),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(20),
                    child: Image.file(
                      File(widget.imagePath),
                      height: 210,
                      width: double.infinity,
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => const SizedBox(
                        height: 210,
                        child: ColoredBox(color: Color(0xFFF3F4F6)),
                      ),
                    ),
                  ),
                  const SizedBox(height: 18),
                  if (placeName == null)
                    ..._notFound()
                  else
                    ..._found(placeName),
                ],
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 12),
            decoration: const BoxDecoration(
              color: Colors.white,
              border: Border(top: BorderSide(color: Color(0xFFE5E7EB))),
            ),
            child: placeName == null
                ? FilledButton.icon(
                    onPressed: _retake,
                    icon: const Icon(Icons.photo_camera_outlined),
                    label: const Text('다시 찍기'),
                    style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(52),
                    ),
                  )
                : Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: () => _savePlace(placeName),
                          icon: Icon(
                            FavoritePlacesService.isPhotoSaved(placeName)
                                ? Icons.bookmark
                                : Icons.bookmark_border,
                          ),
                          label: Text(
                            FavoritePlacesService.isPhotoSaved(placeName)
                                ? '저장됨'
                                : '장소 저장',
                          ),
                          style: OutlinedButton.styleFrom(
                            minimumSize: const Size.fromHeight(52),
                            foregroundColor: AppColors.primary,
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: FilledButton.icon(
                          onPressed: () =>
                              Navigator.of(context).pushReplacement(
                                MaterialPageRoute(
                                  builder: (_) => TripPlacesScreen(
                                    initialPlaces: {placeName},
                                    photoPlan: true,
                                  ),
                                ),
                              ),
                          icon: const Icon(Icons.add_location_alt_outlined),
                          label: const Text('여행 코스 짜기'),
                          style: FilledButton.styleFrom(
                            minimumSize: const Size.fromHeight(52),
                          ),
                        ),
                      ),
                    ],
                  ),
          ),
          const AppBottomNavigation(selectedIndex: 0),
        ],
      ),
    );
  }

  List<Widget> _found(String placeName) => [
    Text(
      placeName,
      style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900),
    ),
    const SizedBox(height: 4),
    Text('$_locationLabel · AI 분석 결과'),
    const SizedBox(height: 12),
    if (!_result.verified)
      Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFFFFF7E6),
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Text(
          'AI가 추측한 장소예요. 지도에서 확인되지 않았으니 정확한지 한 번 확인해주세요.',
          style: TextStyle(fontSize: 14, color: Color(0xFF92400E)),
        ),
      ),
    if (_result.otherCandidates.isNotEmpty) ...[
      const SizedBox(height: 14),
      const Text(
        '다른 후보',
        style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
      ),
      const SizedBox(height: 4),
      Text(
        _result.otherCandidates.join(' · '),
        style: const TextStyle(color: Color(0xFF6B7280)),
      ),
    ],
    const SizedBox(height: 12),
    const Text(
      '여행 코스를 만들려면 날짜부터 선택해 주세요.',
      style: TextStyle(color: Color(0xFF6B7280)),
    ),
  ];

  /// 서버 분석은 성공했지만 어느 장소인지 알아내지 못한 경우입니다.
  List<Widget> _notFound() => [
    Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xFFECFDF5),
        borderRadius: BorderRadius.circular(12),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.check_circle, color: Color(0xFF059669), size: 20),
          SizedBox(width: 6),
          Text(
            '사진 분석 완료',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w800,
              color: Color(0xFF065F46),
            ),
          ),
        ],
      ),
    ),
    const SizedBox(height: 12),
    const Text(
      '어디인지는 알 수 없었어요',
      style: TextStyle(fontSize: 24, fontWeight: FontWeight.w900),
    ),
    const SizedBox(height: 8),
    const Text(
      '사진은 잘 받아서 분석했지만, 어느 여행지인지 알아볼 만한 단서를 찾지 못했어요. '
      '건물, 간판, 풍경이 잘 보이게 다시 찍어주세요.',
      style: TextStyle(fontSize: 16, color: Color(0xFF6B7280)),
    ),
  ];
}
