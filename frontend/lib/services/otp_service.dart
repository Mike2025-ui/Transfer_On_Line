import 'dart:async';
import 'package:http/http.dart' as http;
import 'dart:convert';

import 'backend_api_service.dart';

/// Models for OTP verification workflow via Aion Messaging
class OtpRequest {
  final int verificationId;
  final String status;
  final DateTime sentAt;

  OtpRequest({
    required this.verificationId,
    this.status = 'sent',
    DateTime? sentAt,
  }) : sentAt = sentAt ?? DateTime.now();

  bool get canResend => DateTime.now().difference(sentAt).inSeconds >= 60;
  int get secondsUntilResend {
    final elapsed = DateTime.now().difference(sentAt).inSeconds;
    return elapsed >= 60 ? 0 : 60 - elapsed;
  }
}

class OtpVerificationResult {
  final bool success;
  final String? error;
  final String? accessToken;
  final String? refreshToken;
  final String? phoneNumber;

  OtpVerificationResult({
    required this.success,
    this.error,
    this.accessToken,
    this.refreshToken,
    this.phoneNumber,
  });
}

/// Aion Messaging OTP Service - Handles SMS OTP workflow
///
/// Documentation: https://aionmessaging.com/api/v1/
/// - POST /verify/start - Send OTP code via SMS
/// - POST /verify/check - Verify the OTP code
///
/// This service manages the complete OTP flow:
/// 1. Request OTP via SMS (requestOtp)
/// 2. Verify the submitted code (verifyOtp)
/// 3. Handle resend requests (requestResend)
/// 4. Manage rate limiting and throttling
class OtpService {
  OtpService({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  // Rate limiting constants
  static const int maxRetries = 3;
  static const int resendDelaySeconds = 60;
  static const int codeExpirySeconds = 600; // 10 minutes

  // Current OTP state
  OtpRequest? _currentRequest;
  int _attemptCount = 0;

  /// Get the current OTP request (if any)
  OtpRequest? get currentRequest => _currentRequest;

  /// Get number of remaining attempts before being rate-limited
  int get remainingAttempts => maxRetries - _attemptCount;

  /// Check if user can request a resend
  bool get canResend => _currentRequest != null && _currentRequest!.canResend;

  /// Seconds until user can resend (0 if can resend now)
  int get secondsUntilResend => _currentRequest?.secondsUntilResend ?? 0;

  /// Request OTP via SMS to the provided phone number
  ///
  /// Phone number formats accepted:
  /// - Local (Côte d'Ivoire): 07XXXXXXXX or 05XXXXXXXX (10 digits)
  /// - International: +225XXXXXXXXXX or +XX...
  ///
  /// Returns OtpRequest with verification_id on success
  /// Throws exception on failure
  Future<OtpRequest> requestOtp(String phoneNumber) async {
    if (phoneNumber.isEmpty) {
      throw Exception('Phone number is required');
    }

    _attemptCount++;

    try {
      final response = await _client
          .post(
            Uri.parse('${BackendApiService.baseUrl}/auth/otp/request/'),
            headers: const {'Content-Type': 'application/json'},
            body: jsonEncode({'phone_number': phoneNumber}),
          )
          .timeout(
            const Duration(seconds: 30),
            onTimeout: () => throw Exception(
                'Request timeout - please check your connection'),
          );

      if (response.statusCode == 429) {
        throw Exception('Too many requests - please wait before trying again');
      }

      if (response.statusCode != 200) {
        final error =
            _extractError(response, 'Unable to send verification code');
        throw Exception(error);
      }

      final json = jsonDecode(response.body) as Map<String, dynamic>;
      final verificationId = (json['verification_id'] as num?)?.toInt();

      if (verificationId == null) {
        throw Exception('Invalid server response - verification_id missing');
      }

      _currentRequest = OtpRequest(verificationId: verificationId);
      _attemptCount = 0; // Reset attempt counter on successful request

      return _currentRequest!;
    } catch (error) {
      throw Exception(error.toString().replaceFirst('Exception: ', ''));
    }
  }

  /// Verify the submitted OTP code
  ///
  /// Parameters:
  /// - code: The 6-digit code received via SMS
  /// - phoneNumber: The phone number the code was sent to
  /// - verificationId: The verification_id from requestOtp response
  ///
  /// Returns OtpVerificationResult with JWT tokens on success
  Future<OtpVerificationResult> verifyOtp(
    String code,
    String phoneNumber,
    int verificationId,
  ) async {
    if (code.isEmpty || code.length < 4) {
      throw Exception('Code must be at least 4 digits');
    }

    if (_attemptCount >= maxRetries) {
      throw Exception('Too many verification attempts - request a new code');
    }

    _attemptCount++;

    try {
      final response = await _client
          .post(
            Uri.parse('${BackendApiService.baseUrl}/auth/otp/verify/'),
            headers: const {'Content-Type': 'application/json'},
            body: jsonEncode({
              'phone_number': phoneNumber,
              'code': code,
              'verification_id': verificationId,
            }),
          )
          .timeout(
            const Duration(seconds: 30),
            onTimeout: () =>
                throw Exception('Verification timeout - please try again'),
          );

      if (response.statusCode == 422) {
        // Validation error - typically invalid/expired code
        throw Exception('Code is invalid or has expired');
      }

      if (response.statusCode != 200) {
        final error = _extractError(response, 'Verification failed');
        throw Exception(error);
      }

      final json = jsonDecode(response.body) as Map<String, dynamic>;

      return OtpVerificationResult(
        success: true,
        accessToken: json['access'] as String?,
        refreshToken: json['refresh'] as String?,
        phoneNumber: json['phone_number'] as String?,
      );
    } catch (error) {
      throw Exception(error.toString().replaceFirst('Exception: ', ''));
    }
  }

  /// Request a new OTP code (resend)
  ///
  /// Respects rate limiting - can only resend after 60 seconds
  /// Returns the new OtpRequest
  Future<OtpRequest> requestResend(String phoneNumber) async {
    if (_currentRequest == null) {
      throw Exception('No active verification - request a new code first');
    }

    if (!canResend) {
      throw Exception(
          'Please wait ${secondsUntilResend} seconds before requesting a new code');
    }

    // Reset and request new code
    _currentRequest = null;
    _attemptCount = 0;
    return requestOtp(phoneNumber);
  }

  /// Reset the current OTP session (e.g., when changing phone number)
  void reset() {
    _currentRequest = null;
    _attemptCount = 0;
  }

  /// Extract error message from HTTP response
  static String _extractError(http.Response response, String fallback) {
    try {
      final decoded = jsonDecode(response.body) as Map<String, dynamic>;
      if (decoded.containsKey('error')) {
        return decoded['error'] as String? ?? fallback;
      }
      if (decoded.containsKey('detail')) {
        return decoded['detail'] as String? ?? fallback;
      }
      return fallback;
    } catch (_) {
      return fallback;
    }
  }

  /// Validate phone number format
  /// Accepts: 07XXXXXXXX (local) or +225XXXXXXXXXX (international)
  static bool isValidPhoneNumber(String phone) {
    final cleaned = phone.replaceAll(RegExp(r'[^\d+]'), '');
    final digitsOnly = cleaned.replaceAll(RegExp(r'\D'), '');

    // Must have at least 8 digits
    if (digitsOnly.length < 8) return false;

    // If starts with +, it's international format
    if (cleaned.startsWith('+')) return true;

    // If 10 digits only (local format for Côte d'Ivoire), it's valid
    if (digitsOnly.length == 10) return true;

    // Otherwise needs country code
    return false;
  }

  /// Format phone number to E.164 format (+225XXXXXXXXXX)
  static String formatPhoneNumber(String raw) {
    final cleaned = raw.replaceAll(RegExp(r'[^\d+]'), '');
    final digitsOnly = cleaned.replaceAll(RegExp(r'\D'), '');

    if (cleaned.startsWith('+')) {
      return cleaned;
    }

    if (digitsOnly.length == 10) {
      return '+225$digitsOnly';
    }

    throw Exception('Invalid phone number format');
  }
}
