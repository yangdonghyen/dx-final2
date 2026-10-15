import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:kakao_flutter_sdk_common/kakao_flutter_sdk_common.dart';

import 'app.dart';
import 'services/active_trip_service.dart';
import 'services/auth_service.dart';
import 'services/display_mode_service.dart';
import 'services/invite_link_service.dart';
import 'data/api/api_client.dart';
import 'services/weather_background_service.dart';
import 'services/weather_notification_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AuthSession.restore();
  // Expired access tokens (30 min) are renewed and the request retried.
  ApiClient.refreshAccessToken = AuthService().refreshAccessToken;
  await ActiveTripService.restore();
  await DisplayModeService.restore();
  InviteLinkService.initialize();
  final isAndroid = !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  if (isAndroid) {
    await WeatherNotificationService.instance.initialize();
    await WeatherBackgroundService.initialize();
  }

  // Kakao Native App Key
  // API 키가 없어도 앱 자체는 실행되도록 처리
  const kakaoNativeAppKey = String.fromEnvironment('KAKAO_NATIVE_APP_KEY');

  // Android / iOS 모바일 환경인지 확인
  final isNativeMobile =
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android ||
          defaultTargetPlatform == TargetPlatform.iOS);

  // 모바일 + Kakao API 키가 존재할 때만 Kakao SDK 초기화
  if (isNativeMobile && kakaoNativeAppKey.isNotEmpty) {
    await KakaoSdk.init(nativeAppKey: kakaoNativeAppKey);

    debugPrint('Kakao SDK 초기화 완료');
  } else if (isNativeMobile) {
    // API 키가 없어도 앱 실행은 계속 진행
    debugPrint('KAKAO_NATIVE_APP_KEY가 없어 Kakao SDK 초기화를 건너뜁니다.');
  }

  runApp(const TravelMateApp());
}
