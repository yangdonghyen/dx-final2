# 보고가고 Flutter

React + Vite `프로젝트v1`을 Android Studio에서 관리하기 쉽게 화면별 Dart 파일로 분리한 새 Flutter 소스 프로젝트입니다.

## 처음 한 번만 실행
이 ZIP을 원하는 위치에 압축 해제한 뒤, **압축 해제 폴더에서** 터미널을 엽니다.

```powershell
flutter create .
flutter pub get
flutter analyze
flutter run -d emulator-5558
```

## Android physical-device backend URL

The default API URL (`127.0.0.1:8000`) only works when the backend runs on the
same device. For a physical Android device, copy
`.dart_define.dev.example.json` to the ignored `.dart_define.dev.json`, replace
`YOUR_PC_LAN_IP` with the development PC's LAN IPv4 address, and run:

```powershell
flutter run -d <ANDROID_DEVICE_ID> --dart-define-from-file=.dart_define.dev.json
```

Start FastAPI on the PC with `--host 0.0.0.0 --port 8000`. The phone and PC
must be on the same network. Do not commit the local define file.

`flutter create .`는 이 소스 폴더에 Android/iOS/Web/Windows 등 Flutter 플랫폼 폴더를 생성합니다.
이미 들어 있는 `lib`, `assets`, `pubspec.yaml`은 이 프로젝트의 소스입니다.

## 구조
- `screens/auth`: 로그인, 회원가입, 초기 설정
- `screens/home`: 홈
- `screens/search`: 텍스트/음성 검색
- `screens/discovery`: 카메라, 분석, 장소 결과/상세, 지도
- `screens/preference`: YouTube 저장, AI 취향 분석
- `screens/trip`: 장소/날짜/인원/교통/예산/동행자/일정
- `screens/travel`: 편안한 여행, 숙소, 출발 전, 여행 중, 휴식, 날씨, 길찾기
- `screens/my`: 지난 여행, 알림, 프로필
- `models`, `services`, `widgets`, `core`: 공통 로직

실제 카메라, Leaflet 지도, OAuth, ThinQ, 날씨 API는 UI/화면 구조와 분리되어 있으며 후속 API 연결 단계에서 붙이면 됩니다.
