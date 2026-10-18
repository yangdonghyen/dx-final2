import 'dart:async';

import 'package:flutter/material.dart';

import '../core/theme/app_theme.dart';

/// AI가 오래 걸리는 작업을 하는 동안 진행 중인 느낌의 문구를 돌아가며 보여줍니다.
class AiWorkingIndicator extends StatefulWidget {
  const AiWorkingIndicator({
    super.key,
    required this.title,
    this.messages = planningMessages,
    this.expectedDuration = averagePlanDuration,
  });

  final String title;
  final List<String> messages;

  /// How long the job usually takes; the messages are spread evenly over it.
  final Duration expectedDuration;

  /// Average of the measured EXAONE plan generations (6 runs, 53~114s).
  static const averagePlanDuration = Duration(seconds: 80);

  static const planningMessages = [
    '여행 지도를 펼치는 중이에요 🗺️',
    '가볼 만한 곳을 골라보는 중이에요 📍',
    '현지 맛집을 살펴보는 중이에요 🍜',
    '점심은 어디서 먹을지 고민하는 중이에요 🤔',
    '이동 동선을 이리저리 맞춰보는 중이에요 🚗',
    '쉬어갈 틈도 넣어보는 중이에요 ☕',
    '하루 일정이 너무 빡빡하지 않은지 보는 중이에요 👀',
    '거의 다 됐어요, 마무리하는 중이에요 ✨',
  ];

  static const easierMessages = [
    '힘든 구간을 찾아보는 중이에요 🔍',
    '걷는 거리를 줄여보는 중이에요 🚶',
    '쉬는 시간을 끼워 넣는 중이에요 ☕',
    '더 여유로운 순서로 바꿔보는 중이에요 🧩',
    '거의 다 됐어요, 마무리하는 중이에요 ✨',
  ];

  @override
  State<AiWorkingIndicator> createState() => _AiWorkingIndicatorState();
}

class _AiWorkingIndicatorState extends State<AiWorkingIndicator> {
  Timer? _timer;
  int _index = 0;

  @override
  void initState() {
    super.initState();
    // 평균 생성 시간 ÷ 문구 수: 마지막 문구가 평균 완료 시점쯤 나옵니다.
    final step = widget.expectedDuration ~/ widget.messages.length;
    _timer = Timer.periodic(step, (_) {
      if (!mounted) return;
      setState(() {
        // 마지막 문구에서 멈춰 끝없이 도는 느낌을 줄입니다.
        if (_index < widget.messages.length - 1) _index++;
      });
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(color: AppColors.primary),
          const SizedBox(height: 24),
          Text(
            widget.title,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 23, fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 14),
          SizedBox(
            height: 48,
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 400),
              transitionBuilder: (child, animation) => FadeTransition(
                opacity: animation,
                child: SlideTransition(
                  position: Tween<Offset>(
                    begin: const Offset(0, 0.3),
                    end: Offset.zero,
                  ).animate(animation),
                  child: child,
                ),
              ),
              child: Text(
                widget.messages[_index],
                key: ValueKey(_index),
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                  color: AppColors.primary,
                ),
              ),
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            '1~3분 정도 걸릴 수 있으니 화면을 닫지 말고 기다려주세요.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 15, color: Color(0xFF6B7280)),
          ),
        ],
      ),
    ),
  );
}
