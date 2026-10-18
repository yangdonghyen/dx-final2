import 'package:flutter/material.dart';
import 'core/layout/app_responsive.dart';
import 'core/theme/app_theme.dart';
import 'screens/splash_screen.dart';

/// Lets screens (Home's YouTube bridge) know when another page covers them.
final RouteObserver<PageRoute<dynamic>> appRouteObserver = RouteObserver<PageRoute<dynamic>>();

/// 앱 전체의 테마, 제목, 첫 화면을 설정하는 최상위 위젯입니다.
class TravelMateApp extends StatelessWidget {
  const TravelMateApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: '보고가고',
    theme: AppTheme.light,
    builder: (context, child) {
      // Button labels (친구 초대하기, 여행 계획하기) were laid out for a
      // 360dp-wide screen.  A phone with a large 화면 크기 (display zoom, e.g.
      // the S23+ at 320dp) or 글꼴 크기 wrapped their last letter, so text
      // grows at most 15% and shrinks with a narrower screen.  편한 모드 has
      // large text of its own.
      final media = MediaQuery.of(context);
      final width = media.size.width;
      final narrow = width > 0 && width < 360 ? width / 360 : 1.0;
      final scale = media.textScaler.scale(1).clamp(0.8, 1.15) * narrow;
      return MediaQuery(
        data: media.copyWith(textScaler: TextScaler.linear(scale)),
        child: AppResponsive(child: child ?? const SizedBox.shrink()),
      );
    },
    navigatorObservers: [appRouteObserver],
    home: const SplashScreen(),
  );
}
