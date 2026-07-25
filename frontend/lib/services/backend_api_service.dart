import 'dart:convert';

import 'package:http/http.dart' as http;

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

class BackendApiService {
  static const String baseUrl = String.fromEnvironment(
    'TOL_API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000/api',
  );

  Future<BackendTransactionResult> createTransaction({
    required String operator,
    required String service,
    required String operation,
    required String phone,
    required int amount,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/transactions/execute/'),
      headers: const {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
      body: jsonEncode({
        'operator': operator,
        'service': service,
        'operation': operation,
        'phone': phone,
        'recipient_phone': phone,
        'amount': amount,
        'payment_method': 'cinetpay',
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
}
