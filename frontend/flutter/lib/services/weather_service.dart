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

/// Filming build only (`--dart-define=DEMO_RAIN=true`): the current weather
/// reads as rain so the rain flow (notification -> plan 2 -> proposal) can be
/// shown on a dry day.  Never set in a normal build.
const bool demoRain = bool.fromEnvironment('DEMO_RAIN');

Map<String, dynamic> _withDemoRain(Map<String, dynamic> json) {
  if (!demoRain) return json;
  final current = Map<String, dynamic>.from(json['current'] as Map? ?? const {});
  current['condition'] = '비';
  current['precipitation_probability'] = 90;
  return {...json, 'current': current};
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
    return WeatherData.fromJson(response);
  }

  Future<WeatherData> getWeatherAt({
    required double latitude,
    required double longitude,
  }) async {
    final response = await _apiClient.get(
      '/api/v1/weather?lat=$latitude&lon=$longitude',
      accessToken: _accessToken,
    );
    return WeatherData.fromJson(_withDemoRain(response));
  }
}
