import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import 'backend_api_service.dart';

/// Small storage seam so [AuthService] can be unit-tested without touching
/// the real platform secure-storage channel (which has no in-memory fake
/// available in a plain `flutter test` run).
abstract class AuthTokenStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

class SecureAuthTokenStore implements AuthTokenStore {
  const SecureAuthTokenStore([this._storage = const FlutterSecureStorage()]);

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read(String key) => _storage.read(key: key);

  @override
  Future<void> write(String key, String value) =>
      _storage.write(key: key, value: value);

  @override
  Future<void> delete(String key) => _storage.delete(key: key);
}

class AuthSession {
  const AuthSession({
    required this.phoneNumber,
    required this.accessToken,
    required this.refreshToken,
  });

  final String phoneNumber;
  final String accessToken;
  final String refreshToken;
}

/// The phone number is the durable customer identity; the OTP only proves
/// possession of it. A device stays "known" for as long as it holds a
/// refresh token the backend still accepts - OTP is asked again only on a
/// fresh install or once that refresh token itself is rejected, never just
/// because the short-lived access token expired.
class AuthService {
  AuthService({AuthTokenStore? store, http.Client? client})
      : _store = store ?? const SecureAuthTokenStore(),
        _client = client ?? http.Client();

  final AuthTokenStore _store;
  final http.Client _client;

  static const _phoneKey = 'auth_phone_number';
  static const _accessKey = 'auth_access_token';
  static const _refreshKey = 'auth_refresh_token';

