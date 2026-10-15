import 'package:flutter_test/flutter_test.dart';
import 'package:travel_mate/services/weather_service.dart';

WeatherData _weather({String condition = '맑음', double temperature = 20, double? high}) => WeatherData.fromJson({
  'location_name': '현재 위치',
  'forecast_base_at': '2026-10-15T08:00:00+09:00',
  'current': {'condition': condition, 'temperature': temperature},
  'daily': [
    {'date': '2026-10-15', 'condition': condition, 'high': ?high},
  ],
});

void main() {
  test('rain opens plan 2 and a heat wave (33°C+) opens plan 3', () {
    expect(isRainyWeather(_weather(condition: '비')), isTrue);
    expect(isRainyWeather(_weather(condition: '소나기')), isTrue);
    expect(isRainyWeather(_weather()), isFalse);

    expect(isHeatWave(_weather(temperature: 35)), isTrue);
    expect(isHeatWave(_weather(temperature: 28, high: 34)), isTrue); // today's high counts
    expect(isHeatWave(_weather(temperature: 28, high: 31)), isFalse);
  });

  test('a normal build never reshapes the real forecast', () {
    expect(demoWeatherOn, isFalse);
  });
}
