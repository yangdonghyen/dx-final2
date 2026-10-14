# 로그인·YouTube·여행 생성 복구 보고서 (2026-10-13)

대상: `C:\dev\dx-final-upload` (비교 참고: `C:\dev\dx-all`, 읽기만 함)

## A. 장애 원인

| 문제 | 실제 원인 | 증거 파일·함수 | 수정 여부 | 검증 결과 |
|---|---|---|---|---|
| 네이버 로그인 실패 | **확정**: 앱이 `API_BASE_URL=http://127.0.0.1:8000`으로 빌드된 상태에서 `adb reverse`가 없어 휴대폰의 127.0.0.1:8000 연결이 거부됨. SDK는 성공(`NAVER login success`)했지만 `/api/v1/auth/naver/token-login` 호출이 실패했고, `login_screen.dart`의 `catch (_)`가 예외를 삼켜 "네이버 로그인에 실패했습니다"만 표시하고 로그도 남기지 않음 | `lib/services/auth_service.dart` `loginWithNaver()`, `lib/screens/auth/login_screen.dart` `loginWithNaver()` catch 블록. 휴대폰에서 `nc 127.0.0.1 8000` → Connection refused, `adb reverse --list` 비어 있음. 로그인 실패한 프로세스(18:34, 6회 시도)와 LAN 빌드 프로세스(18:38, 1회 시도 후 홈 진입)가 다름 | 실패 원인 로그 추가 (아래 B) | LAN 빌드에서 로그인 후 홈 진입 확인(로그캣: 홈 화면에서 이벤트 수신, Trip 생성 API 성공). 백엔드 JWT 응답 자체는 백엔드 콘솔을 볼 수 없어 직접 확인 못 함 |
| YouTube 연결 실패 | **확정 (일부)**: 현재 프로젝트 홈의 YouTube 팝업 **'여행 계획하기' 버튼이 빈 동작**(`debugPrint`만 함). dx-all에는 오늘 16:37에 추가된 저장→지역 확인→여행 만들기 이동 코드가 있었는데 이전되지 않음. 또한 PC 쪽 송신기인 크롬 확장(`tools/chrome_youtube_pause_bridge`)이 dx-all에만 있고 Git에도 없음 | `lib/screens/home/home_screen.dart` 여행 계획하기 `onPressed` | 수정함 | PC 백엔드에서 `/discovery/youtube-pause` → WebSocket 브로드캐스트가 127.0.0.1과 LAN IP 모두 정상(YouTube 메타데이터 제목까지 받음 = YouTube API 키 유효). **실기기 앱이 LAN 주소로 WebSocket에 연결돼 이벤트를 수신함**(로그캣 `[YouTube Bridge] SERVICE received`, `HOME received`). '여행 계획하기' 수정본은 실기기 재실행 후 확인 필요 |
| API 주소 충돌 | **확정**: Flutter의 모든 백엔드 통신(`ApiClient`, `YoutubeBridgeService` WebSocket)이 같은 `API_BASE_URL` 컴파일 상수 하나를 씀. 127.0.0.1은 `adb reverse`가 있어야만 동작하고, USB 재연결 시 reverse가 사라짐. LAN IP는 현재 휴대폰(192.168.219.238)과 PC(192.168.219.122)가 같은 서브넷이고 방화벽이 8000을 허용해 동작함 | `lib/data/api/api_client.dart`, `lib/services/youtube_bridge_service.dart`. 휴대폰에서 `nc 192.168.219.122 8000` → HTTP 200 | 설정 분리 안내(E), `.gitignore` 보강 | LAN: 로그인·YouTube 수신·Trip 생성 동작 확인. adb reverse 방식은 현재 미설정 상태라 미검증 |
| 여행 생성 문제 | **확정**: EXAONE 호출까지는 도달(약 89초 후 응답)했으나 백엔드가 `422 ROUTE_TIME_CONFLICT`(실제 이동시간 반영 시 식사가 식사 시간대를 벗어남)로 거절. 그래서 trip 80~82는 DRAFT만 있고 `travel_plans`가 없음. dx-all에는 오늘 오후에 추가된 이동시간 보정(repair) 로직이 있었는데 이전되지 않음 | 로그캣 `[Plan] generate failed: ApiException(422, ROUTE_TIME_CONFLICT…)`, `app/services/plan_generation_service.py` `generate_plan`, `app/services/plan_travel_time.py` | dx-all의 보정 로직을 3-way 병합으로 이식 (B) | 백엔드 단위 테스트 통과(아래 D). 실제 앱에서 재생성은 미검증 |

