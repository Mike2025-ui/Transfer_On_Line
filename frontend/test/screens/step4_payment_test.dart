import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:transfer_on_line/models/models.dart';
import 'package:transfer_on_line/screens/step4_payment.dart';
import 'package:transfer_on_line/services/backend_api_service.dart';

void main() {
  Future<Map<String, dynamic>> pumpAndConfirm(
    WidgetTester tester, {
    required int operatorId,
    required int serviceId,
  }) async {
    // The confirm button sits below the default 800x600 test surface.
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    late Map<String, dynamic> sentBody;
    final client = MockClient((request) async {
      sentBody = jsonDecode(request.body) as Map<String, dynamic>;
      return http.Response(
        jsonEncode({
          'reference': 'TOL-TEST',
          'status': 'pending',
          'checkout_url': '',
          'payment_reference': 'PAY-TEST',
          'payment_status': 'pending',
        }),
        201,
      );
    });

    await tester.pumpWidget(MaterialApp(
      home: Step4PaymentScreen(
        operatorId: operatorId,
        serviceId: serviceId,
        operator: 'Orange',
        service: 'Internet',
        operation: 'Souscription pour moi',
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
      ),
    ));

    await tester.tap(find.text('PAYER ET SOUSCRIRE'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    return sentBody;
  }

  testWidgets(
      'tapping confirm sends the real operatorId/serviceId received from the screens above',
      (tester) async {
    final body = await pumpAndConfirm(tester, operatorId: 1, serviceId: 3);

    expect(body['operator_id'], 1);
    expect(body['service_id'], 3);
    expect(body['operator'], 'Orange');
    expect(body['service'], 'internet');
    expect(body['amount'], 1000);
    expect(body['recipient_phone'], '0700000001');
    expect(body['payment_method'], 'jeko');
    expect(body['jeko_payment_method'], 'wave');
  });

  testWidgets('selecting a payment method updates jeko_payment_method',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    late Map<String, dynamic> sentBody;
    final client = MockClient((request) async {
      sentBody = jsonDecode(request.body) as Map<String, dynamic>;
      return http.Response(
        jsonEncode({
          'reference': 'TOL-TEST',
          'status': 'pending',
          'checkout_url': '',
          'payment_reference': 'PAY-TEST',
          'payment_status': 'pending',
        }),
        201,
      );
    });

    await tester.pumpWidget(MaterialApp(
      home: Step4PaymentScreen(
        operatorId: 1,
        serviceId: 3,
        operator: 'Orange',
        service: 'Internet',
        operation: 'Souscription pour moi',
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
      ),
    ));

    await tester.tap(find.text('Orange Money'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('PAYER ET SOUSCRIRE'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(sentBody['jeko_payment_method'], 'orange');
  });

  testWidgets(
      'different operatorId/serviceId values are forwarded faithfully, not hardcoded',
      (tester) async {
    final body = await pumpAndConfirm(tester, operatorId: 42, serviceId: 7);

    expect(body['operator_id'], 42);
    expect(body['service_id'], 7);
  });

  testWidgets('the confirm button is the only visible payment action',
      (tester) async {
    final client = MockClient((request) async => http.Response(
          jsonEncode({
            'reference': 'TOL-TEST',
            'status': 'pending',
            'checkout_url': '',
            'payment_reference': 'PAY-TEST',
            'payment_status': 'pending'
          }),
          201,
        ));

    await tester.pumpWidget(MaterialApp(
      home: Step4PaymentScreen(
        operatorId: 1,
        serviceId: 3,
        operator: 'Orange',
        service: 'Internet',
        operation: 'Souscription pour moi',
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
      ),
    ));

    expect(find.text('Paiement CinetPay'), findsNothing);
    expect(find.text('Paiement GeniusPay'), findsNothing);
    expect(find.text('Jeko'), findsNothing);
    expect(find.text('Paiement 100% sécurisé'), findsNothing);
    expect(find.textContaining('Frais de service'), findsNothing);
    expect(find.text('Total à payer'), findsNothing);
    expect(find.text('Information tarifaire'), findsNothing);
    expect(find.text('PAYER ET SOUSCRIRE'), findsOneWidget);
  });

  testWidgets(
      'double clic rapide sur PAYER : une seule requête POST /transactions/execute/ part',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    var postCalls = 0;
    final client = MockClient((request) async {
      if (request.url.path.endsWith('/transactions/execute/')) postCalls++;
      await Future<void>.delayed(const Duration(milliseconds: 30));
      return http.Response(
        jsonEncode({
          'reference': 'TOL-TEST',
          'status': 'pending',
          'checkout_url': '',
          'payment_reference': 'PAY-TEST',
          'payment_status': 'pending'
        }),
        201,
      );
    });

    await tester.pumpWidget(MaterialApp(
      home: Step4PaymentScreen(
        operatorId: 1,
        serviceId: 3,
        operator: 'Orange',
        service: 'Internet',
        operation: 'Souscription pour moi',
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
      ),
    ));

    await tester.tap(find.text('PAYER ET SOUSCRIRE'));
    await tester.pump();
    expect(find.text('PAYER ET SOUSCRIRE'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 100));

    expect(postCalls, 1);
  });

  testWidgets(
      'la même Idempotency-Key est réutilisée si l\'utilisateur retente depuis le même écran',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final seenKeys = <String>[];
    var call = 0;
    final client = MockClient((request) async {
      call++;
      if (request.url.path.endsWith('/transactions/execute/')) {
        seenKeys.add(request.headers['Idempotency-Key'] ?? '');
      }
      if (call == 1) return http.Response('Internal Server Error', 500);
      return http.Response(
        jsonEncode({
          'reference': 'TOL-TEST',
          'status': 'pending',
          'checkout_url': '',
          'payment_reference': 'PAY-TEST',
          'payment_status': 'pending'
        }),
        201,
      );
    });

    await tester.pumpWidget(MaterialApp(
      home: Step4PaymentScreen(
        operatorId: 1,
        serviceId: 3,
        operator: 'Orange',
        service: 'Internet',
        operation: 'Souscription pour moi',
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
      ),
    ));

    await tester.tap(find.text('PAYER ET SOUSCRIRE'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    await tester.tap(find.text('PAYER ET SOUSCRIRE'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(seenKeys, hasLength(2));
    expect(seenKeys[0], isNotEmpty);
    expect(seenKeys[0], seenKeys[1]);
  });
}
