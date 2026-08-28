import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:transfer_on_line/models/models.dart';
import 'package:transfer_on_line/screens/phone_verification_screen.dart';
import 'package:transfer_on_line/screens/profile_screen.dart';
import 'package:transfer_on_line/services/auth_service.dart';

class _InMemoryStore implements AuthTokenStore {
  final Map<String, String> values = {};
  int deleteCalls = 0;
  @override
  Future<String?> read(String key) async => values[key];
  @override
  Future<void> write(String key, String value) async => values[key] = value;
  @override
  Future<void> delete(String key) async {
    deleteCalls++;
    values.remove(key);
  }
}

Transaction _tx({required String status, required String operator, int amount = 1000}) => Transaction(
      id: 'TOL-1',
      operator: operator,
      service: 'Internet',
      operation: 'Souscription pour moi',
      phone: '0700000001',
      amount: amount,
      paymentMethod: 'CinetPay',
      date: DateTime(2026, 1, 1),
      status: status,
    );

void main() {
  // Audit frontend D4, §18 : cet écran affichait un nom/email fictifs
  // ("Konan Yves", une adresse e-mail) jamais liés au compte réel.
  testWidgets('shows the real phone number from AuthService, never a fabricated name or email', (tester) async {
    final store = _InMemoryStore()..values['auth_phone_number'] = '+2250700000099';
    final auth = AuthService(store: store, client: MockClient((r) async => http.Response('{}', 200)));

    await tester.binding.setSurfaceSize(const Size(800, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: ProfileScreen(transactions: const [], authService: auth),
    ));
    await tester.pumpAndSettle();

    expect(find.text('+2250700000099'), findsOneWidget);
    expect(find.text('Konan Yves'), findsNothing);
    expect(find.textContaining('@'), findsNothing, reason: 'no fabricated email must ever be shown - the backend has no such field');
  });

  testWidgets('shows a placeholder, never a crash, when no phone number is stored', (tester) async {
    final auth = AuthService(store: _InMemoryStore(), client: MockClient((r) async => http.Response('{}', 200)));

    await tester.binding.setSurfaceSize(const Size(800, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: ProfileScreen(transactions: const [], authService: auth),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Numéro non disponible'), findsOneWidget);
  });

  testWidgets('statistics reflect the real transactions passed in, not sampleTransactions', (tester) async {
    final auth = AuthService(store: _InMemoryStore(), client: MockClient((r) async => http.Response('{}', 200)));

    await tester.binding.setSurfaceSize(const Size(800, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: ProfileScreen(
        transactions: [_tx(status: 'ok', operator: 'MTN', amount: 2500)],
        authService: auth,
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('2 500'), findsOneWidget, reason: 'total spent must come from the real transaction, formatted');
    expect(find.text('1'), findsWidgets, reason: 'the transaction count stat must reflect the real list length');
  });

  testWidgets('an empty transaction history shows a message instead of fabricated operator stats', (tester) async {
    final auth = AuthService(store: _InMemoryStore(), client: MockClient((r) async => http.Response('{}', 200)));

    await tester.binding.setSurfaceSize(const Size(800, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: ProfileScreen(transactions: const [], authService: auth),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Aucune transaction pour le moment.'), findsOneWidget);
  });

  // Audit frontend D4, §18 : le bouton "Déconnexion" ne faisait rien
  // (onPressed: () {}) alors qu'AuthService.logout() existe et fonctionne
  // déjà (voir auth_service_test.dart).
  testWidgets('Déconnexion calls AuthService.logout() and navigates to PhoneVerificationScreen', (tester) async {
    final store = _InMemoryStore()
      ..values['auth_phone_number'] = '+2250700000099'
      ..values['auth_access_token'] = 'some-access-token'
      ..values['auth_refresh_token'] = 'some-refresh-token';
    final auth = AuthService(store: store, client: MockClient((r) async => http.Response('{}', 200)));

    await tester.binding.setSurfaceSize(const Size(800, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: ProfileScreen(transactions: const [], authService: auth),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Déconnexion'));
    await tester.pumpAndSettle();

    expect(find.byType(PhoneVerificationScreen), findsOneWidget);
    expect(await store.read('auth_access_token'), isNull, reason: 'logout must actually clear the stored session, not just navigate');
    expect(await store.read('auth_refresh_token'), isNull);
  });

  testWidgets('a rushed double tap on Déconnexion only ever runs one full logout', (tester) async {
    final store = _InMemoryStore();
    final auth = AuthService(store: store, client: MockClient((r) async => http.Response('{}', 200)));

    await tester.binding.setSurfaceSize(const Size(800, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: ProfileScreen(transactions: const [], authService: auth),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Déconnexion'));
    // A second tap attempt right away, before _loggingOut's setState has
    // even had a chance to rebuild the button - _logout()'s own `if
    // (_loggingOut) return;` guard is what must stop this from running twice.
    await tester.tap(find.text('Déconnexion'), warnIfMissed: false);
    await tester.pumpAndSettle();

    expect(find.byType(PhoneVerificationScreen), findsOneWidget);
    // 3 keys cleared exactly once - never 6, which a double-invoked logout
    // would produce.
    expect(store.deleteCalls, 3);
  });
}
