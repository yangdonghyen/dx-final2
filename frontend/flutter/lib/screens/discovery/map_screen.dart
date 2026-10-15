import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:webview_flutter/webview_flutter.dart';

/// 관심 장소를 지도형 목록으로 보여주고 카테고리 필터를 적용하는 화면입니다.
class MapScreen extends StatefulWidget {
  const MapScreen({super.key, this.onBack});
  final VoidCallback? onBack;
  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  static const String kakaoJavascriptKey = String.fromEnvironment(
    'KAKAO_JAVASCRIPT_KEY',
  );

  static const double fallbackLatitude = 37.5665;
  static const double fallbackLongitude = 126.9780;

  late final WebViewController webViewController;

  bool mapLoaded = false;
  bool locating = false;
  bool satellite = false;

  double latitude = fallbackLatitude;
  double longitude = fallbackLongitude;

  String selectedCategory = '';
  Map<String, dynamic>? selectedPlace;
  String status = '카카오맵을 준비하고 있어요.';
  String _searchLabel = '장소';

  @override
  void initState() {
    super.initState();

    webViewController = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.white)
      ..addJavaScriptChannel(
        'PlaceChannel',
        onMessageReceived: (message) {
          try {
            final decoded = jsonDecode(message.message);
            if (decoded is Map && decoded['type'] == 'count' && mounted) {
              // How many places the category search put on the map.
              final count = decoded['count'] is num ? (decoded['count'] as num).toInt() : 0;
              setState(() {
                status = count > 0
                    ? '현재 위치 주변 $_searchLabel $count곳을 찾았어요.'
                    : '현재 위치 주변에서 ${withObjectParticle(_searchLabel)} 찾지 못했어요.';
              });
            } else if (decoded is Map && mounted) {
              setState(() {
                selectedPlace = Map<String, dynamic>.from(decoded);
              });
            }
          } catch (e) {
            debugPrint('장소 정보 파싱 실패: $e');
          }
        },
      )
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageFinished: (_) {
            if (!mounted) return;

            setState(() {
              mapLoaded = true;
            });

            _locate();
          },
        ),
      );

    if (kakaoJavascriptKey.isNotEmpty) {
      webViewController.loadHtmlString(
        _buildMapHtml(),
        baseUrl: 'https://localhost',
      );
    } else {
      status = 'Kakao JavaScript Key가 전달되지 않았어요.';
    }
  }

  Future<void> _locate() async {
    if (locating) return;

    setState(() {
      locating = true;
      status = '현재 위치를 확인하고 있어요.';
    });

    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();

      if (!serviceEnabled) {
        await _useFallback('위치 서비스가 꺼져 있어 기본 위치를 표시하고 있어요.');
        return;
      }

      var permission = await Geolocator.checkPermission();

      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }

      if (permission == LocationPermission.denied) {
        await _useFallback('위치 권한이 없어 기본 위치를 표시하고 있어요.');
        return;
      }

      if (permission == LocationPermission.deniedForever) {
        await _useFallback('위치 권한이 차단되어 있어요. 설정에서 허용해주세요.');
        return;
      }

      final gps = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
        ),
      );

      if (!mounted) return;

      latitude = gps.latitude;
      longitude = gps.longitude;

      setState(() {
        locating = false;
        status = '현재 위치를 찾았어요. 카페·음식점·관광지를 눌러 주변을 둘러보세요.';
      });

      await _moveMap(latitude, longitude);

      await Future.delayed(const Duration(milliseconds: 300));

      // 처음 진입 시에는 카테고리를 자동 선택하지 않음
    } catch (e) {
      debugPrint('현재 위치 조회 실패: $e');

      await _useFallback('GPS 위치를 가져오지 못해 기본 위치를 표시하고 있어요.');
    }
  }

  Future<void> _useFallback(String message) async {
    latitude = fallbackLatitude;
    longitude = fallbackLongitude;

    if (mounted) {
      setState(() {
        locating = false;
        status = message;
      });
    }

    await _moveMap(fallbackLatitude, fallbackLongitude);
  }

  Future<void> _moveMap(double lat, double lng) async {
    if (!mapLoaded) return;

    await webViewController.runJavaScript('setCurrentLocation($lat, $lng);');
  }

  Future<void> _changeMapType(bool useSatellite) async {
    setState(() {
      satellite = useSatellite;
    });

    if (!mapLoaded) return;

    final type = useSatellite ? 'hybrid' : 'roadmap';

    await webViewController.runJavaScript("setMapType('$type');");
  }

  Future<void> _searchCategory(String category) async {
    String label;

    switch (category) {
      case 'FD6':
        label = '음식점';
        break;
      case 'AT4':
        label = '관광지';
        break;
      case 'CE7':
      default:
        label = '카페';
        category = 'CE7';
    }

    _searchLabel = label;
    if (mounted) {
      setState(() {
        selectedCategory = category;
        selectedPlace = null;
        status = '현재 위치 주변 ${withObjectParticle(label)} 찾고 있어요.';
      });
    }

    if (!mapLoaded) return;

    await webViewController.runJavaScript("searchCategory('$category');");
  }

  String _buildMapHtml() {
    return '''
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">

<meta
  name="viewport"
  content="width=device-width, initial-scale=1.0,
  maximum-scale=1.0, user-scalable=no"
>

<style>
html, body, #map {
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 0;
}

.current-label {
  background: white;
  color: #111827;
  border-radius: 8px;
  padding: 5px 8px;
  font-size: 12px;
  font-weight: bold;
  box-shadow: 0 2px 8px rgba(0,0,0,0.20);
  white-space: nowrap;
}

.place-label {
  background: white;
  border-radius: 8px;
  padding: 6px 8px;
  font-size: 11px;
  font-weight: bold;
  white-space: nowrap;
  box-shadow: 0 2px 7px rgba(0,0,0,0.18);
}
</style>

<script
  type="text/javascript"
  src="https://dapi.kakao.com/v2/maps/sdk.js?appkey=$kakaoJavascriptKey&libraries=services&autoload=false">
</script>
</head>

<body>

<div id="map"></div>

<script>

let map = null;

let currentMarker = null;
let currentOverlay = null;

let placeMarkers = [];
let placeOverlays = [];

let currentLat = $fallbackLatitude;
let currentLng = $fallbackLongitude;

function initMap() {
  const initialPosition =
    new kakao.maps.LatLng(
      currentLat,
      currentLng
    );

  const container =
    document.getElementById('map');

  const options = {
    center: initialPosition,
    level: 4
  };

  map =
    new kakao.maps.Map(
      container,
      options
    );

  currentMarker =
    new kakao.maps.Marker({
      position: initialPosition
    });

  currentMarker.setMap(map);

  currentOverlay =
    new kakao.maps.CustomOverlay({
      position: initialPosition,
      content:
        '<div class="current-label">현재 위치</div>',
      yAnchor: 2.4
    });

  currentOverlay.setMap(map);
}

function setCurrentLocation(lat, lng) {
  if (!map) return;

  currentLat = lat;
  currentLng = lng;

  const position =
    new kakao.maps.LatLng(
      lat,
      lng
    );

  map.setCenter(position);
  map.setLevel(4);

  currentMarker.setPosition(position);
  currentOverlay.setPosition(position);
}

function clearPlaces() {
  placeMarkers.forEach(function(marker) {
    marker.setMap(null);
  });

  placeOverlays.forEach(function(overlay) {
    overlay.setMap(null);
  });

  placeMarkers = [];
  placeOverlays = [];
}

function searchCategory(categoryCode) {
  if (!map) return;

  clearPlaces();

  const places =
    new kakao.maps.services.Places();

  const center =
    new kakao.maps.LatLng(
      currentLat,
      currentLng
    );

  places.categorySearch(
    categoryCode,

    function(data, status) {
      if (
        status !==
        kakao.maps.services.Status.OK
      ) {
        PlaceChannel.postMessage(JSON.stringify({ type: 'count', count: 0 }));
        return;
      }
      PlaceChannel.postMessage(JSON.stringify({ type: 'count', count: Math.min(data.length, 10) }));

      const bounds =
        new kakao.maps.LatLngBounds();

      bounds.extend(center);

      const maxCount =
        Math.min(data.length, 10);

      for (
        let i = 0;
        i < maxCount;
        i++
      ) {
        const place = data[i];

        const position =
          new kakao.maps.LatLng(
            place.y,
            place.x
          );

        const marker =
          new kakao.maps.Marker({
            map: map,
            position: position
          });

        placeMarkers.push(marker);

        const overlay =
          new kakao.maps.CustomOverlay({
            position: position,
            content:
              '<div class="place-label">' +
              escapeHtml(place.place_name) +
              '</div>',
            yAnchor: 2.5
          });

        kakao.maps.event.addListener(
          marker,
          'click',
          function() {
            placeOverlays.forEach(
              function(item) {
                item.setMap(null);
              }
            );

            overlay.setMap(map);

            map.panTo(position);

            PlaceChannel.postMessage(
              JSON.stringify({
                name: place.place_name || '',
                address:
                  place.road_address_name ||
                  place.address_name ||
                  '',
                distance: place.distance || '',
                phone: place.phone || '',
                category: place.category_name || ''
              })
            );
          }
        );

        placeOverlays.push(overlay);

        bounds.extend(position);
      }

      if (maxCount > 0) {
        map.setBounds(bounds);
      }
    },

    {
      location: center,
      radius: 2000,
      sort:
        kakao.maps.services.SortBy.DISTANCE
    }
  );
}

function setMapType(type) {
  if (!map) return;

  if (type === 'hybrid') {
    map.setMapTypeId(
      kakao.maps.MapTypeId.HYBRID
    );
  } else {
    map.setMapTypeId(
      kakao.maps.MapTypeId.ROADMAP
    );
  }
}

function escapeHtml(text) {
  return String(text)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

kakao.maps.load(function() {
  initMap();
});

</script>

</body>
</html>
''';
  }

  Widget _categoryChip({required String code, required String label}) {
    final selected = selectedCategory == code;

    return Expanded(
      child: ChoiceChip(
        label: SizedBox(
          width: double.infinity,
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
            ),
          ),
        ),
        selected: selected,
        showCheckmark: true,
        selectedColor: const Color(0xFFE6E8FF),
        backgroundColor: Colors.white,
        side: BorderSide(
          color: selected ? const Color(0xFF6D72E8) : const Color(0xFFD1D5DB),
        ),
        onSelected: (_) {
          _searchCategory(code);
        },
      ),
    );
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
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 12, 20, 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
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
                      const Expanded(
                        child: Text(
                          '지도 탐색',
                          style: TextStyle(
                            fontSize: 22,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                      ),
                      TextButton.icon(
                        onPressed: locating ? null : _locate,
                        icon: const Icon(Icons.my_location),
                        label: const Text('현재 위치'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  status,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xFF6B7280),
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 6),
              child: Row(
                children: [
                  ChoiceChip(
                    label: const Text('일반 지도'),
                    selected: !satellite,
                    onSelected: (_) {
                      _changeMapType(false);
                    },
                  ),
                  const SizedBox(width: 8),
                  ChoiceChip(
                    label: const Text('위성 지도'),
                    selected: satellite,
                    onSelected: (_) {
                      _changeMapType(true);
                    },
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Row(
                children: [
                  _categoryChip(code: 'CE7', label: '카페'),
                  const SizedBox(width: 6),
                  _categoryChip(code: 'FD6', label: '음식점'),
                  const SizedBox(width: 6),
                  _categoryChip(code: 'AT4', label: '관광지'),
                ],
              ),
            ),
            Expanded(
              child: Stack(
                children: [
                  Positioned.fill(
                    child: kakaoJavascriptKey.isEmpty
                        ? const Center(
                            child: Text('Kakao JavaScript Key가 없습니다.'),
                          )
                        : WebViewWidget(controller: webViewController),
                  ),
                  if (selectedPlace != null)
                    Positioned(
                      left: 12,
                      right: 12,
                      bottom: 12,
                      child: _PlaceCard(
                        place: selectedPlace!,
                        onClose: () {
                          setState(() {
                            selectedPlace = null;
                          });
                        },
                        onSave: () {
                          final placeName =
                              selectedPlace?['name']?.toString() ?? '장소';
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              content: Text('$placeName 저장 기능은 다음 단계에서 연결할게요.'),
                            ),
                          );
                        },
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PlaceCard extends StatelessWidget {
  const _PlaceCard({
    required this.place,
    required this.onClose,
    required this.onSave,
  });

  final Map<String, dynamic> place;
  final VoidCallback onClose;
  final VoidCallback onSave;

  String _distanceText() {
    final raw = place['distance']?.toString() ?? '';
    final meters = double.tryParse(raw);

    if (meters == null) return '';

    if (meters >= 1000) {
      return '${(meters / 1000).toStringAsFixed(1)}km';
    }

    return '${meters.round()}m';
  }

  @override
  Widget build(BuildContext context) {
    final name = place['name']?.toString() ?? '';
    final address = place['address']?.toString() ?? '';
    final phone = place['phone']?.toString() ?? '';
    final category = place['category']?.toString() ?? '';
    final distance = _distanceText();

    return Card(
      elevation: 8,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Padding(
              padding: EdgeInsets.only(top: 4),
              child: Icon(Icons.place, size: 28, color: Color(0xFF4F46E5)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    name,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  if (category.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(
                      category,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 11,
                        color: Color(0xFF9CA3AF),
                      ),
                    ),
                  ],
                  if (address.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      address,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF6B7280),
                      ),
                    ),
                  ],
                  if (distance.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      '현재 위치에서 $distance',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF4F46E5),
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                  if (phone.isNotEmpty) ...[
                    const SizedBox(height: 3),
                    Text(
                      phone,
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF6B7280),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            IconButton(
              onPressed: onClose,
              icon: const Icon(Icons.close),
              tooltip: '닫기',
            ),
          ],
        ),
      ),
    );
  }
}

/// "음식점을", "카페를": 을 after a final consonant, 를 otherwise.
String withObjectParticle(String word) {
  if (word.isEmpty) return word;
  final code = word.codeUnitAt(word.length - 1);
  if (code < 0xAC00 || code > 0xD7A3) return '$word을(를)';
  return (code - 0xAC00) % 28 == 0 ? '$word를' : '$word을';
}
