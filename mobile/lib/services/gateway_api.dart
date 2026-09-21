import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'ussd_service.dart' show SimInfo;

class TransactionRequest {
  TransactionRequest({
    required this.type,
    required this.recipientPhone,
    required this.amount,
    this.gatewayUuid,
  });

  final String type;
  final String recipientPhone;
  final double amount;
  final String? gatewayUuid;

  Map<String, dynamic> toJson({String? ussdResponse}) {
    final Map<String, dynamic> payload = {
      'transaction_type': type,
      'recipient_phone': recipientPhone,
      'amount': amount,
      'reference': 'GW-${DateTime.now().millisecondsSinceEpoch}',
      'commission': (amount * 0.01).toStringAsFixed(2),
    };
    if (gatewayUuid != null) {
      payload['gateway_uuid'] = gatewayUuid;
    }
    if (ussdResponse != null) {
      payload['ussd_response'] = ussdResponse;
    }
    return payload;
  }
}

class PendingTransaction {
  PendingTransaction({
    required this.id,
    required this.type,
    required this.recipientPhone,
    required this.amount,
    required this.serverReference,
    this.ussdCode,
    this.simSlot,
    this.operator,
    this.isInteractive = false,
    this.attemptId,
    this.scenarioId,
    this.scenarioVersion,
  });

  final int id;
  final String type;
  final String recipientPhone;
  final double amount;
  final String serverReference;
  final String? ussdCode;
  final int? scenarioId;
  final int? scenarioVersion;
  // Which physical SIM slot (0/1) the Scheduler reserved for this
  // transaction - absent when USE_NEW_TRANSACTION_ENGINE is off or no
  // attempt exists yet, in which case dialing falls back to today's
  // default/no-preference SIM (see SimResolver on the native side).
  final int? simSlot;
  // Phase D audit (Critique): the operator this transaction requires -
  // gateway_task_payload() already sends this unconditionally (it was just
  // never parsed here before). Passed through to the native dial call so
  // SimResolver.matchesExpectedOperator can refuse dialing on a SIM that
  // doesn't actually belong to this operator, instead of trusting the
  // resolved slot blindly. Null is always safe: it skips the check
  // entirely, exactly like an older Gateway build that never sent it.
  final String? operator;
  // Phase D4.1: always present in the backend response (default false) -
  // decides which engine gateway_loop.dart hands this task to (dialUssd vs
  // the interactive session runner). Never true without [attemptId] also
  // set (see gateway_task_payload()'s own coupling of the two).
  final bool isInteractive;
  // Phase D4.1: the real TransactionAttempt.id used by every
  // /transactions/step/ call for this session - never Transaction.id,
  // never generated here, never serverReference. Only present under the
  // new engine with a reserved attempt.
  final int? attemptId;

  factory PendingTransaction.fromJson(Map<String, dynamic> json) {
    return PendingTransaction(
      id: json['id'] as int,
      type: json['transaction_type'] as String? ?? 'subscription',
      recipientPhone: json['recipient_phone'] as String? ?? '',
      amount: (json['amount'] as num?)?.toDouble() ?? 0.0,
      serverReference: json['reference'] as String? ?? '',
      ussdCode: json['ussd_code'] as String?,
      simSlot: (json['sim_slot'] as num?)?.toInt(),
      operator: json['operator'] as String?,
      isInteractive: json['is_interactive'] as bool? ?? false,
      attemptId: (json['attempt_id'] as num?)?.toInt(),
      scenarioId: (json['scenario_id'] as num?)?.toInt(),
      scenarioVersion: (json['scenario_version'] as num?)?.toInt(),
    );
  }

  TransactionRequest toTransactionRequest({String? gatewayUuid}) {
    return TransactionRequest(
      type: type,
      recipientPhone: recipientPhone,
      amount: amount,
      gatewayUuid: gatewayUuid,
    );
  }
}

/// One SMS job from `GET /api/gateway/sms/pending/` (SmsTask on the
/// backend.
/// Unlike transactions, the backend never assigns a sim_slot for these -
/// SMS always dials on the phone's default SIM for now.
class SmsPendingTask {
  SmsPendingTask({
    required this.id,
    required this.phoneNumber,
    required this.message,
    required this.purpose,
  });

