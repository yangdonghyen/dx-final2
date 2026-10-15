import '../data/api/api_client.dart';
import 'auth_service.dart';

class CurrentWeather {
  const CurrentWeather({this.temperature, this.condition, this.precipitationProbability, this.humidity, this.windSpeed});
  final double? temperature;
  final String? condition;
  final int? precipitationProbability;
  final int? humidity;
  final double? windSpeed;
  factory CurrentWeather.fromJson(Map<String, dynamic> json) => CurrentWeather(temperature: (json['temperature'] as num?)?.toDouble(), condition: json['condition']?.toString(), precipitationProbability: (json['precipitation_probability'] as num?)?.toInt(), humidity: (json['humidity'] as num?)?.toInt(), windSpeed: (json['wind_speed'] as num?)?.toDouble());
}

class DailyWeather {
  const DailyWeather({required this.date, this.condition, this.high, this.low});
  final DateTime date;
  final String? condition;
  final double? high;
  final double? low;
  factory DailyWeather.fromJson(Map<String, dynamic> json) => DailyWeather(date: DateTime.parse(json['date'] as String), condition: json['condition']?.toString(), high: (json['high'] as num?)?.toDouble(), low: (json['low'] as num?)?.toDouble());
}

class WeatherData {
  const WeatherData({required this.locationName, required this.forecastBaseAt, required this.current, required this.daily});
  final String locationName;
  final DateTime forecastBaseAt;
  final CurrentWeather current;
  final List<DailyWeather> daily;
  factory WeatherData.fromJson(Map<String, dynamic> json) => WeatherData(locationName: json['location_name'] as String, forecastBaseAt: DateTime.parse(json['forecast_base_at'] as String), current: CurrentWeather.fromJson(json['current'] as Map<String, dynamic>), daily: (json['daily'] as List? ?? const []).whereType<Map<String, dynamic>>().map(DailyWeather.fromJson).toList());
}

/// Filming build only: `--dart-define=DEMO_WEATHER=rain` or `=heat`
/// (`DEMO_RAIN=true` still means rain).  The server's real forecast is
/// reshaped so the whole screen reads as that weather: current values, the
/// weekly card for today and tomorrow.  Never set in a normal build.
const String demoWeather = String.fromEnvironment(
  'DEMO_WEATHER',
  defaultValue: bool.fromEnvironment('DEMO_RAIN') ? 'rain' : '',
);
const bool demoWeatherOn = demoWeather == 'rain' || demoWeather == 'heat';

const _precipitation = {'비', '비/눈', '눈', '소나기'};

/// Rain, snow or showers now: the rain plan (계획 2).
bool isRainyWeather(WeatherData weather) => _precipitation.contains(weather.current.condition);

/// 33°C and over (폭염 주의보 기준) now or as today's high: the heat plan (계획 3).
bool isHeatWave(WeatherData weather) =>
    (weather.current.temperature ?? 0) >= 33 ||
    (weather.daily.isNotEmpty && (weather.daily.first.high ?? 0) >= 33);

Map<String, dynamic> _withDemoWeather(Map<String, dynamic> json) {
  if (!demoWeatherOn) return json;
  final rain = demoWeather == 'rain';
  final current = Map<String, dynamic>.from(json['current'] as Map? ?? const {});
  final actual = (current['temperature'] as num?)?.toDouble() ?? 18;
  final temperature = rain ? (actual > 21 ? 19.0 : actual) : 35.0;
  current.addAll(rain
      ? {'condition': '비', 'temperature': temperature, 'precipitation_probability': 80, 'humidity': 88, 'wind_speed': 4.6}
      : {'condition': '맑음', 'temperature': temperature, 'precipitation_probability': 0, 'humidity': 62, 'wind_speed': 1.8});
  final daily = [
    for (final day in (json['daily'] as List? ?? const [])) Map<String, dynamic>.from(day as Map),
  ];
  if (daily.isNotEmpty) {
    daily[0].addAll(rain
        ? {'condition': '비', 'high': (temperature + 2).roundToDouble(), 'low': (temperature - 4).roundToDouble()}
        : {'condition': '맑음', 'high': 36.0, 'low': 27.0});
  }
  if (daily.length > 1) {
    daily[1].addAll(rain ? {'condition': '흐림'} : {'condition': '맑음', 'high': 35.0, 'low': 26.0});
  }
  return {...json, 'current': current, 'daily': daily};
}

class WeatherService {
  WeatherService({ApiClient? apiClient}) : _apiClient = apiClient ?? ApiClient();
  final ApiClient _apiClient;
  String get _accessToken {
    final token = AuthSession.accessToken;
    if (token == null || token.isEmpty) throw StateError('Login is required.');
    return token;
  }
  Future<WeatherData> getWeather(String destination) async {
    final cleanDestination = destination.trim();
    if (cleanDestination.isEmpty) throw ArgumentError.value(destination, 'destination', 'must not be blank');
    final response = await _apiClient.get('/api/v1/weather?destination=${Uri.encodeQueryComponent(cleanDestination)}', accessToken: _accessToken);
    return WeatherData.fromJson(_withDemoWeather(response));
  }

  Future<WeatherData> getWeatherAt({
    required double latitude,
    required double longitude,
  }) async {
    final response = await _apiClient.get(
      '/api/v1/weather?lat=$latitude&lon=$longitude',
      accessToken: _accessToken,
    );
    return WeatherData.fromJson(_withDemoWeather(response));
  }
}
