import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
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

Transaction _pendingTransaction({String id = 'TOL-TEST', String status = 'pending'}) => Transaction(
      id: id,
      operator: 'Orange',
      service: 'Internet',
      operation: 'Souscription pour moi',
      phone: '0700000001',
      amount: 1000,
      paymentMethod: 'CinetPay',
      date: DateTime(2026, 1, 1),
      status: status,
    );

http.Response _statusResponse({
  required String status,
  required bool pending,
  required bool success,
  required bool failed,
  required bool cancelled,
}) =>
    http.Response(
      jsonEncode({'status': status, 'is_pending': pending, 'is_success': success, 'is_failed': failed, 'is_cancelled': cancelled}),
      200,
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  SharedPreferences.setMockInitialValues({});

  final auth = AuthService(store: _NullStore(), client: MockClient((r) async => http.Response('{}', 200)));

  Future<void> pumpSuccessScreen(WidgetTester tester, Transaction tx, http.Client client) async {
    // Wide enough that the "VÉRIFIER MAINTENANT" button (only rendered after
    // the extended-wait threshold) and "VOIR LES NOTIFICATIONS" are on
    // screen and hit-testable, not just present in the (scrollable) tree.
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: SuccessScreen(
        transaction: tx,
        notifications: const [],
        backendApiService: BackendApiService(client: client),
        authService: auth,
      ),
    ));
  }

  testWidgets('the first check happens immediately - no wait for a tick - and resolves on success', (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      return _statusResponse(status: 'success', pending: false, success: true, failed: false, cancelled: false);
    });

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-OK'), client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Transaction réussie'), findsOneWidget);
    expect(calls, 1);

    await tester.pump(const Duration(minutes: 5));
    expect(calls, 1, reason: 'must not keep polling once resolved');
  });

  testWidgets('the immediate check resolves on a failed response', (tester) async {
    final client = MockClient((request) async =>
        _statusResponse(status: 'failed', pending: false, success: false, failed: true, cancelled: false));

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-FAIL'), client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Transaction échouée'), findsOneWidget);
  });

  testWidgets('the immediate check resolves on a cancelled response', (tester) async {
    final client = MockClient((request) async =>
        _statusResponse(status: 'cancelled', pending: false, success: false, failed: false, cancelled: true));

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-CANCEL'), client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Paiement annulé'), findsOneWidget);
  });

  testWidgets('a network error on the immediate check does not stop polling - retries per the graduated schedule', (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      if (calls == 1) throw Exception('network blip');
      return _statusResponse(status: 'success', pending: false, success: true, failed: false, cancelled: false);
    });

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-RETRY'), client);
    await tester.pump(); // the immediate check - fails
    expect(find.text('Paiement en attente'), findsOneWidget, reason: 'still pending after the failed immediate check');
    expect(calls, 1);

    await tester.pump(const Duration(seconds: 3)); // first scheduled retry delay
    await tester.pump();
    expect(find.text('Transaction réussie'), findsOneWidget);
    expect(calls, 2);
  });

  testWidgets('a transaction unknown to the backend (404) stops polling without fabricating a result', (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      return http.Response(jsonEncode({'error': 'Transaction not found'}), 404);
    });

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-UNKNOWN'), client);
    await tester.pump();
    expect(find.text('Paiement en attente'), findsOneWidget);
    expect(calls, 1);

    await tester.pump(const Duration(minutes: 5));
    expect(calls, 1, reason: 'a 404 stops the polling entirely, it is never retried');
  });

  testWidgets('polling continues indefinitely while pending - never declares failure due to a time cap', (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      return _statusResponse(status: 'pending', pending: true, success: false, failed: false, cancelled: false);
    });

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-FOREVER'), client);
    await tester.pump();
    // Cumulative schedule: immediate + 3+3+4+5+5+10+15+15+30+30 = 120s, then
    // every 60s - comfortably past the old 60s/15-attempt cap this replaces.
    await tester.pump(const Duration(seconds: 130));
    await tester.pump();

    expect(find.text('Paiement en attente'), findsOneWidget, reason: 'never fabricates an outcome without backend confirmation');
    expect(calls, greaterThan(5), reason: 'polling must still be active well past the old 60s cap');
  });

  testWidgets('after an extended wait, a manual "VÉRIFIER MAINTENANT" button appears and re-checks immediately', (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      return _statusResponse(status: 'pending', pending: true, success: false, failed: false, cancelled: false);
    });

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-LONGWAIT'), client);
    await tester.pump();
    expect(find.text('VÉRIFIER MAINTENANT'), findsNothing, reason: 'not shown before the extended-wait threshold');
    expect(find.text('Votre opération est toujours en cours.'), findsNothing);

    await tester.pump(const Duration(seconds: 65));
    await tester.pump();
    expect(find.text('Votre opération est toujours en cours.'), findsOneWidget);
    expect(find.text('VÉRIFIER MAINTENANT'), findsOneWidget);

    final callsBeforeManualCheck = calls;
    await tester.tap(find.text('VÉRIFIER MAINTENANT'));
    await tester.pump();
    expect(calls, greaterThan(callsBeforeManualCheck), reason: 'tapping must trigger an immediate check, not wait for the next tick');
  });

  testWidgets('returning to the foreground (AppLifecycleState.resumed) triggers an immediate check', (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      if (calls == 1) {
        return _statusResponse(status: 'pending', pending: true, success: false, failed: false, cancelled: false);
      }
      return _statusResponse(status: 'success', pending: false, success: true, failed: false, cancelled: false);
    });

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-RESUME'), client);
    await tester.pump(); // immediate check - still pending, next tick scheduled 3s out
    expect(calls, 1);

    // The app is backgrounded and resumed well before the next scheduled
    // tick (3s) would fire on its own - only the lifecycle callback should
    // be what triggers this second check.
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();

    expect(calls, 2, reason: 'resuming must check immediately, not wait for the pending timer');
    expect(find.text('Transaction réussie'), findsOneWidget);
  });

  testWidgets('disposing the screen cancels the timer - no further calls afterwards', (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      return _statusResponse(status: 'pending', pending: true, success: false, failed: false, cancelled: false);
    });

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-DISPOSE'), client);
    await tester.pump();
    final callsBeforeDispose = calls;
    expect(callsBeforeDispose, greaterThan(0));

    await tester.pumpWidget(const MaterialApp(home: SizedBox()));
    await tester.pump(const Duration(seconds: 30));

    expect(calls, callsBeforeDispose, reason: 'no polling call after the widget is removed from the tree');
  });

  testWidgets('a transaction that is already resolved never starts polling', (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      return http.Response('{}', 200);
    });

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-ALREADY-OK', status: 'ok'), client);
    await tester.pump(const Duration(seconds: 20));

    expect(calls, 0);
  });

  testWidgets('"VOIR LES NOTIFICATIONS" opens the real list passed in, never a hardcoded fallback', (tester) async {
    final client = MockClient((request) async =>
        _statusResponse(status: 'success', pending: false, success: true, failed: false, cancelled: false));
    final realNotifications = [
      AppNotification(
        title: 'Notification réelle de test',
        message: 'contenu',
        time: "Aujourd'hui · 10:00",
        read: false,
        icon: 'success',
        type: 'success',
      ),
    ];

    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: SuccessScreen(
        transaction: _pendingTransaction(id: 'TOL-NOTIF', status: 'ok'),
        notifications: realNotifications,
        backendApiService: BackendApiService(client: client),
        authService: auth,
      ),
    ));
    await tester.pump();

    await tester.tap(find.text('VOIR LES NOTIFICATIONS'));
    await tester.pumpAndSettle();

    expect(find.text('Notification réelle de test'), findsOneWidget,
        reason: 'the button must open whatever list this screen was actually given, not sampleNotifications');
  });

  testWidgets('SUCCESS never exposes internal D4/Gateway/USSD vocabulary', (tester) async {
    final client = MockClient((request) async =>
        _statusResponse(status: 'success', pending: false, success: true, failed: false, cancelled: false));

    await pumpSuccessScreen(tester, _pendingTransaction(id: 'TOL-CLEAN'), client);
    await tester.pump();
    await tester.pump();

    for (final forbidden in ['Gateway', 'USSD', 'attempt_id', 'UssdStep', 'NEW_FIELD', 'FINAL_FIELD']) {
      expect(find.textContaining(forbidden), findsNothing, reason: '"$forbidden" must never reach the Client UI');
    }
  });
}