  final int id;
  final String phoneNumber;
  final String message;
  final String purpose;

  factory SmsPendingTask.fromJson(Map<String, dynamic> json) {
    return SmsPendingTask(
      id: json['id'] as int,
      phoneNumber: json['phone_number'] as String? ?? '',
      message: json['message'] as String? ?? '',
      purpose: json['purpose'] as String? ?? '',
    );
  }
}

class GatewayStatus {
  GatewayStatus({
    required this.id,
    required this.uuid,
    required this.phoneNumber,
    required this.operatorName,
    required this.heartbeatStatus,
    required this.lastCheckIn,
    required this.isOnline,
  });

  final int id;
  final String uuid;
  final String phoneNumber;
  final String operatorName;
  final String heartbeatStatus;
  final String? lastCheckIn;
  final bool isOnline;

  factory GatewayStatus.fromJson(Map<String, dynamic> json) {
    return GatewayStatus(
      id: json['id'] as int,
      uuid:
          json['device']?['uuid'] as String? ??
          json['uuid'] as String? ??
          'n/a',
      phoneNumber: json['device']?['phone_number'] as String? ?? 'n/a',
      operatorName:
          json['device']?['details']?['operator'] as String? ?? 'Inconnu',
      heartbeatStatus: json['heartbeat_status'] as String? ?? 'inconnu',
      lastCheckIn: json['last_checkin'] as String?,
      isOnline: (json['heartbeat_status'] as String?) == 'online',
    );
  }
}

/// Phase D2 (moteur USSD interactif) - one fresh key per NEW logical event
/// (NEW_FIELD/FINAL_FIELD/RESULT), reused verbatim by the caller if that
/// same HTTP call is retried after a network failure - see
/// LocalQueueRepository's interactive_session table, which is exactly what
/// makes that reuse possible across a retry. RFC 4122 v4 shape via
/// Random.secure() - no new dependency (`uuid` is not in pubspec.yaml, and
/// the backend only needs "sufficiently unique", not a validated UUID
/// library).
String generateIdempotencyKey() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10xx
  String hex(int start, int end) => bytes
      .sublist(start, end)
      .map((b) => b.toRadixString(16).padLeft(2, '0'))
      .join();
  return '${hex(0, 4)}-${hex(4, 6)}-${hex(6, 8)}-${hex(8, 10)}-${hex(10, 16)}';
}

/// Response shape from `POST /transactions/step/` (Phase C, apps.devices.
/// views.TransactionStepView) - fields match exactly what that view returns
/// today, nothing added speculatively: `values` only for action=="INPUT",
/// `status` only for the DONE returned by a RESULT event, `errorCode` only
/// for action=="FAILED". The backend never echoes `operator_message` back -
/// it's only ever sent, never received here.
class TransactionStepResponse {
  const TransactionStepResponse({
    required this.action,
    this.values,
    this.status,
    this.errorCode,
  });

  final String action;
  final List<String>? values;
  final String? status;
  final String? errorCode;

  factory TransactionStepResponse.fromJson(Map<String, dynamic> json) {
    return TransactionStepResponse(
      action: json['action'] as String? ?? '',
      values: (json['values'] as List<dynamic>?)
          ?.map((e) => e.toString())
          .toList(),
      status: json['status'] as String?,
      errorCode: json['error_code'] as String?,
    );
  }
}

/// Thrown by [GatewayApi.sendTransactionStep] for any non-2xx response -
/// deliberately distinct from every other method's plain `Exception`
/// (message-only), so D4 can branch on [statusCode] (401/403/404/409...)
/// instead of parsing a string. `TimeoutException`/`SocketException`/
/// `ClientException` are never wrapped here - they propagate as Dart/http's
/// own standard types, exactly as they already do for every other method in
/// this file.
class TransactionStepException implements Exception {
  const TransactionStepException(this.statusCode, this.errorMessage);

