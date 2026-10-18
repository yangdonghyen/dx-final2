import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:flutter/services.dart';
import '../../core/layout/app_responsive.dart';
import '../../core/theme/app_theme.dart';
import '../../data/api/api_client.dart';
import '../../widgets/primary_button.dart';
import '../../services/auth_service.dart';
import '../home/home_screen.dart';
import 'register_screen.dart';

/// 로그인 입력을 받고 성공 시 홈 화면으로 이동시키는 화면입니다.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _S();
}

class _S extends State<LoginScreen> {
  final id = TextEditingController(), pw = TextEditingController();
  String notice = '';
  bool loggingIn = false;
  bool autoLogin = false;
  final AuthService authService = AuthService();
  bool resuming = AuthSession.autoLogin && (AuthSession.refreshToken?.isNotEmpty ?? false);

  @override
  void initState() {
    super.initState();
    if (resuming) _resume();
  }

  Future<void> _resume() async {
    final ok = await authService.resumeSession();
    if (!mounted) return;
    if (ok) {
      _goHome();
    } else {
      setState(() => resuming = false);
    }
  }

  /// Every successful login remembers the "자동 로그인" choice, then opens Home.
  Future<void> _goHome() async {
    if (!resuming) await AuthSession.setAutoLogin(autoLogin);
    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (_) => const HomeScreen()),
    );
  }

  Future<void> loginWithKakao() async {
    if (loggingIn) return;

    setState(() {
      loggingIn = true;
      notice = '';
    });

    try {
      await authService.loginWithKakao();

      if (!mounted) return;

      await _goHome();
    } catch (e) {
      if (!mounted) return;

      setState(() {
        notice = _loginFailureNotice('kakao', e, '서버 로그인에 실패했습니다.');
        loggingIn = false;
      });
    }
  }

  Future<void> loginWithNaver() async {
    if (loggingIn) return;
    setState(() {
      loggingIn = true;
      notice = '';
    });
    try {
      await authService.loginWithNaver();
      if (!mounted) return;
      await _goHome();
    } on PlatformException catch (error) {
      debugPrint('[Auth] naver step=sdk code=${error.code}');
      if (!mounted) return;
      setState(() {
        notice = error.code == 'NAVER_LOGIN_CANCELLED'
            ? '네이버 로그인을 취소했습니다.'
            : '네이버 로그인에 실패했습니다.';
        loggingIn = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        notice = _loginFailureNotice('naver', error, '네이버 로그인에 실패했습니다.');
        loggingIn = false;
      });
    }
  }

  Future<void> login() async {
    if (loggingIn) return;

    final loginId = id.text.trim();
    final password = pw.text;

    if (loginId.isEmpty || password.isEmpty) {
      setState(() {
        notice = '아이디와 비밀번호를 입력해주세요.';
      });
      return;
    }

    setState(() {
      loggingIn = true;
      notice = '';
    });

    try {
      await authService.loginLocal(loginId, password);

      if (!mounted) return;

      await _goHome();
    } catch (error) {
      if (!mounted) return;

      setState(() {
        notice = error is ApiException && error.statusCode == 401
            ? '아이디 또는 비밀번호가 올바르지 않습니다.'
            : _loginFailureNotice(
                'local',
                error,
                '아이디 또는 비밀번호가 올바르지 않습니다.',
              );
        loggingIn = false;
      });
    }
  }

  @override
  Widget build(BuildContext c) => Scaffold(
    backgroundColor: Colors.white,
    // Auto login: keep the form hidden while the saved session is checked.
    body: resuming ? const Center(child: CircularProgressIndicator()) : SafeArea(
      child: ListView(
        padding: EdgeInsets.fromLTRB(ResponsiveLayout.pageHorizontal(c), 48, ResponsiveLayout.pageHorizontal(c), 28),
        children: [
          // The app's turtle logo (same images as the start screen).
          Center(
            child: Image.asset(
              'assets/images/splash_turtles.png',
              width: 200,
              filterQuality: FilterQuality.high,
            ),
          ),
          const SizedBox(height: 4),
          Center(
            child: Image.asset(
              'assets/images/splash_wordmark.png',
              width: 240,
              filterQuality: FilterQuality.high,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            '나에게 맞는 여행을 시작해볼까요?',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey),
          ),
          const SizedBox(height: 34),
          TextField(
            controller: id,
            decoration: const InputDecoration(hintText: '아이디 또는 이메일'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: pw,
            obscureText: true,
            decoration: const InputDecoration(hintText: '비밀번호'),
          ),
          if (notice.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(
                notice,
                style: const TextStyle(color: AppColors.primary),
              ),
            ),
          Padding(
            padding: const EdgeInsets.only(top: 4, bottom: 8),
            child: Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              runSpacing: 4,
              spacing: 8,
              children: [
                Semantics(
                  label: '자동 로그인',
                  checked: autoLogin,
                  child: InkWell(
                    onTap: () => setState(() => autoLogin = !autoLogin),
                    borderRadius: BorderRadius.circular(8),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Checkbox(
                            value: autoLogin,
                            onChanged: (value) =>
                                setState(() => autoLogin = value ?? false),
                            visualDensity: VisualDensity.compact,
                          ),
                          const Text('자동 로그인', style: TextStyle(fontSize: 13)),
                        ],
                      ),
                    ),
                  ),
                ),
                Wrap(
                  crossAxisAlignment: WrapCrossAlignment.center,
                  spacing: 0,
                  children: [
                    TextButton(
                      style: TextButton.styleFrom(
                        minimumSize: Size.zero,
                        padding: const EdgeInsets.symmetric(horizontal: 6),
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                      onPressed: () => setState(
                        () => notice = '가입한 아이디 또는 비밀번호를 재설정할 수 있어요.',
                      ),
                      child: const Text('아이디/비밀번호 찾기'),
                    ),
                    const Padding(
                      padding: EdgeInsets.symmetric(horizontal: 5),
                      child: Text('|', style: TextStyle(color: Color(0xFFD1D5DB))),
                    ),
                    TextButton(
                      style: TextButton.styleFrom(
                        minimumSize: Size.zero,
                        padding: const EdgeInsets.symmetric(horizontal: 6),
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                      onPressed: () => Navigator.push(
                        c,
                        MaterialPageRoute(builder: (_) => const RegisterScreen()),
                      ),
                      child: const Text(
                        '회원가입',
                        style: TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          PrimaryButton('로그인하기', onPressed: loggingIn ? null : login),
          const SizedBox(height: 22),
          const Row(
            children: [
              Expanded(child: Divider()),
              Padding(
                padding: EdgeInsets.symmetric(horizontal: 12),
                child: Text('또는', style: TextStyle(color: Colors.grey)),
              ),
              Expanded(child: Divider()),
            ],
          ),
          const SizedBox(height: 20),
          PrimaryButton(
            '♡  카카오로 로그인하기',
            color: Color(0xFFFFE500),
            onPressed: loginWithKakao,
          ),
          const SizedBox(height: 12),
          PrimaryButton(
            '◯  네이버로 로그인하기',
            color: Color(0xFF03C75A),
            onPressed: loggingIn ? null : loginWithNaver,
          ),
        ],
      ),
    ),
  );
}

/// Logs why a server login failed (no tokens or bodies) and picks the notice.
String _loginFailureNotice(String provider, Object error, String fallback) {
  final String kind;
  String notice = fallback;
  if (error is SocketException || error is http.ClientException) {
    kind = 'network';
    notice = '서버에 연결하지 못했습니다. API 주소와 네트워크를 확인해주세요.';
  } else if (error is TimeoutException) {
    kind = 'timeout';
    notice = '서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요.';
  } else if (error is ApiException) {
    final status = error.statusCode;
    kind = status == 401 || status == 403
        ? 'auth_rejected status=$status'
        : status >= 500
        ? 'server_error status=$status'
        : 'http status=$status';
  } else if (error is FormatException) {
    kind = 'bad_response';
  } else {
    kind = 'unexpected type=${error.runtimeType}';
  }
  debugPrint(
    '[Auth] $provider step=server_login failed kind=$kind '
    'base_url=${ApiClient().baseUrl}',
  );
  return notice;
}
