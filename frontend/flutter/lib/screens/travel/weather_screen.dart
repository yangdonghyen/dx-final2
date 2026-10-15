import 'dart:async';

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';

import '../../core/layout/app_responsive.dart';
import '../../core/theme/app_theme.dart';
import '../../services/active_trip_service.dart';
import '../../services/weather_background_service.dart';
import '../../services/weather_notification_service.dart';
import '../../services/weather_service.dart';
import '../../widgets/app_bottom_navigation.dart';
import '../trip/itinerary_screen.dart';
import 'today_travel_screen.dart';

/// What the AI is asked for when plan 2/3 is applied to the saved itinerary.
const weatherPlanInstructions = <int, String>{
  2: 'Rain is forecast. Replace outdoor stops (beaches, parks, trails) with places marked indoor, such as museums, galleries and exhibitions. Keep meals and keep outdoor walking short.',
  3: 'A heat wave is forecast. Replace outdoor stops in the late morning and afternoon with places marked indoor, such as museums, galleries and exhibitions. Keep meals; outdoor visits only early in the morning.',
};

/// 현재 위치 날씨·일별 예보와 날씨에 맞춘 여행 계획을 보여주는 화면입니다.
class WeatherScreen extends StatefulWidget {
  const WeatherScreen({super.key, this.initialPlan = 1});
  final int initialPlan;

  @override
  State<WeatherScreen> createState() => _WeatherScreenState();
}

enum _LocationFailure {
  serviceDisabled,
  permissionDenied,
  permissionDeniedForever,
  unavailable,
}

class _LocationException implements Exception {
  const _LocationException(this.failure);
  final _LocationFailure failure;
}

class _WeatherScreenState extends State<WeatherScreen> {
  final WeatherService _weatherService = WeatherService();
  late int _plan;
  late Future<WeatherData> _weatherFuture;

  @override
  void initState() {
    super.initState();
    _plan = widget.initialPlan.clamp(1, 3).toInt();
    _weatherFuture = _weatherAtCurrentPosition();
  }

  void _retry() => setState(() {
    _weatherFuture = _weatherAtCurrentPosition();
  });