  /// The backend (apps.accounts.services.otp_service) delegates code
  /// generation, delivery AND verification to IKODDI (OTP As A Service) -
  /// the response never contains the code, in any build, and there is no
  /// separate identifier to carry between request and verify: the pending
  /// code is looked up server-side by phone_number alone.
  ///
  /// [channel] picks which IKODDI delivery method to use - `'sms'` (the
  /// default) or `'whatsapp'`. Both stay on IKODDI end-to-end; this only
  /// selects the endpoint IKODDI itself sends through.
  Future<void> requestOtp(String phoneNumber, {String channel = 'sms'}) async {
    final response = await _client.post(
      Uri.parse('${BackendApiService.baseUrl}/auth/otp/request/'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({'phone_number': phoneNumber, 'channel': channel}),
    );
    if (response.statusCode != 200) {
      throw Exception(_extractError(response, 'Envoi du code impossible'));
    }
  }

  Future<AuthSession> verifyOtp(String phoneNumber, String code) async {
    final response = await _client.post(
      Uri.parse('${BackendApiService.baseUrl}/auth/otp/verify/'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({'phone_number': phoneNumber, 'code': code}),
    );
    if (response.statusCode != 200) {
      throw Exception(_extractError(response, 'Code invalide ou expiré'));
    }
    final json = jsonDecode(response.body) as Map<String, dynamic>;
    final session = AuthSession(
      phoneNumber: json['phone_number'] as String? ?? phoneNumber,
      accessToken: json['access'] as String,
      refreshToken: json['refresh'] as String,
    );
    await _persist(session);
    return session;
  }

  /// Call once at startup. Returns a session if this device is already
  /// known (valid or refreshable token on file), or null if the phone+OTP
  /// screen must be shown - never based only on the access token's age, and
  /// never just because the network happened to be unavailable (see
  /// _RefreshNetworkError below - a transient network/server problem is not
  /// proof the refresh token was rejected).
  Future<AuthSession?> restoreSession() async {
    final phone = await _store.read(_phoneKey);
    final access = await _store.read(_accessKey);
    final refresh = await _store.read(_refreshKey);
    if (phone == null || access == null || refresh == null) return null;

    if (!_isExpired(access)) {
      return AuthSession(
          phoneNumber: phone, accessToken: access, refreshToken: refresh);
    }

    try {
      final refreshed = await _tryRefresh(phone, refresh);
      if (refreshed != null) return refreshed;
      // The backend explicitly rejected this refresh token (401/403) - it
      // really is invalid, this device is no longer known.
      await _clear();
      return null;
    } on _RefreshNetworkError {
      // Could not even reach the backend to ask (offline, timeout, DNS,
      // 5xx, unreadable response) - keep the device "known" with its
      // still-expired access token rather than forcing a fresh OTP. Any
      // API call made with this stale token will surface its own error,
      // which is the caller's normal error-handling path, not this one's.
      return AuthSession(
          phoneNumber: phone, accessToken: access, refreshToken: refresh);
    }
  }

  Future<String?> currentAccessToken() => _store.read(_accessKey);

  /// The phone number of the currently known device, if any - same source
  /// as [restoreSession], exposed directly for screens (e.g. a profile page)
  /// that only need to display it, not the full session/tokens.
  Future<String?> currentPhoneNumber() => _store.read(_phoneKey);

  /// Explicit sign-out - actually removes the stored session. Not wired to
  /// any screen yet (the only "Déconnexion" button in the app lives on the
  /// currently-unreachable ProfileScreen), but must exist and work so a
  /// real logout is possible once one is wired up.
  Future<void> logout() => _clear();

  /// Distinguishes "the backend was reached and explicitly rejected this
  /// refresh token" (a real 401/403 - _tryRefresh returns null for that)
  /// from "the request never got a trustworthy answer at all" (thrown as
  /// this type) - offline, timeout, DNS failure, or a 5xx/unreadable
  /// response from the server. Only the former means the device is no
  /// longer known.
  Future<AuthSession?> _tryRefresh(
      String phoneNumber, String refreshToken) async {
    http.Response response;
    try {
      response = await _client.post(
        Uri.parse('${BackendApiService.baseUrl}/auth/token/refresh/'),
        headers: const {'Content-Type': 'application/json'},
        body: jsonEncode({'refresh': refreshToken}),
      );
    } catch (_) {
      throw _RefreshNetworkError();
    }

    if (response.statusCode == 401 || response.statusCode == 403) {
      return null; // genuinely rejected - the refresh token is invalid
    }
    if (response.statusCode != 200) {
      // Anything else unexpected (500, 502, 503, ...) is a server-side
      // problem, not evidence the token is invalid.
      throw _RefreshNetworkError();
    }

    try {
      final json = jsonDecode(response.body) as Map<String, dynamic>;
      final newAccess = json['access'] as String?;
      if (newAccess == null) return null;
      final session = AuthSession(
        phoneNumber: phoneNumber,
        accessToken: newAccess,
        // SIMPLE_JWT has ROTATE_REFRESH_TOKENS enabled - a rotated refresh
        // token comes back in the response and must replace the stored one.
        refreshToken: json['refresh'] as String? ?? refreshToken,
      );
      await _persist(session);
      return session;
    } catch (_) {
      // Malformed/unreadable response body - also a server-side problem.
      throw _RefreshNetworkError();
    }
  }

  Future<void> _persist(AuthSession session) async {
    await _store.write(_phoneKey, session.phoneNumber);
    await _store.write(_accessKey, session.accessToken);
    await _store.write(_refreshKey, session.refreshToken);
  }

  Future<void> _clear() async {
    await _store.delete(_phoneKey);
    await _store.delete(_accessKey);
    await _store.delete(_refreshKey);
  }

  static bool _isExpired(String jwt) {
    try {
      final parts = jwt.split('.');
      if (parts.length != 3) return true;
      final normalized = base64Url.normalize(parts[1]);
      final payload = jsonDecode(utf8.decode(base64Url.decode(normalized)))
          as Map<String, dynamic>;
      final exp = payload['exp'];
      if (exp is! int) return true;
      final expiry =
          DateTime.fromMillisecondsSinceEpoch(exp * 1000, isUtc: true);
      // 30s safety margin: a token about to expire mid-request should not
      // be treated as still valid.
      return DateTime.now()
          .toUtc()
          .isAfter(expiry.subtract(const Duration(seconds: 30)));
    } catch (_) {
      return true;
    }
  }

  static String _extractError(http.Response response, String fallback) {
    try {
      final decoded = jsonDecode(response.body) as Map<String, dynamic>;
      return decoded['error'] as String? ?? fallback;
    } catch (_) {
      return fallback;
    }
  }
}

/// Internal to [AuthService._tryRefresh]/[AuthService.restoreSession] - a
/// network or server-side failure while attempting to refresh, never a
/// statement about whether the refresh token itself is valid.
class _RefreshNetworkError implements Exception {}
