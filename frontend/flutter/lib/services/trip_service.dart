import '../data/api/api_client.dart';
import 'auth_service.dart';

class TripCreateResult {
  const TripCreateResult({required this.tripId, required this.status});

  final int tripId;
  final String status;

  factory TripCreateResult.fromJson(Map<String, dynamic> json) {
    return TripCreateResult(
      tripId: (json['trip_id'] as num).toInt(),
      status: json['status']?.toString() ?? '',
    );
  }
}

class TripListItem {
  const TripListItem({
    required this.tripId,
    required this.status,
    this.title,
    this.departure,
    this.destination,
    this.startDate,
    this.endDate,
  });

  final int tripId;
  final String? title;
  final String? departure;
  final String? destination;
  final DateTime? startDate;
  final DateTime? endDate;
  final String status;

  factory TripListItem.fromJson(Map<String, dynamic> json) {
    return TripListItem(
      tripId: (json['trip_id'] as num).toInt(),
      title: json['title']?.toString(),
      departure: json['departure']?.toString(),
      destination: json['destination']?.toString(),
      startDate: _parseDate(json['start_date']),
      endDate: _parseDate(json['end_date']),
      status: json['status']?.toString() ?? '',
    );
  }

  static DateTime? _parseDate(dynamic value) {
    final text = value?.toString();

    if (text == null || text.isEmpty) {
      return null;
    }

    return DateTime.tryParse(text);
  }
}

/// A companion row saved in trip_companions for one trip.
class TripCompanionSummary {
  const TripCompanionSummary({
    required this.name,
    required this.relation,
    required this.joinedByInvite,
  });

  final String name;
  final String relation;
  final bool joinedByInvite;

  factory TripCompanionSummary.fromJson(Map<String, dynamic> json) {
    return TripCompanionSummary(
      name: json['name']?.toString() ?? '',
      relation: json['relation']?.toString() ?? '',
      joinedByInvite: json['joined_by_invite'] == true,
    );
  }
}

/// A view-only or invite link created by the backend for one trip.
class TripShareLink {
  const TripShareLink({required this.url, this.expiresAt});

  final String url;
  final DateTime? expiresAt;

  factory TripShareLink.fromJson(Map<String, dynamic> json) {
    return TripShareLink(
      url: json['url'] as String,
      expiresAt: TripListItem._parseDate(json['expires_at']),
    );
  }
}

/// What an invite or view link shows: GET /api/v1/shared-trips/{token}.
class SharedTrip {
  const SharedTrip({
    required this.isInvite,
    required this.companions,
    required this.selectedPlaces,
    this.title,
    this.destination,
    this.startDate,
    this.endDate,
    this.ownerNickname,
  });

  final bool isInvite;
  final String? title;
  final String? destination;
  final DateTime? startDate;
  final DateTime? endDate;
  final String? ownerNickname;
  final List<String> companions;
  final List<String> selectedPlaces;

  factory SharedTrip.fromJson(Map<String, dynamic> json) {
    final companions = json['companions'];
    final places = json['selected_places'];

    return SharedTrip(
      isInvite: json['link_type'] == 'INVITE',
      title: json['title']?.toString(),
      destination: json['destination']?.toString(),
      startDate: TripListItem._parseDate(json['start_date']),
      endDate: TripListItem._parseDate(json['end_date']),
      ownerNickname: json['owner_nickname']?.toString(),
      companions: companions is List
          ? companions
                .whereType<Map<String, dynamic>>()
                .map((row) => row['name']?.toString() ?? '')
                .where((name) => name.isNotEmpty)
                .toList()
          : const [],
      selectedPlaces: places is List
          ? places.map((name) => name.toString()).toList()
          : const [],
    );
  }
}

class TripService {
  TripService({ApiClient? apiClient}) : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;

  String get _accessToken {
    final token = AuthSession.accessToken;

    if (token == null || token.isEmpty) {
      throw StateError('Login is required.');
    }

    return token;
  }

