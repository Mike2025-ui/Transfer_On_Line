import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:transfer_on_line/services/backend_api_service.dart';

void main() {
  group('BackendApiService.getTransactionStatus', () {
    test('pending', () async {
      final api = BackendApiService(
        client: MockClient((request) async {
          expect(request.url.path, contains('/transactions/TOL-1/status/'));
          return http.Response(
            jsonEncode({'status': 'pending', 'is_pending': true, 'is_success': false, 'is_failed': false, 'is_cancelled': false}),
            200,
          );
        }),
      );

      final result = await api.getTransactionStatus('TOL-1');

      expect(result.status, 'pending');
      expect(result.isPending, isTrue);
      expect(result.isSuccess, isFalse);
    });

    test('success', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response(
              jsonEncode({'status': 'success', 'is_pending': false, 'is_success': true, 'is_failed': false, 'is_cancelled': false}),
              200,
            )),
      );

      final result = await api.getTransactionStatus('TOL-2');

      expect(result.isSuccess, isTrue);
      expect(result.isPending, isFalse);
    });

    test('failed', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response(
              jsonEncode({'status': 'failed', 'is_pending': false, 'is_success': false, 'is_failed': true, 'is_cancelled': false}),
              200,
            )),
      );

      final result = await api.getTransactionStatus('TOL-3');

      expect(result.isFailed, isTrue);
    });

    test('cancelled', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response(
              jsonEncode({'status': 'cancelled', 'is_pending': false, 'is_success': false, 'is_failed': false, 'is_cancelled': true}),
              200,
            )),
      );

      final result = await api.getTransactionStatus('TOL-4');

      expect(result.isCancelled, isTrue);
    });

    test('404 throws TransactionNotFoundException', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response(jsonEncode({'error': 'Transaction not found'}), 404)),
      );

      expect(
        () => api.getTransactionStatus('does-not-exist'),
        throwsA(isA<TransactionNotFoundException>()),
      );
    });

    test('a server error throws a generic exception, not TransactionNotFoundException', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response('Internal Server Error', 500)),
      );

      await expectLater(
        api.getTransactionStatus('TOL-5'),
        throwsA(isA<Exception>().having((e) => e is TransactionNotFoundException, 'is 404', isFalse)),
      );
    });

    test('sends the access token as a Bearer header when provided', () async {
      final api = BackendApiService(
        client: MockClient((request) async {
          expect(request.headers['Authorization'], 'Bearer my-token');
          return http.Response(
            jsonEncode({'status': 'pending', 'is_pending': true, 'is_success': false, 'is_failed': false, 'is_cancelled': false}),
            200,
          );
        }),
      );

      await api.getTransactionStatus('TOL-6', accessToken: 'my-token');
    });
  });

  group('BackendApiService.getOperators', () {
    test('returns the active operators from the backend', () async {
      final api = BackendApiService(
        client: MockClient((request) async {
          expect(request.url.path, contains('/operators/'));
          return http.Response(
            jsonEncode([
              {'id': 1, 'name': 'Orange', 'code': 'orange'},
              {'id': 2, 'name': 'MTN', 'code': 'mtn'},
            ]),
            200,
          );
        }),
      );

      final operators = await api.getOperators();

      expect(operators, hasLength(2));
      expect(operators[0].id, 1);
      expect(operators[0].name, 'Orange');
      expect(operators[1].name, 'MTN');
    });

    test('an empty list is returned as-is, not an error', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response(jsonEncode([]), 200)),
      );

      final operators = await api.getOperators();

      expect(operators, isEmpty);
    });

    test('a server error throws', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response('Internal Server Error', 500)),
      );

      expect(() => api.getOperators(), throwsA(isA<Exception>()));
    });

    test('a network failure throws', () async {
      final api = BackendApiService(
        client: MockClient((request) async => throw const SocketException('offline')),
      );

      expect(() => api.getOperators(), throwsA(anything));
    });
  });

  group('BackendApiService.getServices', () {
    test('returns the active services from the backend', () async {
      final api = BackendApiService(
        client: MockClient((request) async {
          expect(request.url.path, contains('/services/'));
          return http.Response(
            jsonEncode([
              {'id': 1, 'name': 'Internet', 'code': 'internet'},
            ]),
            200,
          );
        }),
      );

      final services = await api.getServices();

      expect(services, hasLength(1));
      expect(services[0].name, 'Internet');
    });

    test('an empty list is returned as-is, not an error', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response(jsonEncode([]), 200)),
      );

      final services = await api.getServices();

      expect(services, isEmpty);
    });

    test('a server error throws', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response('Internal Server Error', 500)),
      );

      expect(() => api.getServices(), throwsA(isA<Exception>()));
    });
  });

  group('BackendApiService.getAvailableAmounts', () {
    test('returns the configured amounts for (operatorId, serviceId)', () async {
      final api = BackendApiService(
        client: MockClient((request) async {
          expect(request.url.path, contains('/operators/1/services/2/amounts/'));
          return http.Response(
            jsonEncode([
              {'amount': 500},
              {'amount': 1000},
            ]),
            200,
          );
        }),
      );

      final amounts = await api.getAvailableAmounts(1, 2);

      expect(amounts, hasLength(2));
      expect(amounts[0].amount, 500.0);
      expect(amounts[1].amount, 1000.0);
    });

    test('a single amount of 500 parses correctly', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response(
              jsonEncode([
                {'amount': 500},
              ]),
              200,
            )),
      );

      final amounts = await api.getAvailableAmounts(1, 2);

      expect(amounts, hasLength(1));
      expect(amounts.single.amount, 500.0);
    });

    test('an empty list means no fixed catalog - free amount entry stays valid', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response(jsonEncode([]), 200)),
      );

      final amounts = await api.getAvailableAmounts(1, 2);

      expect(amounts, isEmpty);
    });

    test('a server error throws', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response('Internal Server Error', 500)),
      );

      expect(() => api.getAvailableAmounts(1, 2), throwsA(isA<Exception>()));
    });

    test('a network failure throws', () async {
      final api = BackendApiService(
        client: MockClient((request) async => throw const SocketException('offline')),
      );

      expect(() => api.getAvailableAmounts(1, 2), throwsA(anything));
    });
  });

  group('BackendApiService.createTransaction', () {
    test('sends operator_id/service_id in addition to the names when provided', () async {
      late Map<String, dynamic> sentBody;
      final api = BackendApiService(
        client: MockClient((request) async {
          sentBody = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode({
              'reference': 'TOL-1', 'status': 'pending', 'checkout_url': 'https://pay/tok',
              'payment_reference': 'PAY-1', 'payment_status': 'pending',
            }),
            201,
          );
        }),
      );

      await api.createTransaction(
        operator: 'Orange', service: 'Internet', operation: 'subscription',
        phone: '0700000001', amount: 500, operatorId: 1, serviceId: 2,
      );

      expect(sentBody['operator_id'], 1);
      expect(sentBody['service_id'], 2);
      expect(sentBody['operator'], 'Orange');
      expect(sentBody['service'], 'Internet');
    });

    test('omits operator_id/service_id when not provided - existing callers are unaffected', () async {
      late Map<String, dynamic> sentBody;
      final api = BackendApiService(
        client: MockClient((request) async {
          sentBody = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode({
              'reference': 'TOL-1', 'status': 'pending', 'checkout_url': 'https://pay/tok',
              'payment_reference': 'PAY-1', 'payment_status': 'pending',
            }),
            201,
          );
        }),
      );

      await api.createTransaction(
        operator: 'Orange', service: 'Internet', operation: 'subscription',
        phone: '0700000001', amount: 500,
      );

      expect(sentBody.containsKey('operator_id'), isFalse);
      expect(sentBody.containsKey('service_id'), isFalse);
      expect(sentBody['operator'], 'Orange');
    });

    test('parses a successful response', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response(
              jsonEncode({
                'reference': 'TOL-1', 'status': 'pending', 'checkout_url': 'https://pay/tok',
                'payment_reference': 'PAY-1', 'payment_status': 'pending',
              }),
              201,
            )),
      );

      final result = await api.createTransaction(
        operator: 'Orange', service: 'Internet', operation: 'subscription',
        phone: '0700000001', amount: 500, operatorId: 1, serviceId: 2,
      );

      expect(result.reference, 'TOL-1');
      expect(result.checkoutUrl, 'https://pay/tok');
    });

    test('a server error throws with the backend error message', () async {
      final api = BackendApiService(
        client: MockClient((request) async => http.Response(
              jsonEncode({'error': 'operator_id=999 introuvable ou inactif'}),
              404,
            )),
      );

      expect(
        () => api.createTransaction(
          operator: 'Orange', service: 'Internet', operation: 'subscription',
          phone: '0700000001', amount: 500, operatorId: 999,
        ),
        throwsA(isA<Exception>().having((e) => e.toString(), 'message', contains('introuvable'))),
      );
  });

  group('BackendApiService.baseUrl', () {
    // Vérifie que l'URL de base se termine obligatoirement par /api
    test('garantit la présence du suffixe /api même si omis lors du build', () {
      expect(BackendApiService.baseUrl.endsWith('/api'), isTrue);
    });
  });
}
