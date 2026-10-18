import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'auth/login_screen.dart';

/// 앱을 켜면 처음 보이는 화면입니다. 거북이 둘이 왼쪽에서 천천히 걸어
/// 들어오며 살짝 들썩이고, 가운데에 도착하면 로고가 뿅 나타난 뒤
/// 로그인 화면으로 넘어갑니다.
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  static const holdDuration = Duration(milliseconds: 4200);

  /// true: turtles and logo simply fade in together and fade out.
  /// false: the walk-in with the "뿅" logo.
  static const fadeOnly = false;

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> with TickerProviderStateMixin {
  // One step: the turtles lift a little and settle back down.
  late final AnimationController _step = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 750),
  )..repeat();

  // Slow walk in from the left.
  late final AnimationController _intro = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 2200),
  );

  late final Animation<double> _walkIn = CurvedAnimation(
    parent: _intro,
    curve: Curves.easeOut,
  );

  // "뿅": the word mark pops in once the turtles reach the middle.
  late final AnimationController _pop = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 700),
  );

  late final Animation<double> _popScale = TweenSequence<double>([
    TweenSequenceItem(tween: Tween(begin: 0.0, end: 1.18).chain(CurveTween(curve: Curves.easeOut)), weight: 50),
    TweenSequenceItem(tween: Tween(begin: 1.18, end: 0.94).chain(CurveTween(curve: Curves.easeInOut)), weight: 25),
    TweenSequenceItem(tween: Tween(begin: 0.94, end: 1.0).chain(CurveTween(curve: Curves.easeOut)), weight: 25),
  ]).animate(_pop);

  // Fade-only style: fade in, stay, fade out.
  late final AnimationController _fadeController = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 3100),
  );

  late final Animation<double> _fade = TweenSequence<double>([
    TweenSequenceItem(tween: Tween(begin: 0.0, end: 1.0).chain(CurveTween(curve: Curves.easeOut)), weight: 900),
    TweenSequenceItem(tween: ConstantTween(1.0), weight: 1500),
    TweenSequenceItem(tween: Tween(begin: 1.0, end: 0.0).chain(CurveTween(curve: Curves.easeIn)), weight: 700),
  ]).animate(_fadeController);

  @override
  void initState() {
    super.initState();
    if (SplashScreen.fadeOnly) {
      _step.stop();
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _fadeController.forward(from: 0).whenComplete(_openLogin);
      });
      return;
    }
    // Count from the first painted frame, so a slow start still shows the
    // whole walk-in instead of jumping straight to the login screen.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _intro.forward(from: 0).whenComplete(() {
        if (mounted) _pop.forward(from: 0);
      });
      Future.delayed(SplashScreen.holdDuration, _openLogin);
    });
  }

  void _openLogin() {
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      PageRouteBuilder(
        transitionDuration: const Duration(milliseconds: 450),
        pageBuilder: (_, _, _) => const LoginScreen(),
        transitionsBuilder: (_, animation, _, child) =>
            FadeTransition(opacity: animation, child: child),
      ),
    );
  }

  @override
  void dispose() {
    _step.dispose();
    _intro.dispose();
    _pop.dispose();
    _fadeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final width = math.min(MediaQuery.sizeOf(context).width * 0.62, 320.0);
    if (SplashScreen.fadeOnly) {
      return Scaffold(
        backgroundColor: Colors.white,
        body: Center(
          child: FadeTransition(
            opacity: _fade,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Image.asset('assets/images/splash_turtles.png', width: width, filterQuality: FilterQuality.high),
                const SizedBox(height: 4),
                Image.asset('assets/images/splash_wordmark.png', width: width * 1.3, filterQuality: FilterQuality.high),
              ],
            ),
          ),
        ),
      );
    }
    return Scaffold(
      backgroundColor: Colors.white,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AnimatedBuilder(
              animation: Listenable.merge([_step, _walkIn]),
              builder: (context, child) {
                // 0 → 1 → 0 once per step: a gentle lift, nothing else moves.
                final lift = (1 - math.cos(_step.value * 2 * math.pi)) / 2;
                return Transform.translate(
                  offset: Offset((1 - _walkIn.value) * -width * 1.2, -lift * 7),
                  child: child,
                );
              },
              child: Image.asset(
                'assets/images/splash_turtles.png',
                width: width,
                filterQuality: FilterQuality.high,
              ),
            ),
            const SizedBox(height: 4),
            AnimatedBuilder(
              animation: _pop,
              builder: (context, child) => CustomPaint(
                // A small burst of dots around the logo as it pops.
                painter: _PopBurstPainter(_pop.value),
                child: Opacity(
                  opacity: (_pop.value * 3).clamp(0.0, 1.0),
                  child: Transform.scale(scale: _popScale.value, child: child),
                ),
              ),
              child: Image.asset(
                'assets/images/splash_wordmark.png',
                width: width * 1.3,
                filterQuality: FilterQuality.high,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PopBurstPainter extends CustomPainter {
  _PopBurstPainter(this.progress);

  final double progress;

  static const _colors = [
    Color(0xFF1E3A7B),
    Color(0xFF14B8A6),
    Color(0xFFFF7A3D),
    Color(0xFF4ADE80),
  ];

  @override
  void paint(Canvas canvas, Size size) {
    if (progress <= 0 || progress >= 1) return;
    final center = size.center(Offset.zero);
    final reach = size.width * 0.62;
    final fade = 1 - progress;
    for (var i = 0; i < 12; i++) {
      final angle = i * math.pi / 6 + 0.2;
      final distance = reach * Curves.easeOut.transform(progress) * (i.isEven ? 1 : 0.8);
      final offset = center + Offset(math.cos(angle) * distance, math.sin(angle) * distance * 0.55);
      canvas.drawCircle(
        offset,
        (i.isEven ? 7 : 5) * fade,
        Paint()..color = _colors[i % _colors.length].withValues(alpha: fade),
      );
    }
  }

  @override
  bool shouldRepaint(_PopBurstPainter old) => old.progress != progress;
}
