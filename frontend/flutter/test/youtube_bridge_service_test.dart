import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:travel_mate/services/youtube_bridge_service.dart';

class _FakeTimer implements Timer {
  _FakeTimer(this.callback);

  final void Function() callback;
  bool _active = true;

  @override
  bool get isActive => _active;

  @override
  int get tick => 0;

  @override
  void cancel() => _active = false;

  void fire() {
    _active = false;
    callback();
  }
}

void main() {
  test('uses the backend WebSocket path from API_BASE_URL', () {
    final service = YoutubeBridgeService.forTest(
      connect: (_) => throw UnimplementedError(),
    );
    expect(
      service.eventsUri.toString(),
      'ws://10.0.2.2:8000/api/v1/discovery/youtube-events',
    );
  });

  test('reconnect delays back off and stop growing at 30 seconds', () {
    expect(
      [for (var i = 1; i <= 5; i++) YoutubeBridgeService.reconnectDelay(i)],
      const [
        Duration(seconds: 2),
        Duration(seconds: 4),
        Duration(seconds: 8),
        Duration(seconds: 16),
        Duration(seconds: 30),
      ],
    );
  });

  test('a failing server keeps being retried at the 30-second ceiling', () async {
    var calls = 0;
    final delays = <Duration>[];
    _FakeTimer? pending;
    final service = YoutubeBridgeService.forTest(
      connect: (_) async {
        calls++;
        throw const WebSocketException('404');
      },
      schedule: (delay, callback) {
        delays.add(delay);
        return pending = _FakeTimer(callback);
      },
    );

    await service.start();
    for (var i = 0; i < 8; i++) {
      pending!.fire();
      await Future<void>.delayed(Duration.zero);
    }

    expect(calls, 9);
    expect(delays.take(5), [
      for (var i = 1; i <= 5; i++) YoutubeBridgeService.reconnectDelay(i),
    ]);
    expect(delays.skip(5), everyElement(const Duration(seconds: 30)));
    expect(service.isReconnectPending, isTrue); // still trying, no give-up
    await service.stop();
    expect(service.isReconnectPending, isFalse);
  });

  test('stop cancels a pending reconnect', () async {
    _FakeTimer? pending;
    var calls = 0;
    final service = YoutubeBridgeService.forTest(
      connect: (_) async {
        calls++;
        throw const WebSocketException('404');
      },
      schedule: (delay, callback) => pending = _FakeTimer(callback),
    );

    await service.start();
    expect(service.isReconnectPending, isTrue);
    await service.stop();

    expect(service.isReconnectPending, isFalse);
    expect(pending!.isActive, isFalse);
    expect(calls, 1);
  });

  group('with a local WebSocket server', () {
    late HttpServer server;
    late List<WebSocket> serverSockets;
    late Completer<WebSocket> accepted;
    late Completer<int?> clientClosed;

    // The client's connect() completes when it reads the handshake response;
    // the server's upgrade() completes on its own turn of the event loop.
    // Which one runs first depends on the platform (Windows runs the client
    // first), so tests wait for the server side explicitly.
    Future<WebSocket> serverSide() =>
        accepted.future.timeout(const Duration(seconds: 5));

    setUp(() async {
      serverSockets = [];
      accepted = Completer<WebSocket>();
      clientClosed = Completer<int?>();
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      server.listen((request) async {
        if (request.uri.path != '/api/v1/discovery/youtube-events') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }
        final socket = await WebSocketTransformer.upgrade(request);
        // Read client frames so the app's close frame reaches the server.
        socket.listen(
          (_) {},
          onDone: () {
            if (!clientClosed.isCompleted) {
              clientClosed.complete(socket.closeCode);
            }
          },
        );
        serverSockets.add(socket);
        if (!accepted.isCompleted) accepted.complete(socket);
      });
    });

    tearDown(() => server.close(force: true));

    YoutubeBridgeService service({YoutubeBridgeScheduler? schedule}) =>
        YoutubeBridgeService.forTest(
          connect: WebSocket.connect,
          schedule: schedule,
          apiBaseUrl: 'http://127.0.0.1:${server.port}',
        );

    test('delivers a pause event to listeners', () async {
      final bridge = service();
      final event = bridge.events.first;
      await bridge.start();
      expect(bridge.isConnected, isTrue);
      final serverSocket = await serverSide();
      expect(serverSockets.single, same(serverSocket));

      serverSocket.add(
        jsonEncode({
          'event': 'pause',
          'video_id': 'abc123',
          'position_sec': 95,
        }),
      );

      expect(await event.timeout(const Duration(seconds: 5)), {
        'event': 'pause',
        'video_id': 'abc123',
        'position_sec': 95,
      });
      await bridge.stop();
    });

    test('a dropped connection schedules one reconnect', () async {
      final delays = <Duration>[];
      final scheduled = Completer<void>();
      final bridge = service(
        schedule: (delay, callback) {
          delays.add(delay);
          if (!scheduled.isCompleted) scheduled.complete();
          return _FakeTimer(callback);
        },
      );
      await bridge.start();
      final serverSocket = await serverSide();
      expect(serverSockets.single, same(serverSocket));
      await serverSocket.close();

      // The client's onDone schedules the reconnect; wait for that event.
      await scheduled.future.timeout(const Duration(seconds: 5));

      expect(bridge.isConnected, isFalse);
      expect(bridge.isReconnectPending, isTrue);
      expect(delays, [const Duration(seconds: 2)]);
      await bridge.stop();
      expect(bridge.isReconnectPending, isFalse);
    });

    test('closes the socket only when the last screen stops', () async {
      final bridge = service();
      await bridge.start();
      await bridge.start();
      final serverSocket = await serverSide();
      expect(serverSockets.single, same(serverSocket));

      await bridge.stop();
      expect(bridge.isConnected, isTrue);

      await bridge.stop();
      expect(bridge.isConnected, isFalse);
      // The server sees a normal close from the app.
      expect(
        await clientClosed.future.timeout(const Duration(seconds: 5)),
        WebSocketStatus.normalClosure,
      );
    });
  });
}