  final int statusCode;
  final String? errorMessage;

  @override
  String toString() => 'TransactionStepException($statusCode, $errorMessage)';
}

class GatewayApi {
  /// [client] is injectable so tests can pass an `http.MockClient` instead
  /// of hitting the network - every real call site keeps using `GatewayApi()`
  /// unchanged, which falls back to a plain `http.Client()`. [gatewaySecret]
  /// is injectable the same way for tests; every real call site instead
  /// falls back to the compile-time `TOL_GATEWAY_SECRET` define baked into
  /// this specific phone's build (see [_defaultGatewaySecret]'s doc).
  GatewayApi({http.Client? client, String? gatewaySecret, String? baseUrl})
    : _client = client ?? http.Client(),
      _gatewaySecret = gatewaySecret,
      _baseUrl = baseUrl;

  final http.Client _client;
  final String? _gatewaySecret;
  final String? _baseUrl;

  static const String defaultProductionUrl =
      'https://transfert-online.site/api';

  // Provide the backend address at build time with
  // --dart-define=TOL_API_BASE_URL=https://transfert-online.site/api.
  static const String baseUrl = String.fromEnvironment(
    'TOL_API_BASE_URL',
    defaultValue: defaultProductionUrl,
  );

  /// Business-model audit Phase 7 (Gateway security): each physical Gateway
  /// phone is enrolled once via the Django admin (see
  /// apps/core/admin.py::GatewayAdmin's "Générer un nouveau secret" action,
  /// which shows the plaintext exactly once) and that secret is then baked
  /// into THIS phone's own build via --dart-define=TOL_GATEWAY_SECRET=...,
  /// exactly like TOL_API_BASE_URL above - no new screen, no manual entry
  /// UI needed. Empty by default (no define passed) so any build/test that
  /// doesn't set it behaves exactly as before this existed: no header sent,
  /// and the backend rejects it as unauthenticated (see
  /// apps.devices.views._authenticate_gateway) rather than silently
  /// auto-provisioning a Gateway the way it used to.
  static const String _defaultGatewaySecret = String.fromEnvironment(
    'TOL_GATEWAY_SECRET',
    defaultValue: '',
  );

  static const String prefBaseUrlKey = 'tol_api_base_url';
  static const String prefSecretKey = 'tol_gateway_secret';

  static String? _cachedBaseUrl;
  static String? _cachedSecret;

