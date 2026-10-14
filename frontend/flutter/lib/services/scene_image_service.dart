import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import '../data/api/api_client.dart';
import 'auth_service.dart';

/// Result of POST /api/v1/discovery/scene-image with analyze=true.
///
/// [verified] is true only when Kakao confirmed the AI's guess as a real
/// place; then [address] and the coordinates come from Kakao.
class SceneRecognitionResult {
  const SceneRecognitionResult({
    required this.recognized,
    required this.verified,
    this.placeName,
    this.address,
    this.areaLabel,
    this.latitude,
    this.longitude,
    this.otherCandidates = const [],
  });

  final bool recognized;
  final bool verified;
  final String? placeName;
  final String? address;

  /// City/region the AI named, used when Kakao could not confirm the place.
  final String? areaLabel;
  final double? latitude;
  final double? longitude;
  final List<String> otherCandidates;

  factory SceneRecognitionResult.fromJson(Map<String, dynamic> json) {
    final verifiedPlace = json['verified_place'];
    final primary = json['primary_candidate'];
    final candidates = json['candidates'];
    final verified =
        json['place_verified'] == true && verifiedPlace is Map<String, dynamic>;
    final primaryName = primary is Map<String, dynamic>
        ? primary['place_name']?.toString()
        : null;
    final area = primary is Map<String, dynamic>
        ? [primary['region'], primary['city']]
              .whereType<String>()
              .where((value) => value.trim().isNotEmpty)
              .toSet()
              .join(' ')
        : '';
    final placeName = verified
        ? verifiedPlace['place_name']?.toString()
        : primaryName;

    return SceneRecognitionResult(
      recognized: json['recognized'] == true && placeName != null,
      verified: verified,
      placeName: placeName,
      address: verified
          ? (verifiedPlace['road_address'] ?? verifiedPlace['address'])
                ?.toString()
          : null,
      areaLabel: area.isEmpty ? null : area,
      latitude: verified
          ? (verifiedPlace['latitude'] as num?)?.toDouble()
          : null,
      longitude: verified
          ? (verifiedPlace['longitude'] as num?)?.toDouble()
          : null,
      otherCandidates: candidates is List
          ? candidates
                .whereType<Map<String, dynamic>>()
                .map((row) => row['place_name']?.toString() ?? '')
                .where((name) => name.isNotEmpty && name != primaryName)
                .toList()
          : const [],
    );
  }
}

class SceneImageService {
  SceneImageService({String? baseUrl, http.Client? client})
    : _baseUrl = baseUrl ?? ApiClient().baseUrl,
      _client = client ?? http.Client();

  final String _baseUrl;
  final http.Client _client;

  /// Sends the photo to the server and returns the recognized place.
  Future<SceneRecognitionResult> analyze(String imagePath) async {
    final accessToken = AuthSession.accessToken;
    if (accessToken == null || accessToken.isEmpty) {
      throw StateError('Login is required.');
    }

    final request =
        http.MultipartRequest(
            'POST',
            Uri.parse('$_baseUrl/api/v1/discovery/scene-image'),
          )
          ..headers['Authorization'] = 'Bearer $accessToken'
          ..fields['analyze'] = 'true'
          ..files.add(
            await http.MultipartFile.fromPath(
              'file',
              imagePath,
              contentType: _contentType(imagePath),
            ),
          );

    final response = await http.Response.fromStream(await _client.send(request));
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    final body = decoded is Map<String, dynamic>
        ? decoded
        : <String, dynamic>{};
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, body);
    }
    return SceneRecognitionResult.fromJson(body);
  }

  static MediaType _contentType(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.png')) return MediaType('image', 'png');
    if (lower.endsWith('.webp')) return MediaType('image', 'webp');
    return MediaType('image', 'jpeg');
  }
}
