# Demo-day check: EXAONE on this PC, the tunnel to the server, and the server.
# Run:  powershell -ExecutionPolicy Bypass -File C:\dev\dx-final-upload\deploy\check_demo.ps1
$ok = $true

try {
  Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 5 | Out-Null
  Write-Host "[OK]   EXAONE(Ollama)가 이 PC에서 돌고 있어요" -ForegroundColor Green
} catch {
  Write-Host "[실패] EXAONE(Ollama)가 꺼져 있어요 -> 시작 메뉴에서 Ollama 실행" -ForegroundColor Red
  $ok = $false
}

$tunnel = ssh -o BatchMode=yes -o ConnectTimeout=10 root@211.233.203.19 "curl -s -m 5 http://127.0.0.1:11434/api/version"
if ($tunnel -match 'version') {
  Write-Host "[OK]   서버가 EXAONE에 연결돼 있어요 (터널 정상)" -ForegroundColor Green
} else {
  Write-Host "[실패] 터널이 끊겼어요 -> 아래 명령을 새 PowerShell 창에서 실행하고 창을 닫지 마세요" -ForegroundColor Red
  Write-Host "       powershell -ExecutionPolicy Bypass -File C:\dev\dx-final-upload\deploy\exaone_tunnel.ps1"
  $ok = $false
}

try {
  Invoke-WebRequest https://bogogago.kro.kr/docs -UseBasicParsing -TimeoutSec 10 | Out-Null
  Write-Host "[OK]   서버(bogogago.kro.kr)가 켜져 있어요" -ForegroundColor Green
} catch {
  Write-Host "[실패] 서버에 접속이 안 돼요 -> 네이버 클라우드 콘솔에서 서버가 '운영 중'인지 확인" -ForegroundColor Red
  $ok = $false
}

if ($ok) { Write-Host "`n모두 정상이에요. 앱에서 여행을 하나 만들어 1분 안팎에 나오면 끝." -ForegroundColor Green }
else { Write-Host "`n위의 [실패] 항목을 고친 뒤 이 파일을 다시 실행하세요." -ForegroundColor Yellow }