  Future<WeatherData> _weatherAtCurrentPosition() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw const _LocationException(_LocationFailure.serviceDisabled);
    }
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied) {
      throw const _LocationException(_LocationFailure.permissionDenied);
    }
    if (permission == LocationPermission.deniedForever) {
      throw const _LocationException(_LocationFailure.permissionDeniedForever);
    }
    final Position position;
    try {
      position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
        ),
      );
    } catch (_) {
      throw const _LocationException(_LocationFailure.unavailable);
    }

    await WeatherBackgroundService.saveCurrentLocationAndSchedule(
      latitude: position.latitude,
      longitude: position.longitude,
    );

    final weather = await _weatherService.getWeatherAt(
      latitude: position.latitude,
      longitude: position.longitude,
    );
    unawaited(
      WeatherNotificationService.instance.notifyForWeather(
        weather,
        requestPermission: true,
      ),
    );
    return weather;
  }

  List<(String, String, String)> get _plans {
    final places = ActiveTripService.places;
    final primary = places.isNotEmpty ? places.first : '선택한 여행지';
    final secondary = places.length > 1 ? places[1] : '$primary 주변';
    return [
      ('🌤️', '계획 1 · 기본 일정', '숙소 체크인 → $primary → 점심 식사 → $secondary → 숙소 복귀'),
      (
        '🌧️',
        '계획 2 · 비 오는 날 일정',
        '숙소 체크인 → $primary 실내·휴식 우선 → 점심 → $secondary 주변 카페 → 숙소 복귀',
      ),
      (
        '☀️',
        '계획 3 · 더운 날 일정',
        '숙소 체크인 → $primary 이른 방문 → 점심 → $secondary 주변 그늘·실내 휴식 → 숙소 복귀',
      ),
    ];
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      leading: IconButton(
        onPressed: () => Navigator.of(context).maybePop(),
        icon: const Icon(Icons.chevron_left_rounded),
        tooltip: '뒤로가기',
      ),
      title: const Text('오늘 날씨'),
      backgroundColor: Colors.white,
    ),
    body: FutureBuilder<WeatherData>(
      future: _weatherFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) return _error(snapshot.error);
        return _weatherBody(snapshot.requireData);
      },
    ),
    bottomNavigationBar: const AppBottomNavigation(selectedIndex: 0),
  );

  Widget _error(Object? error) {
    final (title, detail) = switch (error) {
      _LocationException(failure: _LocationFailure.serviceDisabled) => (
        '위치 서비스가 꺼져 있어요.',
        '휴대폰 설정에서 위치 서비스를 켠 뒤 다시 시도해주세요.',
      ),
      _LocationException(failure: _LocationFailure.permissionDenied) => (
        '위치 권한이 필요해요.',
        '현재 위치 날씨를 보려면 위치 권한을 허용해주세요.',
      ),
      _LocationException(failure: _LocationFailure.permissionDeniedForever) => (
        '위치 권한이 차단되어 있어요.',
        '휴대폰 설정에서 앱의 위치 권한을 허용한 뒤 다시 시도해주세요.',
      ),
      _LocationException() => ('현재 위치를 가져오지 못했어요.', '잠시 후 다시 시도해주세요.'),
      _ => ('날씨 정보를 불러오지 못했어요.', '네트워크 또는 날씨 서비스 상태를 확인한 뒤 다시 시도해주세요.'),
    };
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.location_off_outlined,
              size: 48,
              color: Color(0xFF6B7280),
            ),
            const SizedBox(height: 16),
            Text(
              title,
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            Text(
              detail,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Color(0xFF6B7280)),
            ),
            const SizedBox(height: 18),
            OutlinedButton(onPressed: _retry, child: const Text('다시 시도')),
          ],
        ),
      ),
    );
  }

  Widget _weatherBody(WeatherData weather) {
    final selected = _plans[_plan - 1];
    final rainy = isRainyWeather(weather);
    final hot = !rainy && isHeatWave(weather);
    return ListView(
      padding: EdgeInsets.fromLTRB(ResponsiveLayout.pageHorizontal(context), ResponsiveLayout.sectionSpacing(context), ResponsiveLayout.pageHorizontal(context), 16),
      children: [
        Container(
          padding: EdgeInsets.all(ResponsiveLayout.isCompact(context) ? 16 : 22),
          decoration: BoxDecoration(
            color: const Color(0xFF173B76),
            borderRadius: BorderRadius.circular(24),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${weather.locationName} · 현재 날씨',
                style: const TextStyle(
                  fontSize: 17,
                  color: Color(0xFFBFDBFE),
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 6),
              Row(
                children: [
                  Text(
                    _emoji(weather.current.condition),
                    style: const TextStyle(fontSize: 70),
                  ),
                  const SizedBox(width: 7),
                  Text(
                    _temperature(weather.current.temperature),
                    style: const TextStyle(
                      fontSize: 46,
                      color: Colors.white,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(width: 7),
                  Text(
                    weather.current.condition ?? '정보 없음',
                    style: const TextStyle(
                      fontSize: 20,
                      color: Color(0xFFDBEAFE),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: _Metric(
                      Icons.water_drop_outlined,
                      '강수확률',
                      _percent(weather.current.precipitationProbability),
                    ),
                  ),
                  const SizedBox(width: 7),
                  Expanded(
                    child: _Metric(
                      Icons.opacity_outlined,
                      '습도',
                      _percent(weather.current.humidity),
                    ),
                  ),
                  const SizedBox(width: 7),
                  Expanded(
                    child: _Metric(
                      Icons.air_rounded,
                      '바람',
                      _wind(weather.current.windSpeed),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 22),
        const Text(
          '이번 주',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 12),
        if (weather.daily.isEmpty)
          const Text(
            '표시할 일별 예보가 없어요.',
            style: TextStyle(color: Color(0xFF6B7280)),
          )
        else
          SizedBox(
            height: 108,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: weather.daily.length,
              separatorBuilder: (_, _) => const SizedBox(width: 8),
              itemBuilder: (_, index) =>
                  _ForecastDay(weather: weather.daily[index]),
            ),
          ),
        const SizedBox(height: 22),
        const Text(
          '날씨별 오늘 일정',
          style: TextStyle(fontSize: 23, fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 6),
        Text(
          rainy
              ? '현재 ${weather.current.condition} 예보에는 계획 2를 추천해요.'
              : hot
              ? '현재 폭염 예보에는 계획 3을 추천해요.'
              : '현재 예보에 맞는 여행 계획을 선택해보세요.',
          style: const TextStyle(
            fontSize: 17,
            color: Color(0xFF6B7280),
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 8),
        SizedBox(
          height: 54,
          child: Row(
            children: List.generate(
              3,
              (index) => Expanded(
                child: Padding(
                  padding: EdgeInsets.only(right: index == 2 ? 0 : 9),
                  child: _PlanChoice(
                    label: '계획 ${index + 1}',
                    selected: _plan == index + 1,
                    onTap: () => setState(() => _plan = index + 1),
                  ),
                ),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: AppColors.soft,
            borderRadius: BorderRadius.circular(22),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${selected.$1}  ${selected.$2}',
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                selected.$3,
                style: const TextStyle(fontSize: 15, height: 1.42),
              ),
              const SizedBox(height: 12),
              if (weatherPlanInstructions[_plan] != null &&
                  (ActiveTripService.planId != null || ActiveTripService.tripId != null)) ...[
                OutlinedButton.icon(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => ItineraryScreen(
                        weatherInstruction: weatherPlanInstructions[_plan],
                      ),
                    ),
                  ),
                  icon: const Icon(Icons.auto_fix_high_rounded),
                  label: Text(_plan == 3 ? '계획 3으로 내 일정 수정안 만들기' : '계획 2로 내 일정 수정안 만들기'),
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size.fromHeight(54),
                  ),
                ),
                const SizedBox(height: 8),
              ],
              FilledButton(
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute(
                    // 날씨 계획은 안내 문구일 뿐이라, 저장된 실제 일정을 엽니다.
                    builder: (_) => const TodayTravelScreen(),
                  ),
                ),
                style: FilledButton.styleFrom(
                  minimumSize: const Size.fromHeight(54),
                  backgroundColor: AppColors.primary,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16),
                  ),
                ),
                child: const Text(
                  '오늘 일정 보기',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  String _temperature(double? value) {
    if (value == null) return '-';
    return '${value.toStringAsFixed(value == value.roundToDouble() ? 0 : 1)}°';
  }

  String _percent(int? value) => value == null ? '-' : '$value%';
  String _wind(double? value) =>
      value == null ? '-' : '${value.toStringAsFixed(1)}m/s';
  String _emoji(String? condition) => switch (condition) {
    '비' || '소나기' => '🌧️',
    '비/눈' => '🌨️',
    '눈' => '❄️',
    '맑음' => '☀️',
    '구름많음' || '흐림' => '☁️',
    _ => '🌤️',
  };
}

class _PlanChoice extends StatelessWidget {
  const _PlanChoice({
    required this.label,
    required this.selected,
    required this.onTap,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Material(
    color: selected ? AppColors.primary : Colors.white,
    borderRadius: BorderRadius.circular(16),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        alignment: Alignment.center,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: selected ? AppColors.primary : const Color(0xFFB8C7E8),
            width: 2,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 16,
            color: selected ? Colors.white : AppColors.primary,
            fontWeight: FontWeight.w900,
          ),
        ),
      ),
    ),
  );
}

class _Metric extends StatelessWidget {
  const _Metric(this.icon, this.label, this.value);
  final IconData icon;
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Container(
    constraints: const BoxConstraints(minHeight: 82),
    padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 5),
    decoration: BoxDecoration(
      color: const Color(0xFF2B5AA0),
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFF80B2FF), width: 1.2),
    ),
    child: Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(icon, size: 19, color: const Color(0xFFBFDBFE)),
        const SizedBox(height: 2),
        Text(
          label,
          style: const TextStyle(
            fontSize: 14,
            color: Color(0xFFDBEAFE),
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 2),
        SizedBox(
          width: double.infinity,
          child: FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(
              value,
              maxLines: 1,
              style: const TextStyle(
                fontSize: 20,
                color: Colors.white,
                fontWeight: FontWeight.w900,
              ),
            ),
          ),
        ),
      ],
    ),
  );
}

class _ForecastDay extends StatelessWidget {
  const _ForecastDay({required this.weather});
  final DailyWeather weather;
  String _value(double? value) {
    if (value == null) return '-';
    return '${value.toStringAsFixed(value == value.roundToDouble() ? 0 : 1)}°';
  }

  IconData _icon() => switch (weather.condition) {
    '비' || '소나기' => Icons.thunderstorm_rounded,
    '비/눈' || '눈' => Icons.cloudy_snowing,
    '맑음' => Icons.wb_sunny_rounded,
    '구름많음' || '흐림' => Icons.cloud_rounded,
    _ => Icons.cloud_outlined,
  };
  static const _weekdays = ['월', '화', '수', '목', '금', '토', '일'];

  bool get _isToday {
    final now = DateTime.now();
    return weather.date.year == now.year &&
        weather.date.month == now.month &&
        weather.date.day == now.day;
  }

  String get _dayLabel => _isToday ? '오늘' : _weekdays[weather.date.weekday - 1];

  @override
  Widget build(BuildContext context) => Container(
    width: 64,
    padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 6),
    decoration: BoxDecoration(
      color: _isToday ? AppColors.soft : Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(
        color: _isToday ? const Color(0xFFB9C9F8) : const Color(0xFFE5E7EB),
      ),
    ),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          _dayLabel,
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 6),
        Tooltip(
          message: weather.condition ?? '정보 없음',
          child: Icon(_icon(), color: const Color(0xFF4169D8), size: 23),
        ),
        const SizedBox(height: 6),
        Text(
          _value(weather.high),
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w900),
        ),
        Text(
          _value(weather.low),
          style: const TextStyle(fontSize: 11, color: Color(0xFF6B7280)),
        ),
      ],
    ),
  );
}
