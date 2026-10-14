import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

typedef YoutubeBridgeConnector = Future<WebSocket> Function(String url);
typedef YoutubeBridgeScheduler =
    Timer Function(Duration delay, void Function() callback);

/// Receives TV YouTube pause events over the backend WebSocket
/// (`/api/v1/discovery/youtube-events`).
///
/// A failed or dropped connection is retried with exponential backoff
/// (2s, 4s, 8s, 16s, then every 30s) for as long as a screen keeps the
/// bridge started, so a backend restart recovers without reopening the app.
/// [stop] (Home hidden, app in background) ends the retries.
///
/// Log steps: CONNECTED / RECONNECTED / DISCONNECTED / EVENT_RECEIVED.
class YoutubeBridgeService {
  YoutubeBridgeService._({
    YoutubeBridgeConnector? connect,
    YoutubeBridgeScheduler? schedule,
    String? apiBaseUrl,
  }) : _connect = connect ?? WebSocket.connect,
       _schedule = schedule ?? Timer.new,
       _apiBaseUrl = apiBaseUrl ?? _defaultApiBaseUrl;

  @visibleForTesting
  YoutubeBridgeService.forTest({
    required YoutubeBridgeConnector connect,
    YoutubeBridgeScheduler? schedule,
    String apiBaseUrl = 'http://10.0.2.2:8000',
  }) : this._(connect: connect, schedule: schedule, apiBaseUrl: apiBaseUrl);

  static final YoutubeBridgeService instance = YoutubeBridgeService._();

  static const _defaultApiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  /// Reconnects after which the delay stays at the 30-second ceiling.
  static const maxReconnectAttempts = 5;
  static const _maxDelay = Duration(seconds: 30);

  final YoutubeBridgeConnector _connect;
  final YoutubeBridgeScheduler _schedule;
  final String _apiBaseUrl;

  final StreamController<Map<String, dynamic>> _eventController =
      StreamController<Map<String, dynamic>>.broadcast();

  Stream<Map<String, dynamic>> get events => _eventController.stream;

  WebSocket? _socket;
  bool _connecting = false;
  bool _stopped = true;
  int _users = 0;
  int _failures = 0;
  bool _connectedBefore = false;
  Timer? _reconnectTimer;

  bool get isConnected => _socket != null;

  /// Whether a reconnect is waiting to run.
  bool get isReconnectPending => _reconnectTimer?.isActive ?? false;

  /// The WebSocket URL derived from API_BASE_URL.
  Uri get eventsUri {
    final apiUri = Uri.parse(_apiBaseUrl);
    return Uri(
      scheme: apiUri.scheme == 'https' ? 'wss' : 'ws',
      host: apiUri.host,
      port: apiUri.hasPort ? apiUri.port : null,
      path: '/api/v1/discovery/youtube-events',
    );
  }

  /// Delay before the [attempt]-th reconnect (1-based).
  @visibleForTesting
  static Duration reconnectDelay(int attempt) {
    final seconds = 2 << (attempt - 1);
    final delay = Duration(seconds: seconds);
    return delay > _maxDelay ? _maxDelay : delay;
  }

  /// Starts listening. Each [start] must be paired with one [stop]; the
  /// connection closes when the last user stops.
  Future<void> start() async {
    _users++;
    _stopped = false;
    _failures = 0;
    _connectedBefore = false;
    await _open();
  }

  Future<void> _open() async {
    if (_stopped || _socket != null || _connecting) {
      return;
    }

    _connecting = true;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;

    final wsUri = eventsUri;

    try {
      final socket = await _connect(wsUri.toString());

      if (_stopped) {
        await socket.close();
        return;
      }

      socket.pingInterval = const Duration(seconds: 20);
      _socket = socket;
      _failures = 0;

      debugPrint(
        '[YouTube Bridge] ${_connectedBefore ? 'RECONNECTED' : 'CONNECTED'}: $wsUri',
      );
      _connectedBefore = true;

      socket.listen(
        (message) {
          try {
            final decoded = jsonDecode(message as String);
            if (decoded is Map) {
              debugPrint(
                '[YouTube Bridge] EVENT_RECEIVED '
                'event_id=${decoded['event_id']} video_id=${decoded['video_id']} '
                'position_sec=${decoded['position_sec']}',
              );
            }

            if (decoded is Map<String, dynamic>) {
              _eventController.add(decoded);
            } else if (decoded is Map) {
              _eventController.add(
                decoded.map((key, value) => MapEntry(key.toString(), value)),
              );
            }
          } catch (error) {
            debugPrint('[YouTube Bridge] SERVICE parse error: $error');
          }
        },
        onError: (Object error, StackTrace stackTrace) {
          debugPrint('[YouTube Bridge] SERVICE error: $error');
        },
        onDone: () {
          debugPrint(
            '[YouTube Bridge] DISCONNECTED '
            'code=${socket.closeCode} '
            'reason=${socket.closeReason}',
          );

          if (identical(_socket, socket)) {
            _socket = null;
          }

          _scheduleReconnect();
        },
        cancelOnError: false,
      );
    } catch (error) {
      debugPrint('[YouTube Bridge] SERVICE connection failed: $error');

      _scheduleReconnect();
    } finally {
      _connecting = false;
    }
  }

  void _scheduleReconnect() {
    if (_stopped || _socket != null || isReconnectPending) {
      return;
    }

    _failures++;
    final delay = reconnectDelay(
      _failures > maxReconnectAttempts ? maxReconnectAttempts : _failures,
    );
    debugPrint(
      '[YouTube Bridge] SERVICE reconnecting in ${delay.inSeconds} seconds',
    );

    _reconnectTimer = _schedule(delay, () {
      _reconnectTimer = null;
      unawaited(_open());
    });
  }

  /// Releases one [start]. The socket and timer are closed when no screen
  /// uses the bridge any more.
  Future<void> stop() async {
    if (_users > 0) _users--;
    if (_users > 0) return;

    _stopped = true;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;

    final socket = _socket;
    _socket = null;

    if (socket != null) {
      await socket.close(WebSocketStatus.normalClosure, 'service stopped');
    }

    debugPrint('[YouTube Bridge] SERVICE stopped (no events until started again)');
  }
}
