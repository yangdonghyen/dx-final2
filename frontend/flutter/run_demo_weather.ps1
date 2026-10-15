# Filming build: the forecast reads as rain or a heat wave.
#   powershell -File run_demo_weather.ps1 rain   (or heat)
# Normal runs use `flutter run` without DEMO_WEATHER.
param([ValidateSet('rain', 'heat')][string]$Weather = 'rain')
Set-Location $PSScriptRoot
C:\flutter\bin\flutter.bat run -d 23188914d70c7ece --dart-define-from-file=.dart_define.dev.json --dart-define=DEMO_WEATHER=$Weather
