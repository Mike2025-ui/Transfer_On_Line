import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/models.dart';

class BackendTransactionResult {
  const BackendTransactionResult({
    required this.reference,
    required this.status,
    required this.checkoutUrl,
    required this.paymentReference,
    required this.paymentStatus,
  });

  final String reference;
  final String status;
  final String checkoutUrl;
  final String paymentReference;
  final String paymentStatus;

  bool get isSuccess => status == 'success';
  bool get isPending => status == 'pending' || paymentStatus == 'pending';

  factory BackendTransactionResult.fromJson(Map<String, dynamic> json) {
    return BackendTransactionResult(
      reference: json['reference'] as String? ?? '',
      status: json['status'] as String? ?? 'pending',
      checkoutUrl: json['checkout_url'] as String? ?? '',
      paymentReference: json['payment_reference'] as String? ?? '',
      paymentStatus: json['payment_status'] as String? ?? 'pending',
    );
  }
}

/// Thrown by [BackendApiService.getTransactionStatus] when the backend has
/// no record of that reference (404) - distinct from a generic network/
/// server error so a poller can stop cleanly instead of retrying forever.
class TransactionNotFoundException implements Exception {}

class TransactionStatusResult {
  const TransactionStatusResult({
    required this.status,
    required this.isSuccess,
    required this.isPending,
    required this.isFailed,
    required this.isCancelled,
  });

  final String status;
  final bool isSuccess;
  final bool isPending;
  final bool isFailed;
  final bool isCancelled;

  factory TransactionStatusResult.fromJson(Map<String, dynamic> json) {
    return TransactionStatusResult(
      status: json['status'] as String? ?? 'pending',
      isSuccess: json['is_success'] as bool? ?? false,
      isPending: json['is_pending'] as bool? ?? true,
      isFailed: json['is_failed'] as bool? ?? false,
      isCancelled: json['is_cancelled'] as bool? ?? false,
    );
  }
}

/// One row of the customer's own purchase history - `GET /transactions/my/`.
/// Same fields as `transaction_payload()` on the backend (apps.core.
/// serializers) - the endpoint is filtered by `request.user`, never by a
/// phone_number/user_id this class could send.
class TransactionSummary {
  const TransactionSummary({
    required this.reference,
    required this.transactionType,
    required this.operator,
    required this.service,
    required this.recipientPhone,
    required this.amount,
    required this.status,
    required this.paymentMethod,
    required this.createdAt,
    required this.updatedAt,
  });

  final String reference;
  final String transactionType;
  final String operator;
  final String service;
  final String recipientPhone;
  final double amount;
  final String status;
  final String? paymentMethod;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  factory TransactionSummary.fromJson(Map<String, dynamic> json) {
    DateTime? parseDate(String? value) =>
        value == null ? null : DateTime.tryParse(value);
    return TransactionSummary(
      reference: json['reference'] as String? ?? '',
      transactionType: json['transaction_type'] as String? ?? '',
      operator: json['operator'] as String? ?? '',
      service: json['service'] as String? ?? '',
      recipientPhone: json['recipient_phone'] as String? ?? '',
      amount: (json['amount'] as num?)?.toDouble() ?? 0,
      status: json['status'] as String? ?? 'pending',
      paymentMethod: json['payment_method'] as String?,
      createdAt: parseDate(json['created_at'] as String?),
      updatedAt: parseDate(json['updated_at'] as String?),
    );
  }
}

/// One row from `GET /notifications/` - always scoped to `request.user` on
/// the backend (apps.core.models.Notification), never to a device/phone.
class NotificationItem {
  const NotificationItem({
    required this.id,
    required this.title,
    required this.message,
    required this.type,
    required this.isRead,
    required this.createdAt,
    this.transactionReference,
  });

  final int id;
  final String title;
  final String message;
  final String type;
  final bool isRead;
  final DateTime? createdAt;
  final String? transactionReference;

  factory NotificationItem.fromJson(Map<String, dynamic> json) {
    return NotificationItem(
      id: (json['id'] as num).toInt(),
      title: json['title'] as String? ?? '',
      message: json['message'] as String? ?? '',
      type: json['type'] as String? ?? '',
      isRead: json['is_read'] as bool? ?? false,
      createdAt: json['created_at'] == null
          ? null
          : DateTime.tryParse(json['created_at'] as String),
      transactionReference: json['transaction_reference'] as String?,
    );
  }
}

