import 'dart:convert';

import 'package:http/http.dart' as http;

class BackendTransactionResult {
  const BackendTransactionResult({
    required this.reference,
    required this.status,
  });

  final String reference;
  final String status;

  bool get isSuccess => status == 'success' || status == 'pending';

  factory BackendTransactionResult.fromJson(Map<String, dynamic> json) {
    return BackendTransactionResult(
      reference: json['reference'] as String? ?? '',
      status: json['status'] as String? ?? 'pending',
    );
  }
}

class BackendApiService {
  static const String baseUrl = String.fromEnvironment(
    'TOL_API_BASE_URL',
    defaultValue: 'http://192.168.43.98:8000/api',
  );

  Future<BackendTransactionResult> createTransaction({
    required String operator,
    required String service,
    required String operation,
    required String phone,
    required int amount,
    required String paymentMethod,
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
        'payment_method': paymentMethod,
      }),
    );

    if (response.statusCode == 200 || response.statusCode == 201) {
      return BackendTransactionResult.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw Exception('Backend indisponible (${response.statusCode})');
  }
}