  /// Vérifie si une URL de base d'API est syntaxiquement et sémantiquement valide.
  /// Rejette les valeurs nulles, vides, sans schéma HTTP/HTTPS ou contenant des
  /// segments incorrects comme `/api/gateway`, `/gateway/api`, `/api/api`, `/gateway`.
  static bool isValidBaseUrl(String? input) {
    if (input == null) return false;
    final trimmed = input.trim();
    if (trimmed.isEmpty) return false;

    final uri = Uri.tryParse(trimmed);
    if (uri == null ||
        !uri.hasScheme ||
        (uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.isEmpty) {
      return false;
    }

    final lower = trimmed.toLowerCase();
    if (lower.contains('/api/gateway') ||
        lower.contains('/gateway/api') ||
        lower.contains('/api/api') ||
        lower.contains('/gateway')) {
      return false;
    }

    return true;
  }

  /// Normalise l'URL d'API de base :
  /// - Supprime les slashes finals : `https://transfert-online.site/api/` -> `https://transfert-online.site/api`
  /// - Ajoute `/api` si manquant : `https://transfert-online.site` -> `https://transfert-online.site/api`
  /// - Si l'URL fournie est invalide (ex: contient `/api/gateway/api` ou `/api/api`), elle est rejetée
  ///   et remplacée par l'URL de production par défaut [baseUrl].
  static String formatBaseUrl(String input) {
    if (!isValidBaseUrl(input)) {
      return baseUrl;
    }
    final clean = input.trim().replaceAll(RegExp(r'/+$'), '');
    return clean.endsWith('/api') ? clean : '$clean/api';
  }

  static Future<void> initPreferences() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final savedUrl = prefs.getString(prefBaseUrlKey);
      if (savedUrl != null && savedUrl.trim().isNotEmpty) {
        if (!isValidBaseUrl(savedUrl)) {
          // Migration automatique de l'ancienne valeur invalide
          await prefs.setString(prefBaseUrlKey, baseUrl);
          _cachedBaseUrl = baseUrl;
        } else {
          final formatted = formatBaseUrl(savedUrl);
          if (formatted != savedUrl) {
            await prefs.setString(prefBaseUrlKey, formatted);
          }
          _cachedBaseUrl = formatted;
        }
      } else {
        _cachedBaseUrl = baseUrl;
      }
      _cachedSecret = prefs.getString(prefSecretKey);
    } catch (_) {
      // Ignored in test environments
    }
  }

  static Future<void> saveSettings({String? baseUrl, String? secret}) async {
    final prefs = await SharedPreferences.getInstance();
    if (baseUrl != null && baseUrl.trim().isNotEmpty) {
      final formatted = formatBaseUrl(baseUrl);
      await prefs.setString(prefBaseUrlKey, formatted);
      _cachedBaseUrl = formatted;
    }
    if (secret != null) {
      final cleanSecret = secret.trim();
      await prefs.setString(prefSecretKey, cleanSecret);
      _cachedSecret = cleanSecret;
    }
  }

  static Future<String> getConfiguredBaseUrl() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getString(prefBaseUrlKey);
      if (saved != null && saved.trim().isNotEmpty) {
        if (!isValidBaseUrl(saved)) {
          // Migration automatique : rejeter et remplacer par l'URL de production
          await prefs.setString(prefBaseUrlKey, baseUrl);
          _cachedBaseUrl = baseUrl;
          return baseUrl;
        }
        final formatted = formatBaseUrl(saved);
        if (formatted != saved) {
          await prefs.setString(prefBaseUrlKey, formatted);
        }
        _cachedBaseUrl = formatted;
        return formatted;
      }
    } catch (_) {}
    if (_cachedBaseUrl != null &&
        _cachedBaseUrl!.isNotEmpty &&
        isValidBaseUrl(_cachedBaseUrl)) {
      return _cachedBaseUrl!;
    }
    _cachedBaseUrl = baseUrl;
    return baseUrl;
  }

  static Future<String> getConfiguredSecret() async {
    if (_cachedSecret != null && _cachedSecret!.isNotEmpty) {
      return _cachedSecret!;
    }
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getString(prefSecretKey);
      if (saved != null && saved.isNotEmpty) {
        _cachedSecret = saved;
        return saved;
      }
    } catch (_) {}
    return _defaultGatewaySecret;
  }

  @visibleForTesting
  static void resetCacheForTesting() {
    _cachedBaseUrl = null;
    _cachedSecret = null;
  }

  String get effectiveBaseUrl {
    final customUrl = _baseUrl;
    if (customUrl != null && customUrl.isNotEmpty) {
      return isValidBaseUrl(customUrl) ? formatBaseUrl(customUrl) : baseUrl;
    }
    final cached = _cachedBaseUrl;
    if (cached != null && cached.isNotEmpty) {
      return isValidBaseUrl(cached) ? formatBaseUrl(cached) : baseUrl;
    }
    return baseUrl;
  }

  String get effectiveSecret {
    final customSecret = _gatewaySecret;
    if (customSecret != null) {
      return customSecret;
    }
    final cached = _cachedSecret;
    if (cached != null) {
      return cached;
    }
    return _defaultGatewaySecret;
  }

  Map<String, String> get _authHeaders {
    final secret = effectiveSecret;
    return secret.isEmpty ? const {} : {'X-Gateway-Secret': secret};
  }

  /// Stabilisation RC1 (priorité moyenne n°8): the `http` package applies no
  /// timeout of its own - without one, a single stalled connection (dead
  /// Wi-Fi, backend hang) would leave a request awaiting forever, keeping
  /// the autonomous loop's reentrancy guard (see gateway_service_entrypoint's
  /// `ticking`) stuck "busy" indefinitely instead of retrying on the next
  /// tick. Comfortably under the 20s tick interval so a timeout resolves
  /// before the next tick would even fire.
  static const _requestTimeout = Duration(seconds: 15);

  /// Tests connection to the backend using either provided credentials or the current configured ones.
  Future<Map<String, dynamic>> testConnection({
    String? baseUrl,
    String? secret,
  }) async {
    final targetUrl = baseUrl != null && baseUrl.trim().isNotEmpty
        ? formatBaseUrl(baseUrl)
        : effectiveBaseUrl;
    final targetSecret = secret != null ? secret.trim() : effectiveSecret;
    final headers = <String, String>{
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      if (targetSecret.isNotEmpty) 'X-Gateway-Secret': targetSecret,
    };

    try {
      // 1. Test basic reachability via /gateways/
      final listRes = await _client
          .get(
            Uri.parse('$targetUrl/gateways/'),
            headers: {'Accept': 'application/json'},
          )
          .timeout(_requestTimeout);

      if (listRes.statusCode != 200) {
        return {
          'success': false,
          'message':
              'Serveur inaccessible ou URL incorrecte (HTTP ${listRes.statusCode}).',
        };
      }

      // 2. Test authentication via /gateways/heartbeat/
      if (targetSecret.isEmpty) {
        return {
          'success': false,
          'message':
              'Serveur accessible, mais aucun Secret Gateway n\'est configuré.',
        };
      }

      final authRes = await _client
          .post(
            Uri.parse('$targetUrl/gateways/heartbeat/'),
            headers: headers,
            body: jsonEncode({
              'status': 'online',
              'gateway_uuid': 'ping_test',
              'details': {'ping': true},
            }),
          )
          .timeout(_requestTimeout);

      if (authRes.statusCode == 200 || authRes.statusCode == 201) {
        final data = jsonDecode(authRes.body);
        final name = data['name'] ?? 'Gateway';
        return {
          'success': true,
          'message': 'Connexion réussie ! Identifié comme : $name',
        };
      } else if (authRes.statusCode == 401) {
        return {
          'success': false,
          'message':
              'Secret Gateway invalide ou non reconnu par le serveur (401).',
        };
      } else if (authRes.statusCode == 403) {
        return {
          'success': false,
          'message': 'Cette Gateway est désactivée sur le serveur (403).',
        };
      } else {
        return {
          'success': false,
          'message': 'Erreur serveur (HTTP ${authRes.statusCode}).',
        };
      }
    } catch (e) {
      return {
        'success': false,
        'message': 'Erreur réseau : impossible de contacter le serveur ($e)',
      };
    }
  }

  Future<GatewayStatus> fetchGatewayStatus({String? deviceUuid}) async {
    final response = await _client
        .get(
          Uri.parse('$effectiveBaseUrl/gateways/'),
          headers: {'Accept': 'application/json'},
        )
        .timeout(_requestTimeout);

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data is List && data.isNotEmpty) {
        if (deviceUuid != null && deviceUuid.isNotEmpty) {
          final match = data.cast<Map<String, dynamic>>().firstWhere((g) {
            final gUuid =
                g['uuid'] as String? ?? g['device']?['uuid'] as String?;
            return gUuid == deviceUuid;
          }, orElse: () => data.first as Map<String, dynamic>);
          return GatewayStatus.fromJson(match);
        }
        return GatewayStatus.fromJson(data.first as Map<String, dynamic>);
      }
      if (data is Map<String, dynamic>) {
        return GatewayStatus.fromJson(data);
      }
      throw Exception('Aucune gateway enregistrée');
    }
    throw Exception('Échec du chargement du statut (${response.statusCode})');
  }

  Future<GatewayStatus> sendHeartbeat(
    int? gatewayId,
    DeviceSnapshot device,
  ) async {
    final suffix = gatewayId == null
        ? 'gateways/heartbeat/'
        : 'gateways/$gatewayId/heartbeat/';
    final response = await _client
        .post(
          Uri.parse('$effectiveBaseUrl/$suffix'),
          headers: {'Content-Type': 'application/json', ..._authHeaders},
          body: jsonEncode({
            'status': 'online',
            'gateway_uuid': device.uuid,
            'details': {
              'uuid': device.uuid,
              'phone_number': device.phoneNumber,
              'operator': device.operatorName,
              'device_model': device.deviceModel,
              'os_version': device.osVersion,
              ...device.toTelemetryJson(),
            },
          }),
        )
        .timeout(_requestTimeout);

    if (response.statusCode == 200 || response.statusCode == 201) {
      return GatewayStatus.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw Exception('Échec du heartbeat (${response.statusCode})');
  }

  Future<Map<String, dynamic>> executeTransaction(
    TransactionRequest request, {
    String? ussdResponse,
  }) async {
    final response = await _client
        .post(
          Uri.parse('$effectiveBaseUrl/transactions/execute/'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(request.toJson(ussdResponse: ussdResponse)),
        )
        .timeout(_requestTimeout);

    if (response.statusCode == 200 || response.statusCode == 201) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Échec de l’exécution (${response.statusCode})');
  }

  Future<List<PendingTransaction>> fetchPendingTransactions(
    String gatewayUuid,
  ) async {
    final response = await _client
        .get(
          Uri.parse(
            '$effectiveBaseUrl/transactions/pending/?gateway_uuid=$gatewayUuid',
          ),
          headers: {'Accept': 'application/json', ..._authHeaders},
        )
        .timeout(_requestTimeout);

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data is List) {
        return data
            .map(
              (item) =>
                  PendingTransaction.fromJson(item as Map<String, dynamic>),
            )
            .toList();
      }
      throw Exception('Réponse inattendue pour les transactions en attente');
    }
    throw Exception(
      'Échec du chargement des transactions (${response.statusCode})',
    );
  }

  Future<List<SmsPendingTask>> fetchSmsPending() async {
    final response = await _client
        .get(
          Uri.parse('$effectiveBaseUrl/sms/pending/'),
          headers: {'Accept': 'application/json', ..._authHeaders},
        )
        .timeout(_requestTimeout);
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data is List) {
        return data
            .map(
              (item) => SmsPendingTask.fromJson(item as Map<String, dynamic>),
            )
            .toList();
      }
      throw Exception('Réponse inattendue pour les SMS en attente');
    }
    throw Exception('Échec du chargement des SMS (${response.statusCode})');
  }

  Future<void> reportSmsResult({
    required int id,
    required bool success,
    String? gatewayUuid,
  }) async {
    final response = await _client
        .post(
          Uri.parse('$effectiveBaseUrl/sms/result/'),
          headers: {'Content-Type': 'application/json', ..._authHeaders},
          body: jsonEncode({
            'id': id,
            'success': success,
            'gateway_uuid': ?gatewayUuid,
          }),
        )
        .timeout(_requestTimeout);
    if (response.statusCode != 200 && response.statusCode != 201) {
      throw Exception(
        'Échec de mise à jour du résultat SMS (${response.statusCode})',
      );
    }
  }

  Future<void> reportTransactionResult({
    required String reference,
    required bool success,
    required String result,
  }) async {
    final response = await _client
        .post(
          Uri.parse('$effectiveBaseUrl/transactions/result/'),
          headers: {'Content-Type': 'application/json', ..._authHeaders},
          body: jsonEncode({
            'transaction_reference': reference,
            'success': success,
            'result': result,
          }),
        )
        .timeout(_requestTimeout);

    if (response.statusCode != 200 && response.statusCode != 201) {
      throw Exception(
        'Échec de mise à jour du résultat (${response.statusCode})',
      );
    }
  }

  /// Phase D2 (moteur USSD interactif) - the single request shape for
  /// NEW_FIELD/FINAL_FIELD/RESULT (see TransactionStepView on the backend).
  /// [idempotencyKey] must be freshly generated by the caller for a NEW
  /// event and reused verbatim for a retry of the SAME event - this method
  /// never generates one itself, exactly so that discipline lives with the
  /// caller holding the interactive_session row (LocalQueueRepository), not
  /// buried here where a retry could accidentally mint a new key.
  Future<TransactionStepResponse> sendTransactionStep({
    required String transactionReference,
    required int attemptId,
    required String event,
    required String idempotencyKey,
    int? fieldCount,
    String? status,
    String? operatorMessage,
    String? errorCode,
  }) async {
    final response = await _client
        .post(
          Uri.parse('$effectiveBaseUrl/transactions/step/'),
          headers: {
            'Content-Type': 'application/json',
            'Idempotency-Key': idempotencyKey,
            ..._authHeaders,
          },
          body: jsonEncode({
            'transaction_reference': transactionReference,
            'attempt_id': attemptId,
            'event': event,
            'field_count': ?fieldCount,
            'status': ?status,
            'operator_message': ?operatorMessage,
            'error_code': ?errorCode,
          }),
        )
        .timeout(_requestTimeout);

    if (response.statusCode != 200) {
      String? errorMessage;
      try {
        final decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) {
          errorMessage = decoded['error'] as String?;
        }
      } catch (_) {
        // Non-JSON error body - errorMessage stays null, statusCode alone
        // is still meaningful to the caller.
      }
      throw TransactionStepException(response.statusCode, errorMessage);
    }
    return TransactionStepResponse.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
    );
  }

  /// Architecture Hybride Edge : Récupère les scénarios versionnés depuis le Backend Django
  /// (GET /api/scenarios/sync/).
  Future<String> fetchScenariosRaw() async {
    final uri = Uri.parse('$effectiveBaseUrl/scenarios/sync/');
    final headers = <String, String>{
      'Accept': 'application/json',
      ..._authHeaders,
    };

    final response = await _client
        .get(uri, headers: headers)
        .timeout(const Duration(seconds: 15));

    if (response.statusCode != 200) {
      throw Exception(
        'Échec synchronisation scénarios : HTTP ${response.statusCode}',
      );
    }
    return response.body;
  }
}