class BackendApiService {
  BackendApiService({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  // Provide the backend address at build time with
  // --dart-define=TOL_API_BASE_URL=http://HOST:8000/api.
  static const String baseUrl = String.fromEnvironment(
    'TOL_API_BASE_URL',
    defaultValue: 'http://localhost:8000/api',
  );

  /// Confirmation must come from the backend, never from the checkout URL
  /// having merely opened - see `GET /transactions/{reference}/status/`.
  Future<TransactionStatusResult> getTransactionStatus(String reference,
      {String? accessToken}) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/transactions/$reference/status/'),
      headers: {
        'Accept': 'application/json',
        if (accessToken != null) 'Authorization': 'Bearer $accessToken',
      },
    );
    if (response.statusCode == 404) {
      throw TransactionNotFoundException();
    }
    if (response.statusCode != 200) {
      throw Exception(
          'Impossible de vérifier le statut (${response.statusCode})');
    }
    return TransactionStatusResult.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>);
  }

  /// Catalog reflecting the dashboard's is_active toggle - never a
  /// hardcoded Orange/MTN/Moov list. See `GET /operators/`.
  Future<List<OperatorItem>> getOperators() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/operators/'),
      headers: {'Accept': 'application/json'},
    );
    if (response.statusCode != 200) {
      throw Exception(
          'Impossible de charger les opérateurs (${response.statusCode})');
    }
    final list = jsonDecode(response.body) as List;
    return list
        .map((e) => OperatorItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// See `GET /services/`.
  Future<List<ServiceItem>> getServices() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/services/'),
      headers: {'Accept': 'application/json'},
    );
    if (response.statusCode != 200) {
      throw Exception(
          'Impossible de charger les services (${response.statusCode})');
    }
    final list = jsonDecode(response.body) as List;
    return list
        .map((e) => ServiceItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Business-model audit: montants pour lesquels un admin a configuré un
  /// UssdCode dédié à cet (operator, service) - voir
  /// `GET /operators/{operatorId}/services/{serviceId}/amounts/`. Une liste
  /// vide signifie qu'aucun palier fixe n'est configuré ; la saisie libre
  /// reste valide côté backend (resolve_ussd_code() a toujours son repli
  /// générique).
  Future<List<AmountItem>> getAvailableAmounts(
      int operatorId, int serviceId) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/operators/$operatorId/services/$serviceId/amounts/'),
      headers: {'Accept': 'application/json'},
    );
    if (response.statusCode != 200) {
      throw Exception(
          'Impossible de charger les montants (${response.statusCode})');
    }
    final list = jsonDecode(response.body) as List;
    return list
        .map((e) => AmountItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// operatorId/serviceId are the business-model audit's target contract
  /// (see backend `_resolve_operator`/`_resolve_service` in
  /// apps/devices/views.py, which already prioritises the id over the name
  /// when both are sent). Optional and additive: no existing caller passes
  /// them yet, so every current call keeps sending names exactly as before.
  Future<BackendTransactionResult> createTransaction({
    required String operator,
    required String service,
    required String operation,
    required String phone,
    required int amount,
    int? operatorId,
    int? serviceId,
    String paymentMethod = 'djeko',
    String? accessToken,
    String? idempotencyKey,
  }) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/transactions/execute/'),
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        // Additive only: /transactions/execute/ stays AllowAny, this just
        // lets the backend attribute the transaction to a signed-in user
        // when one exists - it is not, on its own, an access requirement.
        if (accessToken != null) 'Authorization': 'Bearer $accessToken',
        // Business-model audit Phase 5: identifies THIS submission attempt
        // so a retried/duplicated call never creates a second Transaction -
        // see ExecuteTransactionView.post() in apps/devices/views.py.
        if (idempotencyKey != null) 'Idempotency-Key': idempotencyKey,
      },
      body: jsonEncode({
        if (operatorId != null) 'operator_id': operatorId,
        if (serviceId != null) 'service_id': serviceId,
        'operator': operator,
        'service': service,
        'operation': operation,
        'phone': phone,
        'recipient_phone': phone,
        'amount': amount,
        'payment_method': paymentMethod,
      }),
    );

    if (response.statusCode == 200 || response.statusCode == 201) {
      return BackendTransactionResult.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    String detail = 'Backend indisponible (${response.statusCode})';
    try {
      final decoded = jsonDecode(response.body) as Map<String, dynamic>;
      detail = decoded['error'] as String? ?? detail;
    } catch (_) {}
    throw Exception(detail);
  }

  /// Identity architecture (Phase 7): `GET /transactions/my/`, filtered
  /// server-side by the JWT alone - a real access token is required, there
  /// is no anonymous equivalent of "my history".
  Future<List<TransactionSummary>> fetchMyTransactions({
    required String accessToken,
    int page = 1,
  }) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/transactions/my/?page=$page'),
      headers: {
        'Accept': 'application/json',
        'Authorization': 'Bearer $accessToken'
      },
    );
    if (response.statusCode == 401) {
      throw Exception('Session expirée');
    }
    if (response.statusCode != 200) {
      throw Exception(
          'Impossible de charger l\'historique (${response.statusCode})');
    }
    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    final results = decoded['results'] as List? ?? const [];
    return results
        .map((e) => TransactionSummary.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Identity architecture (Phase 8): `GET /notifications/`, filtered
  /// server-side by the JWT alone.
  Future<List<NotificationItem>> fetchNotifications({
    required String accessToken,
    int page = 1,
  }) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/notifications/?page=$page'),
      headers: {
        'Accept': 'application/json',
        'Authorization': 'Bearer $accessToken'
      },
    );
    if (response.statusCode == 401) {
      throw Exception('Session expirée');
    }
    if (response.statusCode != 200) {
      throw Exception(
          'Impossible de charger les notifications (${response.statusCode})');
    }
    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    final results = decoded['results'] as List? ?? const [];
    return results
        .map((e) => NotificationItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<int> fetchUnreadNotificationCount(
      {required String accessToken}) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/notifications/unread-count/'),
      headers: {
        'Accept': 'application/json',
        'Authorization': 'Bearer $accessToken'
      },
    );
    if (response.statusCode != 200) {
      throw Exception(
          'Impossible de charger le compteur (${response.statusCode})');
    }
    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    return (decoded['unread_count'] as num?)?.toInt() ?? 0;
  }

  Future<NotificationItem> markNotificationRead({
    required String accessToken,
    required int notificationId,
  }) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/notifications/$notificationId/read/'),
      headers: {
        'Accept': 'application/json',
        'Authorization': 'Bearer $accessToken'
      },
    );
    if (response.statusCode != 200) {
      throw Exception(
          'Impossible de marquer la notification comme lue (${response.statusCode})');
    }
    return NotificationItem.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>);
  }
}
