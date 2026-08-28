import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:gateway_apk/services/gateway_api.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Business-model audit Phase 7: GatewayApi attaches an `X-Gateway-Secret`
/// header (constructor-injected here, a real build instead bakes it in via
/// --dart-define=TOL_GATEWAY_SECRET - see GatewayApi's own doc) to every
/// request the Gateway-facing endpoints now require it on, and to none of
/// the others. No real network involved - a `http.MockClient` records what
/// headers actually went out, matching this project's existing test style
/// (see gateway_loop_test.dart).
void main() {
  DeviceSnapshot fakeSnapshot() => const DeviceSnapshot(
    uuid: 'device-1',
    operatorName: 'Orange',
    phoneNumber: '0700000000',
    deviceModel: 'Pixel',
    osVersion: '14',
  );

  http.Response okJson(Map<String, dynamic> body) =>
      http.Response(jsonEncode(body), 200);

  // Header name lookup, case-insensitively - http's own Request.headers is a
  // plain Map<String, String> that preserves whatever case the call site
  // used, so a naive exact-key lookup would be brittle here.
  String? secretHeaderValue(Map<String, String>? headers) {
    if (headers == null) return null;
    for (final entry in headers.entries) {
      if (entry.key.toLowerCase() == 'x-gateway-secret') return entry.value;
    }
    return null;
  }

  group('with no secret configured (default, unset TOL_GATEWAY_SECRET)', () {
    test('sendHeartbeat sends no X-Gateway-Secret header', () async {
      Map<String, String>? seenHeaders;
      final client = MockClient((request) async {
        seenHeaders = request.headers;
        return okJson({
          'id': 1,
          'uuid': 'device-1',
          'device': {'uuid': 'device-1', 'phone_number': '0700000000', 'details': {}},
          'heartbeat_status': 'online',
          'last_checkin': null,
        });
      });
      final api = GatewayApi(client: client);

      await api.sendHeartbeat(null, fakeSnapshot());

      expect(secretHeaderValue(seenHeaders), isNull);
    });

    test('fetchPendingTransactions sends no X-Gateway-Secret header', () async {
      Map<String, String>? seenHeaders;
      final client = MockClient((request) async {
        seenHeaders = request.headers;
        return http.Response(jsonEncode(<dynamic>[]), 200);
      });
      final api = GatewayApi(client: client);

      await api.fetchPendingTransactions('gw-1');

      expect(secretHeaderValue(seenHeaders), isNull);
    });
  });

  group('with a gatewaySecret injected', () {
    const secret = 'test-gateway-secret-value';

    test('sendHeartbeat sends the secret as X-Gateway-Secret', () async {
      Map<String, String>? seenHeaders;
      final client = MockClient((request) async {
        seenHeaders = request.headers;
        return okJson({
          'id': 1,
          'uuid': 'device-1',
          'device': {'uuid': 'device-1', 'phone_number': '0700000000', 'details': {}},
          'heartbeat_status': 'online',
          'last_checkin': null,
        });
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await api.sendHeartbeat(null, fakeSnapshot());

      expect(secretHeaderValue(seenHeaders), secret);
    });

    test('fetchPendingTransactions sends the secret as X-Gateway-Secret', () async {
      Map<String, String>? seenHeaders;
      final client = MockClient((request) async {
        seenHeaders = request.headers;
        return http.Response(jsonEncode(<dynamic>[]), 200);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await api.fetchPendingTransactions('gw-1');

      expect(secretHeaderValue(seenHeaders), secret);
    });

    test('reportTransactionResult sends the secret as X-Gateway-Secret', () async {
      Map<String, String>? seenHeaders;
      final client = MockClient((request) async {
        seenHeaders = request.headers;
        return http.Response('', 200);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await api.reportTransactionResult(reference: 'ref-1', success: true, result: 'OK');

      expect(secretHeaderValue(seenHeaders), secret);
    });

    test('fetchSmsPending sends the secret as X-Gateway-Secret', () async {
      Map<String, String>? seenHeaders;
      final client = MockClient((request) async {
        seenHeaders = request.headers;
        return http.Response(jsonEncode(<dynamic>[]), 200);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await api.fetchSmsPending();

      expect(secretHeaderValue(seenHeaders), secret);
    });

    test('reportSmsResult sends the secret as X-Gateway-Secret', () async {
      Map<String, String>? seenHeaders;
      final client = MockClient((request) async {
        seenHeaders = request.headers;
        return http.Response('', 200);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await api.reportSmsResult(id: 1, success: true);

      expect(secretHeaderValue(seenHeaders), secret);
    });

    test('fetchGatewayStatus never sends the secret - not a protected endpoint', () async {
      Map<String, String>? seenHeaders;
      final client = MockClient((request) async {
        seenHeaders = request.headers;
        return okJson({
          'id': 1,
          'uuid': 'device-1',
          'device': {'uuid': 'device-1', 'phone_number': '0700000000', 'details': {}},
          'heartbeat_status': 'online',
          'last_checkin': null,
        });
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await api.fetchGatewayStatus();

      expect(secretHeaderValue(seenHeaders), isNull);
    });

    test('executeTransaction never sends the secret - the manual test-button endpoint, not protected', () async {
      Map<String, String>? seenHeaders;
      final client = MockClient((request) async {
        seenHeaders = request.headers;
        return okJson({'reference': 'ref-1'});
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await api.executeTransaction(
        TransactionRequest(type: 'subscription', recipientPhone: '0700000000', amount: 500),
      );

      expect(secretHeaderValue(seenHeaders), isNull);
    });
  });

  group('generateIdempotencyKey', () {
    test('produces a well-formed UUID v4 string', () {
      final key = generateIdempotencyKey();
      final pattern = RegExp(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
      );
      expect(pattern.hasMatch(key), isTrue, reason: 'got "$key"');
    });

    test('two calls produce two different keys', () {
      expect(generateIdempotencyKey(), isNot(generateIdempotencyKey()));
    });
  });

  group('sendTransactionStep', () {
    const secret = 'test-gateway-secret-value';

    Map<String, dynamic> capturedBody(http.Request request) =>
        jsonDecode(request.body) as Map<String, dynamic>;

    test('sends X-Gateway-Secret and Idempotency-Key headers', () async {
      Map<String, String>? seenHeaders;
      final client = MockClient((request) async {
        seenHeaders = request.headers;
        return http.Response(jsonEncode({'action': 'DONE'}), 200);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await api.sendTransactionStep(
        transactionReference: 'TOL-1',
        attemptId: 45,
        event: 'FINAL_FIELD',
        idempotencyKey: 'KEY-A',
      );

      String? header(String name) {
        for (final entry in seenHeaders!.entries) {
          if (entry.key.toLowerCase() == name.toLowerCase()) return entry.value;
        }
        return null;
      }

      expect(header('X-Gateway-Secret'), secret);
      expect(header('Idempotency-Key'), 'KEY-A');
    });

    test('NEW_FIELD is serialized exactly per the Phase C contract', () async {
      http.Request? seenRequest;
      final client = MockClient((request) async {
        seenRequest = request;
        return http.Response(
          jsonEncode({'action': 'INPUT', 'values': ['0700000000', '500']}), 200,
        );
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      final response = await api.sendTransactionStep(
        transactionReference: 'TOL-1',
        attemptId: 45,
        event: 'NEW_FIELD',
        idempotencyKey: 'KEY-A',
        fieldCount: 2,
      );

      expect(capturedBody(seenRequest!), {
        'transaction_reference': 'TOL-1',
        'attempt_id': 45,
        'event': 'NEW_FIELD',
        'field_count': 2,
      });
      expect(response.action, 'INPUT');
      expect(response.values, ['0700000000', '500']);
    });

    test('FINAL_FIELD is serialized exactly per the Phase C contract', () async {
      http.Request? seenRequest;
      final client = MockClient((request) async {
        seenRequest = request;
        return http.Response(jsonEncode({'action': 'DONE'}), 200);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      final response = await api.sendTransactionStep(
        transactionReference: 'TOL-1',
        attemptId: 45,
        event: 'FINAL_FIELD',
        idempotencyKey: 'KEY-B',
      );

      expect(capturedBody(seenRequest!), {
        'transaction_reference': 'TOL-1',
        'attempt_id': 45,
        'event': 'FINAL_FIELD',
      });
      expect(response.action, 'DONE');
    });

    test('RESULT SUCCESS is serialized exactly, operator_message never truncated', () async {
      const fullMessage =
          'Transfert effectué avec succès. Montant : 500 FCFA. Identifiant : 847291. Merci.';
      http.Request? seenRequest;
      final client = MockClient((request) async {
        seenRequest = request;
        return http.Response(jsonEncode({'action': 'DONE', 'status': 'SUCCESS'}), 200);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      final response = await api.sendTransactionStep(
        transactionReference: 'TOL-1',
        attemptId: 45,
        event: 'RESULT',
        idempotencyKey: 'KEY-C',
        status: 'SUCCESS',
        operatorMessage: fullMessage,
      );

      expect(capturedBody(seenRequest!)['operator_message'], fullMessage);
      expect((capturedBody(seenRequest!)['operator_message'] as String).length, fullMessage.length);
      expect(response.action, 'DONE');
      expect(response.status, 'SUCCESS');
    });

    test('RESULT FAILED is serialized exactly with error_code', () async {
      http.Request? seenRequest;
      final client = MockClient((request) async {
        seenRequest = request;
        return http.Response(jsonEncode({'action': 'DONE', 'status': 'RETRY_SCHEDULED'}), 200);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      final response = await api.sendTransactionStep(
        transactionReference: 'TOL-1',
        attemptId: 45,
        event: 'RESULT',
        idempotencyKey: 'KEY-D',
        status: 'FAILED',
        operatorMessage: 'Erreur réseau',
        errorCode: 'network_error',
      );

      expect(capturedBody(seenRequest!), {
        'transaction_reference': 'TOL-1',
        'attempt_id': 45,
        'event': 'RESULT',
        'status': 'FAILED',
        'operator_message': 'Erreur réseau',
        'error_code': 'network_error',
      });
      expect(response.status, 'RETRY_SCHEDULED');
    });

    test('HTTP 401 raises TransactionStepException with statusCode preserved', () async {
      final client = MockClient((request) async {
        return http.Response(jsonEncode({'error': 'Gateway authentication required'}), 401);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await expectLater(
        api.sendTransactionStep(
          transactionReference: 'TOL-1', attemptId: 45, event: 'NEW_FIELD',
          idempotencyKey: 'KEY-A', fieldCount: 1,
        ),
        throwsA(isA<TransactionStepException>()
            .having((e) => e.statusCode, 'statusCode', 401)
            .having((e) => e.errorMessage, 'errorMessage', 'Gateway authentication required')),
      );
    });

    test('HTTP 403 raises TransactionStepException with statusCode preserved', () async {
      final client = MockClient((request) async {
        return http.Response(jsonEncode({'error': 'This Gateway was not assigned this attempt'}), 403);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await expectLater(
        api.sendTransactionStep(
          transactionReference: 'TOL-1', attemptId: 45, event: 'NEW_FIELD',
          idempotencyKey: 'KEY-A', fieldCount: 1,
        ),
        throwsA(isA<TransactionStepException>().having((e) => e.statusCode, 'statusCode', 403)),
      );
    });

    test('HTTP 409 raises TransactionStepException with statusCode preserved', () async {
      final client = MockClient((request) async {
        return http.Response(jsonEncode({'error': 'Attempt is not active (status=success)'}), 409);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await expectLater(
        api.sendTransactionStep(
          transactionReference: 'TOL-1', attemptId: 45, event: 'NEW_FIELD',
          idempotencyKey: 'KEY-A', fieldCount: 1,
        ),
        throwsA(isA<TransactionStepException>().having((e) => e.statusCode, 'statusCode', 409)),
      );
    });

    test('a slow backend raises TimeoutException, not a wrapped exception', () async {
      final client = MockClient((request) async {
        await Future.delayed(const Duration(seconds: 20));
        return http.Response(jsonEncode({'action': 'DONE'}), 200);
      });
      final api = GatewayApi(client: client, gatewaySecret: secret);

      await expectLater(
        api.sendTransactionStep(
          transactionReference: 'TOL-1', attemptId: 45, event: 'FINAL_FIELD', idempotencyKey: 'KEY-A',
        ),
        throwsA(isA<TimeoutException>()),
      );
    });
  });
}