추정 원인으로 남은 것: 사용자가 "LAN으로 바꾸자 YouTube가 끊겼다"고 느낀 시점은, 이 버튼이 동작하지 않는 상태와 크롬 확장 설정(LAN IP로 송신)이 겹친 결과로 보입니다. 현재 측정으로는 LAN 주소가 YouTube 연결을 끊는다는 증거는 없습니다.

## B. 수정 파일

Flutter
- `frontend/flutter/lib/screens/home/home_screen.dart`: YouTube 팝업 '여행 계획하기'가 영상을 서버에 저장(`YouTubeSavedDiscoveryService.save`)하고, 서버가 확인한 지역으로 `TripPlacesScreen`을 엽니다. 중복 탭 방지, 실패 시 스낵바와 `[YouTube Bridge] PLAN failed` 로그. (dx-all의 해당 부분만 선택 이식, 비 알림 등 다른 변경은 가져오지 않음)
- `frontend/flutter/lib/screens/auth/login_screen.dart`: 네이버·카카오·일반 로그인 실패 시 원인을 구분해 로그(`[Auth] naver step=server_login failed kind=network|timeout|auth_rejected status=…|server_error status=…|bad_response base_url=…`)를 남기고, 네트워크·타임아웃이면 화면 문구도 다르게 표시. 토큰·응답 본문은 기록하지 않음. 일반 로그인은 401일 때만 "아이디 또는 비밀번호가 올바르지 않습니다".

Backend (dx-all 오늘 변경분을 현재 프로젝트 변경과 3-way 병합)
- `backend/app/services/plan_generation_service.py`: 이동시간 보정(`repair=True`), 단계별 소요시간 로그(`plan_generation_timing`), 검증 성공 후에만 선택 장소 저장. 충돌 1곳은 **현재 프로젝트의 앵커 계약을 유지**하도록 직접 해결: `selected_place_ids` 생략 → 저장된 앵커 사용, `[]` → 목적지 전체 기반.
- `backend/app/services/plan_travel_time.py`, `place_search_service.py`, `external/place/kakao_provider.py`, `external/routing/cached_provider.py`: dx-all 변경분 병합(충돌 없음)
- `backend/tests/unit/test_plan_generation_service.py`, `test_place_search_service.py`: 병합, `test_route_time_repair.py`: 추가
- 병합 전 원본 백업: `%TEMP%\merge\orig_backup\` (Git 밖)

기타
- `tools/chrome_youtube_pause_bridge/`: dx-all에서 복사(누락 폴더 추가, 덮어쓴 파일 없음). 키 없음, 주소만 있음.
- `.gitignore`: `*.backup`, `frontend/flutter/.dart_define.*.json`(예시 파일 제외) 추가. 기존 `.dart_define.dev.json.backup`, `local.properties.backup`이 Git에 올라갈 수 있는 상태였음.

`.env`, `local.properties`, `.dart_define.dev.json`은 수정하지 않았습니다. DB는 읽기 조회만 했습니다(Alembic `011_trip_transport_mode_walk (head)` 확인).

## C. API 연결 구조

1. 네이버 로그인: 네이버 SDK(MainActivity, MethodChannel `travelmate/naver_auth`) → 네이버 Access Token → `POST {API_BASE_URL}/api/v1/auth/naver/token-login` → JWT 저장 → 홈. 표시 이름은 `https://openapi.naver.com/v1/nid/me`를 앱이 직접 호출(실패해도 로그인은 유지).
2. YouTube: PC 크롬 확장이 YouTube 일시정지 시 `POST http://192.168.219.122:8000/api/v1/discovery/youtube-pause` → 백엔드가 YouTube Data API로 제목 조회 → WebSocket `ws://{API_BASE_URL 호스트}/api/v1/discovery/youtube-events`로 휴대폰에 전달 → '여행 계획하기' → `POST {API_BASE_URL}/api/v1/discovery/youtube-saved`. Flutter는 YouTube Data API를 직접 호출하지 않습니다.
3. EXAONE 여행 생성: `POST {API_BASE_URL}/api/v1/trips` → 계획 생성 API(180초 타임아웃) → 백엔드가 Ollama `127.0.0.1:11434`의 `EXAONE-3.5-7.8B`(로드됨 확인) 호출 → 검증 → MySQL 저장.

세 기능 모두 같은 `API_BASE_URL` 하나를 씁니다. 127.0.0.1 하드코딩은 `ApiClient`·`YoutubeBridgeService`의 기본값뿐이고, dx-all 주소를 직접 참조하는 코드는 없습니다.

## D. 테스트 결과

