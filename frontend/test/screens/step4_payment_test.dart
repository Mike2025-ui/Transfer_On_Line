import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:transfer_on_line/models/models.dart';
import 'package:transfer_on_line/screens/step4_payment.dart';
import 'package:transfer_on_line/services/auth_service.dart';
import 'package:transfer_on_line/services/backend_api_service.dart';

class _NullStore implements AuthTokenStore {
  @override
  Future<String?> read(String key) async => null;
  @override
  Future<void> write(String key, String value) async {}
  @override
  Future<void> delete(String key) async {}
}

void main() {
  final auth = AuthService(
      store: _NullStore(),
      client: MockClient((r) async => http.Response('{}', 200)));

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
      // Empty checkout_url: _confirm() throws right after this and shows a
      // SnackBar - it never reaches launchUrl() (unmockable platform call)
      // or SuccessScreen. The real HTTP POST has already happened by then.
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
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
        authService: auth,
      ),
    ));

    await tester.tap(find.text('Wave'));
    await tester.pump();
    await tester.tap(find.textContaining('PAYER ET SOUSCRIRE'));
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
    expect(body['service'], 'Internet');
    expect(body['amount'], 1000);
    expect(body['payment_amount'], 1015);
    expect(body['recipient_phone'], '0700000001');
    expect(body['payment_method'], 'auto');
    expect(body['jeko_payment_method'], 'wave');
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
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
        authService: auth,
      ),
    ));

    expect(find.text('Paiement CinetPay'), findsNothing);
    expect(find.text('Paiement GeniusPay'), findsNothing);
    expect(find.text('Djeko'), findsNothing);
    expect(find.text('Paiement 100% sécurisé'), findsNothing);
    expect(find.text('Information tarifaire'), findsNothing);
    expect(find.textContaining('Frais de service (1.5%)'), findsOneWidget);
    expect(find.text('Total à payer'), findsOneWidget);
    expect(find.text('1015 FCFA'), findsWidgets);
    expect(find.textContaining('PAYER ET SOUSCRIRE'), findsOneWidget);
  });

  testWidgets(
      'les 5 moyens de paiement officiels sont affichés sans présélection',
      (tester) async {
    final client = MockClient((request) async => http.Response('{}', 200));
    await tester.pumpWidget(MaterialApp(
      home: Step4PaymentScreen(
        operatorId: 1,
        serviceId: 3,
        operator: 'Orange',
        service: 'Internet',
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
        authService: auth,
      ),
    ));

    expect(find.text('Moyen de paiement'), findsOneWidget);
    expect(find.text('Wave'), findsOneWidget);
    expect(find.text('Orange Money'), findsOneWidget);
    expect(find.text('MTN MoMo'), findsOneWidget);
    expect(find.text('Moov Money'), findsOneWidget);
    expect(find.text('Djamo'), findsOneWidget);
    expect(find.byIcon(Icons.check_circle_rounded), findsNothing);
  });

  testWidgets(
      'l\'absence de sélection de moyen de paiement bloque le paiement et affiche un message',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    var postCalled = false;
    final client = MockClient((request) async {
      postCalled = true;
      return http.Response('{}', 200);
    });

    await tester.pumpWidget(MaterialApp(
      home: Step4PaymentScreen(
        operatorId: 1,
        serviceId: 3,
        operator: 'Orange',
        service: 'Internet',
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
        authService: auth,
      ),
    ));

    await tester.tap(find.textContaining('PAYER ET SOUSCRIRE'));
    await tester.pump();

    expect(postCalled, isFalse);
    expect(find.textContaining('Veuillez choisir un moyen de paiement'),
        findsOneWidget);
  });

  // Audit frontend D4, §14/§17/§22 : vérifie qu'un double tap rapide ne
  // crée jamais deux transactions - le bouton doit se désactiver (loading)
  // dès le premier appui, avant même que la requête HTTP ne parte.
  testWidgets(
      'double clic rapide sur PAYER : une seule requête POST /transactions/execute/ part',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    var postCalls = 0;
    final client = MockClient((request) async {
      if (request.url.path.endsWith('/transactions/execute/')) postCalls++;
      // A slow-ish response widens the window during which a second tap
      // could slip through if the button were not actually disabled yet.
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
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
        authService: auth,
      ),
    ));

    await tester.tap(find.text('Wave'));
    await tester.pump();

    await tester.tap(find.textContaining('PAYER ET SOUSCRIRE'));
    await tester.pump();
    // _confirm()'s first synchronous setState (_loading = true) replaces the
    // button's entire label with a spinner (see TolButton) - it is not just
    // visually disabled, the text is gone outright, which is itself the
    // proof that a second tap on this exact label can no longer land.
    expect(find.textContaining('PAYER ET SOUSCRIRE'), findsNothing,
        reason:
            'the button must not be re-actionable while the request is in flight');
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 100));

    expect(postCalls, 1,
        reason: 'a rushed double tap must never create two transactions');
  });

  // Audit frontend D4, §19 : l'Idempotency-Key doit rester identique pour
  // un nouvel essai depuis le MÊME écran (même instance de Step4PaymentScreen)
  // - jamais régénérée à chaque tap.
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
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
        authService: auth,
      ),
    ));

    await tester.tap(find.text('Wave'));
    await tester.pump();

    await tester.tap(find.textContaining('PAYER ET SOUSCRIRE'));
    await tester.pump();
    await tester.pump(const Duration(
        milliseconds: 50)); // first attempt fails (500), button re-enabled

    await tester.tap(find.textContaining('PAYER ET SOUSCRIRE'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(seenKeys, hasLength(2));
    expect(seenKeys[0], isNotEmpty);
    expect(seenKeys[0], seenKeys[1],
        reason:
            'a retry from the same screen instance must reuse the exact same key');
  });

  testWidgets(
      'confirmer le paiement ajoute une notification persistée avec les détails complets',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    AppNotification? addedNotif;
    final client = MockClient((request) async => http.Response(
          jsonEncode({
            'reference': 'TOL-TEST-NOTIF',
            'status': 'pending',
            'checkout_url': '',
            'payment_reference': 'PAY-TEST',
            'payment_status': 'pending',
          }),
          201,
        ));

    await tester.pumpWidget(MaterialApp(
      home: Step4PaymentScreen(
        operatorId: 1,
        serviceId: 3,
        operator: 'Orange',
        service: 'Internet',
        phone: '0700000001',
        amount: 1000,
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification n) => addedNotif = n,
        notifications: const [],
        backendApiService: BackendApiService(client: client),
        authService: auth,
      ),
    ));

    await tester.tap(find.text('Wave'));
    await tester.pump();
    await tester.tap(find.textContaining('PAYER ET SOUSCRIRE'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(addedNotif, isNotNull);
    expect(addedNotif!.reference, 'TOL-TEST-NOTIF');
    expect(addedNotif!.operator, 'Orange');
    expect(addedNotif!.service, 'Internet');
    expect(addedNotif!.phone, '0700000001');
    expect(addedNotif!.amount, '1000 FCFA');
    expect(addedNotif!.fee, '15 FCFA');
    expect(addedNotif!.total, '1015 FCFA');
    expect(addedNotif!.paymentMethod, 'Wave');
    expect(addedNotif!.type, 'pending');
  });
}
