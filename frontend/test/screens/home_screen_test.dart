import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:transfer_on_line/screens/home_screen.dart';
import 'package:transfer_on_line/screens/step2_service.dart';
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
  TestWidgetsFlutterBinding.ensureInitialized();
  SharedPreferences.setMockInitialValues({});

  // A fake, in-memory-backed AuthService for every test in this file - none
  // of them are about authentication, and the real flutter_secure_storage
  // platform channel has no fake available in a plain `flutter test` run
  // (see AuthTokenStore's own doc comment).
  final auth = AuthService(
      store: _NullStore(),
      client: MockClient((r) async => http.Response('{}', 200)));

  Future<void> pumpHome(WidgetTester tester, http.Client client) async {
    // The real screen content is taller than the default 800x600 test
    // surface (SingleChildScrollView) - widen it so tap() can hit widgets
    // without needing to scroll them into view first.
    await tester.binding.setSurfaceSize(const Size(800, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: HomeScreen(
          backendApiService: BackendApiService(client: client),
          authService: auth),
    ));
  }

  testWidgets('shows a loading indicator while operators are being fetched',
      (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpHome(tester, client);

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('displays the operators returned by the backend', (tester) async {
    final client = MockClient((request) async {
      expect(request.url.path, contains('/operators/'));
      return http.Response(
        jsonEncode([
          {'id': 1, 'name': 'Orange', 'code': 'orange'},
          {'id': 2, 'name': 'MTN', 'code': 'mtn'},
        ]),
        200,
      );
    });

    await pumpHome(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Orange'), findsOneWidget);
    expect(find.text('MTN'), findsOneWidget);
    // A third, never-returned operator (representing one deactivated on the
    // backend) must never appear just because it exists elsewhere.
    expect(find.text('Moov'), findsNothing);
  });

  testWidgets(
      'shows an empty-state message when the backend has no active operators',
      (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpHome(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Aucun opérateur disponible.'), findsOneWidget);
    expect(find.text('Orange'), findsNothing);
  });

  testWidgets(
      'shows an error message with a retry button on failure, and retry recovers',
      (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      if (calls == 1) return http.Response('Internal Server Error', 500);
      return http.Response(
        jsonEncode([
          {'id': 1, 'name': 'Orange', 'code': 'orange'},
        ]),
        200,
      );
    });

    await pumpHome(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Impossible de charger les opérateurs.'), findsOneWidget);
    expect(find.text('RÉESSAYER'), findsOneWidget);

    await tester.tap(find.text('RÉESSAYER'));
    await tester.pump();
    await tester.pump();

    expect(find.text('Orange'), findsOneWidget);
    expect(calls, 2);
  });

  testWidgets(
      'tapping an operator card navigates to Step2ServiceScreen with the right operator name',
      (tester) async {
    final client = MockClient((request) async => http.Response(
          jsonEncode([
            {'id': 1, 'name': 'Orange', 'code': 'orange'},
          ]),
          200,
        ));

    await pumpHome(tester, client);
    await tester.pump();
    await tester.pump();

    await tester.tap(find.text('Orange'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.byType(Step2ServiceScreen), findsOneWidget);
    final step2 =
        tester.widget<Step2ServiceScreen>(find.byType(Step2ServiceScreen));
    expect(step2.operator, 'Orange');
    expect(step2.operatorId, 1);
  });

  testWidgets('l accueil ne montre plus les raccourcis historiques et profil',
      (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpHome(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.byIcon(Icons.receipt_long_rounded), findsNothing);
    expect(find.byIcon(Icons.person_outline_rounded), findsNothing);
    expect(find.byIcon(Icons.notifications_none_rounded), findsOneWidget);
  });

  testWidgets('l accueil ne montre plus les mentions de securite et de marque',
      (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpHome(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Sécurisé à 100%'), findsNothing);
    expect(find.text('Vos transactions sont protégées'), findsNothing);
    expect(find.text('AFRITECH-CI'), findsNothing);
  });

  // Audit frontend D4, §10 : une transaction locale restée "pending" (app
  // fermée avant résolution) doit être revérifiée auprès du Backend au
  // démarrage suivant, jamais supposée toujours active sans vérifier.
  testWidgets(
      'a locally pending transaction is reconciled against the backend on startup',
      (tester) async {
    SharedPreferences.setMockInitialValues({
      'transactions': jsonEncode([
        {
          'id': 'TOL-PENDING-1',
          'operator': 'Orange',
          'service': 'Internet',
          'operation': 'Souscription pour moi',
          'phone': '0700000001',
          'amount': 1000,
          'paymentMethod': 'CinetPay',
          'date': DateTime(2026, 1, 1).toIso8601String(),
          'status': 'pending',
        },
      ]),
    });
    var statusCalls = 0;
    final client = MockClient((request) async {
      if (request.url.path.contains('/operators/')) {
        return http.Response(jsonEncode([]), 200);
      }
      if (request.url.path.contains('/transactions/TOL-PENDING-1/status/')) {
        statusCalls++;
        return http.Response(
          jsonEncode({
            'status': 'success',
            'is_pending': false,
            'is_success': true,
            'is_failed': false,
            'is_cancelled': false
          }),
          200,
        );
      }
      return http.Response('not found', 404);
    });

    await pumpHome(tester, client);
    await tester.pump();
    await tester.pump();
    await tester.pump();

    expect(statusCalls, 1,
        reason:
            'the pending transaction must be checked exactly once against the backend');
    final prefs = await SharedPreferences.getInstance();
    final saved = jsonDecode(prefs.getString('transactions')!) as List;
    expect(saved.single['status'], 'ok',
        reason:
            'the local record must be corrected once the backend confirms the outcome');
  });

  testWidgets(
      'a network error while reconciling a pending transaction leaves it pending - never fabricates failure',
      (tester) async {
    SharedPreferences.setMockInitialValues({
      'transactions': jsonEncode([
        {
          'id': 'TOL-PENDING-2',
          'operator': 'Orange',
          'service': 'Internet',
          'operation': 'Souscription pour moi',
          'phone': '0700000001',
          'amount': 1000,
          'paymentMethod': 'CinetPay',
          'date': DateTime(2026, 1, 1).toIso8601String(),
          'status': 'pending',
        },
      ]),
    });
    final client = MockClient((request) async {
      if (request.url.path.contains('/operators/')) {
        return http.Response(jsonEncode([]), 200);
      }
      return http.Response('Internal Server Error', 500);
    });

    await pumpHome(tester, client);
    await tester.pump();
    await tester.pump();
    await tester.pump();

    final prefs = await SharedPreferences.getInstance();
    final saved = jsonDecode(prefs.getString('transactions')!) as List;
    expect(saved.single['status'], 'pending',
        reason:
            'a transient reconciliation error must never turn pending into failed');
  });

  testWidgets(
      'the notification bell badge displays unread count and disappears when notifications are cleared',
      (tester) async {
    SharedPreferences.setMockInitialValues({
      'notifications': jsonEncode([
        {
          'id': 101,
          'title': 'Paiement validé',
          'message': '1000 FCFA',
          'time': '10:00',
          'read': false,
          'icon': 'success',
          'type': 'success',
        },
        {
          'id': 102,
          'title': 'Paiement échoué',
          'message': 'Solde insuffisant',
          'time': '10:15',
          'read': false,
          'icon': 'error',
          'type': 'error',
        },
      ]),
    });

    final client = MockClient((request) async {
      if (request.url.path.contains('/operators/')) {
        return http.Response(jsonEncode([]), 200);
      }
      return http.Response(jsonEncode([]), 200);
    });

    await pumpHome(tester, client);
    await tester.pump();
    await tester.pump();

    // 2 notifications non lues -> le badge "2" doit être visible sur la cloche
    expect(find.text('2'), findsOneWidget);

    // L'utilisateur clique sur la cloche pour ouvrir l'écran des notifications
    await tester.tap(find.byIcon(Icons.notifications_none_rounded));
    await tester.pumpAndSettle();

    expect(find.text('Paiement validé'), findsOneWidget);

    // L'utilisateur clique sur "Tout effacer"
    await tester.tap(find.text('Tout effacer'));
    await tester.pumpAndSettle();

    expect(find.text('Paiement validé'), findsNothing);

    // Retour sur l'accueil
    await tester.tap(find.byIcon(Icons.arrow_back_rounded));
    await tester.pumpAndSettle();

    // De retour sur l'accueil, le badge "2" a complètement disparu
    expect(find.text('2'), findsNothing);
  });
}