  Future<TripCreateResult> create({
    DateTime? startDate,
    DateTime? endDate,
    String? destination,
    String? transportMode,
    List<String>? interestCodes,
    String? travelStyle,
  }) async {
    final body = <String, dynamic>{};

    if (startDate != null) {
      body['start_date'] = _formatDate(startDate);
    }

    if (endDate != null) {
      body['end_date'] = _formatDate(endDate);
    }

    final normalizedDestination = destination?.trim();

    if (normalizedDestination != null && normalizedDestination.isNotEmpty) {
      body['destination'] = normalizedDestination;
    }

    if (transportMode != null) {
      body['transport_mode'] = transportMode;
    }

    if (interestCodes != null && interestCodes.isNotEmpty) {
      body['interest_codes'] = interestCodes;
    }

    if (travelStyle != null) {
      body['trip_preferences'] = {'travel_style': travelStyle};
    }

    final response = await _apiClient.post(
      '/api/v1/trips',
      accessToken: _accessToken,
      body: body,
    );

    return TripCreateResult.fromJson(response);
  }

  /// DELETE /api/v1/trips/{id}: the server archives the trip, so it leaves
  /// every trip list; its data is kept, not erased.
  Future<void> discard(int tripId) async {
    await _apiClient.delete('/api/v1/trips/$tripId', accessToken: _accessToken);
  }

  /// Representative photo of a region, or null when none was found.
  Future<String?> destinationImage(String destination) async {
    final response = await _apiClient.get(
      '/api/v1/destination-image?destination=${Uri.encodeQueryComponent(destination)}',
      accessToken: _accessToken,
    );
    final url = response['image_url'];
    return url is String && url.isNotEmpty ? url : null;
  }

  Future<List<TripListItem>> list() async {
    final response = await _apiClient.get(
      '/api/v1/trips',
      accessToken: _accessToken,
    );

    final trips = response['trips'];

    if (trips is! List) {
      throw const FormatException(
        'trips response does not contain a trips list.',
      );
    }

    return trips
        .whereType<Map<String, dynamic>>()
        .map(TripListItem.fromJson)
        .toList();
  }

  Future<List<TripCompanionSummary>> companions(int tripId) async {
    final response = await _apiClient.get(
      '/api/v1/trips/$tripId',
      accessToken: _accessToken,
    );

    final companions = response['companions'];

    if (companions is! List) {
      throw const FormatException(
        'trip response does not contain a companions list.',
      );
    }

    return companions
        .whereType<Map<String, dynamic>>()
        .map(TripCompanionSummary.fromJson)
        .toList();
  }

  /// [invite] true creates a 7-day invite link, false a view-only link.
  Future<TripShareLink> createShareLink(
    int tripId, {
    required bool invite,
  }) async {
    final response = await _apiClient.post(
      '/api/v1/trips/$tripId/share-links',
      accessToken: _accessToken,
      body: {'link_type': invite ? 'INVITE' : 'VIEW'},
    );

    return TripShareLink.fromJson(response);
  }

  /// Public: no login needed to see what the link shares.
  Future<SharedTrip> sharedTrip(String token) async {
    final response = await _apiClient.get(
      '/api/v1/shared-trips/${Uri.encodeComponent(token)}',
    );

    return SharedTrip.fromJson(response);
  }

  /// Joins the trip as a companion. Returns true when already joined.
  Future<bool> joinSharedTrip(String token) async {
    final response = await _apiClient.post(
      '/api/v1/shared-trips/${Uri.encodeComponent(token)}/join',
      accessToken: _accessToken,
    );

    return response['already_joined'] == true;
  }

  static String _formatDate(DateTime date) {
    final year = date.year.toString().padLeft(4, '0');
    final month = date.month.toString().padLeft(2, '0');
    final day = date.day.toString().padLeft(2, '0');

    return '$year-$month-$day';
  }
}
