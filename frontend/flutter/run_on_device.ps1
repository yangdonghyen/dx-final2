param(
  [Parameter(Mandatory = $true)][string]$Device,
  [ValidateSet('none', 'rain', 'heat')][string]$Weather = 'none',
  # dev = this PC's backend, prod = the deployed server (.dart_define.prod.json)
  [ValidateSet('dev', 'prod')][string]$Server = 'dev'
)
# Run the app on a specific phone (adb device id), optionally with the demo weather.
Set-Location $PSScriptRoot
$defines = ".dart_define.$Server.json"
if ($Weather -eq 'none') {
  C:\flutter\bin\flutter.bat run -d $Device --dart-define-from-file=$defines
} else {
  C:\flutter\bin\flutter.bat run -d $Device --dart-define-from-file=$defines --dart-define=DEMO_WEATHER=$Weather
}