class DeviceSnapshot {
  const DeviceSnapshot({
    required this.uuid,
    required this.operatorName,
    required this.phoneNumber,
    required this.deviceModel,
    required this.osVersion,
    this.appVersion,
    this.batteryLevel,
    this.temperature,
    this.networkType,
    this.signalStrength,
    this.ipAddress,
    this.ramAvailableMb,
    this.storageAvailableMb,
    this.isBusy,
    this.currentTaskCount,
    this.sims = const [],
  });

  final String uuid;
  final String operatorName;
  final String phoneNumber;
  final String deviceModel;
  final String osVersion;
  final String? appVersion;
  final int? batteryLevel;
  final double? temperature;
  final String? networkType;
  final int? signalStrength;
  final String? ipAddress;
  final int? ramAvailableMb;
  final int? storageAvailableMb;
  final bool? isBusy;
  final int? currentTaskCount;
  final List<SimInfo> sims;

  /// Keys match GatewayManager._HEARTBEAT_TELEMETRY_FIELDS /
  /// _apply_heartbeat_sims exactly. Only present when known, so an older
  /// backend (or a permission-denied device) never sends a spurious null
  /// that would fight with a value it already has - the server-side
  /// contract treats a present key as authoritative, an absent one as
  /// "leave untouched".
  Map<String, dynamic> toTelemetryJson() {
    return {
      if (appVersion != null) 'app_version': appVersion,
      if (batteryLevel != null) 'battery_level': batteryLevel,
      if (temperature != null) 'temperature': temperature,
      if (networkType != null) 'network_type': networkType,
      if (signalStrength != null) 'signal_strength': signalStrength,
      if (ipAddress != null) 'ip_address': ipAddress,
      if (ramAvailableMb != null) 'ram_available_mb': ramAvailableMb,
      if (storageAvailableMb != null)
        'storage_available_mb': storageAvailableMb,
      if (isBusy != null) 'is_busy': isBusy,
      if (currentTaskCount != null) 'current_task_count': currentTaskCount,
      if (sims.isNotEmpty) 'sims': sims.map((s) => s.toJson()).toList(),
    };
  }
}
