# Filming build: rain forecast forced on (DEMO_RAIN). Normal runs omit this flag.
Set-Location $PSScriptRoot
C:\flutter\bin\flutter.bat run -d 23188914d70c7ece --dart-define-from-file=.dart_define.dev.json --dart-define=DEMO_RAIN=true