| 항목 | 결과 |
|---|---|
| `flutter analyze` (수정한 2개 파일) | 성공, 이슈 없음 |
| `flutter test` 전체 | 46 성공 / 5 파일 로드 실패. 실패는 기존 테스트가 없어진 API(`AuthService.login` 등)를 써서 컴파일되지 않는 것으로, 이번 수정과 무관 |
| 백엔드 `pytest tests/unit` | 701 성공 / 3 실패. 3개는 병합 전에도 똑같이 실패하던 테스트(`test_plan_validation_service::test_validation_marks_valid_items`, `test_trip_service` 2개) |
| 휴대폰 → PC LAN 8000 | 성공 (HTTP 200) |
| 휴대폰 → 127.0.0.1:8000 | 실패 (adb reverse 없음) |
| YouTube pause → WebSocket → 실기기 수신 | 성공 |
| 실기기 네이버 로그인 → 홈 | LAN 빌드에서 성공(로그로 추정 확인) |
| Trip 생성 API | 성공 (trip_id 82) |
| EXAONE 일정 생성 | 실패 → 수정 후 미검증 (앱에서 다시 생성 필요) |
| 수정한 Flutter 코드 실기기 실행 | 미실행 (앱 재빌드 필요) |

## E. 사용자가 실행할 PowerShell 명령어

FastAPI(이미 `--reload`로 실행 중이면 백엔드 수정은 자동 반영됨, 지금 응답 200 확인):
```powershell
cd C:\dev\dx-final-upload\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Flutter 실기기 실행 (현재 권장: LAN 방식, 지금 실제로 동작 확인됨):
```powershell
cd C:\dev\dx-final-upload\frontend\flutter
flutter run -d 23188914d70c7ece --dart-define-from-file=.dart_define.dev.json
```

USB(adb reverse) 방식을 따로 쓰고 싶을 때 (IP가 바뀌는 장소에서 유용):
```powershell
cd C:\dev\dx-final-upload\frontend\flutter
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
$d = Get-Content .dart_define.dev.json -Raw | ConvertFrom-Json
$d.API_BASE_URL = 'http://127.0.0.1:8000'
[IO.File]::WriteAllText("$PWD\.dart_define.usb.json", ($d | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
& $adb -s 23188914d70c7ece reverse tcp:8000 tcp:8000
& $adb -s 23188914d70c7ece reverse --list
flutter run -d 23188914d70c7ece --dart-define-from-file=.dart_define.usb.json
```
USB를 다시 꽂으면 `reverse tcp:8000 tcp:8000`만 다시 실행하세요. 크롬 확장은 PC에서 보내므로 두 방식 모두 LAN 주소 그대로 둡니다.

PC IP가 바뀌었는지 확인:
```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '169.*' -and $_.IPAddress -ne '127.0.0.1' } | Select-Object InterfaceAlias,IPAddress
```
바뀌었다면 `.dart_define.dev.json`의 `API_BASE_URL`과 `tools\chrome_youtube_pause_bridge\config.js`, `manifest.json`의 `host_permissions`를 같이 바꾸고 확장을 다시 로드합니다.

로그인·YouTube·여행 생성 로그 확인:
```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb -s 23188914d70c7ece logcat -c
& $adb -s 23188914d70c7ece logcat | Select-String 'TravelMateNaver|\[Auth\]|\[YouTube Bridge\]|\[Plan\]|\[Trip\]'
```

크롬 확장: `chrome://extensions` → 개발자 모드 → 압축해제된 확장 로드 → `C:\dev\dx-final-upload\tools\chrome_youtube_pause_bridge` 선택 (기존 dx-all 경로의 확장은 제거하거나 비활성화).

## F. 남은 문제

- 수정 후 EXAONE 일정 생성이 실제로 성공하는지 앱에서 확인 필요. 또 실패하면 로그캣의 `[Plan] generate failed`의 오류 코드와 백엔드 콘솔의 `plan_generation_timing` 줄을 알려주세요.
- 백엔드 JWT 발급은 백엔드 콘솔을 보지 못해 직접 확인하지 못했습니다(앱이 홈으로 이동한 것으로 성공을 추정).
- `backend\.env`의 TOUR/KMA 키 4개가 31~34행(빈 값)과 36~52행(값 있음)에 중복. 뒤쪽 값이 적용되어 현재 실제 설정은 모두 채워져 있음(확인함). 혼동을 줄이려면 31~34행 삭제를 권장합니다.
- dx-all에서 오늘 오후 바뀐 Flutter 쪽 파일(`plan_service.dart`, `trip_service.dart`, `trip_places_screen.dart`, `ai_working_indicator.dart`, `weather_screen.dart`와 관련 테스트)은 이번 범위에서 이식하지 않았습니다. 생성 중 화면 표시 개선 등으로 보이며 필요하면 따로 진행합니다.
- 기존에 깨져 있던 Flutter 테스트 5개, 백엔드 테스트 3개는 그대로입니다.
