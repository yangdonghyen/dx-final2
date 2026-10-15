import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// 향후 서버 API 요청을 한곳에서 관리하기 위한 통신 진입점입니다.
class ApiClient {
  ApiClient({String? baseUrl, http.Client? client})
    : baseUrl =
          baseUrl ??
          const String.fromEnvironment(
            'API_BASE_URL',
            defaultValue: 'http://127.0.0.1:8000',
          ),
      _client = client ?? http.Client();

  /// Ordinary API calls. AI plan calls pass a longer [timeout] themselves.
  static const defaultTimeout = Duration(seconds: 60);

  final String baseUrl;
  final http.Client _client;

  /// Set in main(): trades the stored refresh token for a new access token.
  /// Access tokens last 30 minutes, so without this every request failed
  /// with 401 half an hour into a session (seen while filming the demo).
  static Future<String?> Function()? refreshAccessToken;
  static Future<String?>? _refreshing;

  /// Sends once; on 401 with a token, refreshes it (one shared refresh for
  /// concurrent calls) and sends again with the new token.
  Future<http.Response> _send(
    String? accessToken,
    Future<http.Response> Function(String? token) request,
  ) async {
    final response = await request(accessToken);
    final refresh = refreshAccessToken;
    if (response.statusCode != 401 || accessToken == null || refresh == null) {
      return response;
    }
    final renewed = await (_refreshing ??= refresh().whenComplete(() => _refreshing = null));
    if (renewed == null || renewed == accessToken) return response;
    return request(renewed);
  }

  Future<Map<String, dynamic>> post(
    String path, {
    Map<String, dynamic>? body,
    String? accessToken,
    bool sendBody = true,
    Duration timeout = defaultTimeout,
  }) async {
    final response = await _send(accessToken, (token) => _client.post(
      Uri.parse('$baseUrl$path'),
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        if (token != null) 'Authorization': 'Bearer $token',
      },
      body: sendBody ? jsonEncode(body ?? <String, dynamic>{}) : null,
    ).timeout(timeout));

    return _decode(response);
  }

  Future<Map<String, dynamic>> get(
    String path, {
    String? accessToken,
    Duration timeout = defaultTimeout,
  }) async {
    final response = await _send(accessToken, (token) => _client.get(
      Uri.parse('$baseUrl$path'),
      headers: {
        if (token != null) 'Authorization': 'Bearer $token',
      },
    ).timeout(timeout));

    return _decode(response);
  }

  Future<Map<String, dynamic>> delete(
    String path, {
    String? accessToken,
    Duration timeout = defaultTimeout,
  }) async {
    final response = await _send(accessToken, (token) => _client.delete(
      Uri.parse('$baseUrl$path'),
      headers: {
        if (token != null) 'Authorization': 'Bearer $token',
      },
    ).timeout(timeout));

    return _decode(response);
  }

  Future<Map<String, dynamic>> patch(
    String path, {
    Map<String, dynamic>? body,
    String? accessToken,
    Duration timeout = defaultTimeout,
  }) async {
    final response = await _send(accessToken, (token) => _client.patch(
      Uri.parse('$baseUrl$path'),
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        if (token != null) 'Authorization': 'Bearer $token',
      },
      body: jsonEncode(body ?? <String, dynamic>{}),
    ).timeout(timeout));

    return _decode(response);
  }

  Map<String, dynamic> _decode(http.Response response) {
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(
        response.statusCode,
        decoded is Map<String, dynamic> ? decoded : <String, dynamic>{},
      );
    }

    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('API response must be a JSON object.');
    }

    return decoded;
  }
}

class ApiException implements Exception {
  const ApiException(this.statusCode, this.body);

  final int statusCode;
  final Map<String, dynamic> body;

  @override
  String toString() => 'ApiException($statusCode, $body)';
}
