import 'dart:convert';

import 'package:http/http.dart' as http;

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
  });

  final int id;
  final String type;
  final String recipientPhone;
  final double amount;
  final String serverReference;
  final String? ussdCode;

  factory PendingTransaction.fromJson(Map<String, dynamic> json) {
    return PendingTransaction(
      id: json['id'] as int,
      type: json['transaction_type'] as String? ?? 'subscription',
      recipientPhone: json['recipient_phone'] as String? ?? '',
      amount: (json['amount'] as num?)?.toDouble() ?? 0.0,
      serverReference: json['reference'] as String? ?? '',
      ussdCode: json['ussd_code'] as String?,
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

class GatewayApi {
  static const String baseUrl = String.fromEnvironment(
    'TOL_API_BASE_URL',
    defaultValue: 'http://192.168.43.98:8000/api',
  );

  Future<GatewayStatus> fetchGatewayStatus() async {
    final response = await http.get(
      Uri.parse('$baseUrl/gateways/'),
      headers: {'Accept': 'application/json'},
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data is List && data.isNotEmpty) {
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
    final response = await http.post(
      Uri.parse('$baseUrl/$suffix'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'status': 'online',
        'gateway_uuid': device.uuid,
        'details': {
          'uuid': device.uuid,
          'phone_number': device.phoneNumber,
          'operator': device.operatorName,
          'device_model': device.deviceModel,
          'os_version': device.osVersion,
        },
      }),
    );

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
    final response = await http.post(
      Uri.parse('$baseUrl/transactions/execute/'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(request.toJson(ussdResponse: ussdResponse)),
    );

    if (response.statusCode == 200 || response.statusCode == 201) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Échec de l’exécution (${response.statusCode})');
  }

  Future<List<PendingTransaction>> fetchPendingTransactions(
    String gatewayUuid,
  ) async {
    final response = await http.get(
      Uri.parse('$baseUrl/transactions/pending/?gateway_uuid=$gatewayUuid'),
      headers: {'Accept': 'application/json'},
    );

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

  Future<void> reportTransactionResult({
    required String reference,
    required bool success,
    required String result,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/transactions/result/'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'transaction_reference': reference,
        'success': success,
        'result': result,
      }),
    );

    if (response.statusCode != 200 && response.statusCode != 201) {
      throw Exception(
        'Échec de mise à jour du résultat (${response.statusCode})',
      );
    }
  }
}

class DeviceSnapshot {
  const DeviceSnapshot({
    required this.uuid,
    required this.operatorName,
    required this.phoneNumber,
    required this.deviceModel,
    required this.osVersion,
  });

  final String uuid;
  final String operatorName;
  final String phoneNumber;
  final String deviceModel;
  final String osVersion;
}

