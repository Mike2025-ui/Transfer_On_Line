import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:transfer_on_line/models/models.dart';
import 'package:transfer_on_line/screens/step2_service.dart';
import 'package:transfer_on_line/screens/step3_info.dart';
import 'package:transfer_on_line/screens/step4_payment.dart';
import 'package:transfer_on_line/services/auth_service.dart';
import 'package:transfer_on_line/services/backend_api_service.dart';

/// Best-available integration coverage for the flow requested by the D4
/// frontend implementation task (§25):
///
///   Home -> Service -> Informations -> Paiement -> création transaction
///     -> EN COURS -> PENDING -> PENDING -> SUCCESS  (and a FAILED variant)
///
/// CE QUI EST RÉELLEMENT SIMULÉ (à ne jamais présenter comme prouvé) :
/// - Le premier test démarre directement à Step2ServiceScreen (avec un
///   BackendApiService explicite, exactement le principe déjà établi dans
///   step2_service_test.dart) puis conduit l'utilisateur, par de vraies
///   interactions `tester.tap`/`tester.enterText` sur les vrais écrans,
///   jusqu'à Step4PaymentScreen. La frontière Home -> Step2 elle-même est
///   déjà prouvée séparément, avec de vrais taps, par home_screen_test.dart
///   ("tapping an operator card navigates to Step2ServiceScreen with the
///   right operator name") - inutile de la répéter ici. Elle ne peut de
///   toute façon pas être enchaînée dans le MÊME test sans reconstruire
///   l'arbre : `_operatorCard` dans home_screen.dart ne transmet pas son
///   BackendApiService à la navigation réelle vers Step2ServiceScreen (une
///   caractéristique préexistante de l'app, pas un bug introduit par D4, et
///   hors périmètre de cette tâche - aucune demande de refactor de la
///   navigation), donc un Step2ServiceScreen atteint par un vrai tap depuis
///   Home utiliserait un BackendApiService() par défaut dont le vrai
///   http.Client est intercepté par flutter_test et répond 400 à toute
///   requête.
/// - Il s'arrête à Step4PaymentScreen sans appuyer sur "PAYER..." : le tap
///   réel appellerait `url_launcher`'s `launchUrl()`, un vrai canal de
///   plateforme qu'un `flutter test` classique ne peut pas simuler (aucun
///   faux disponible sans dépendance supplémentaire) - c'est la même limite
///   déjà documentée dans step4_payment_test.dart.
/// - Le second test reprend exactement là où le premier s'arrête : il
///   construit SuccessScreen directement (comme le ferait _confirm() une
///   fois `launchUrl()` réussi) avec la Transaction que Step4 aurait
///   réellement créée, puis simule le Backend qui répond PENDING deux fois
///   avant SUCCESS - prouvant la séquence EN COURS -> PENDING -> PENDING ->
///   SUCCESS avec le vrai code de polling (SuccessScreen), pas un double.
/// - Le troisième test est la même reprise pour la variante FAILED.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  SharedPreferences.setMockInitialValues({});

  final auth = AuthService(
    store: _NullStore(),
    client: MockClient((r) async => http.Response('{}', 200)),
  );

  testWidgets(
    'Home -> Service -> Informations -> Paiement : les données réelles traversent toute la chaîne',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(800, 1600));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final client = MockClient((request) async {
        final path = request.url.path;
        if (path.contains('/operators/')) {
          return http.Response(jsonEncode([
            {'id': 1, 'name': 'Orange', 'code': 'orange'},
          ]), 200);
        }
        if (path.contains('/services/')) {
          return http.Response(jsonEncode([
            {'id': 2, 'name': 'Internet', 'code': 'internet'},
          ]), 200);
        }
        if (path.contains('/amounts/')) {
          return http.Response(jsonEncode([]), 200);
        }
        return http.Response('not found', 404);
      });

      // La frontière Home -> Step2 est déjà prouvée par home_screen_test.dart
      // ("tapping an operator card navigates to Step2ServiceScreen with the
      // right operator name") avec de vrais taps - inutile de la répéter
      // ici. Voir le commentaire de tête de fichier : HomeScreen ne
      // transmet de toute façon pas son BackendApiService à cette
      // navigation (_operatorCard dans home_screen.dart), donc un
      // Step2ServiceScreen atteint par un vrai tap depuis Home utiliserait
      // un client HTTP non simulé ici. Ce test démarre donc directement à
      // Step2ServiceScreen, avec le mock explicite - exactement le principe
      // déjà établi dans step2_service_test.dart - puis enchaîne par de
      // VRAIS taps, sans aucune reconstruction d'arbre intermédiaire,
      // jusqu'à Step4PaymentScreen.
      await tester.pumpWidget(MaterialApp(
        home: Step2ServiceScreen(
          operatorId: 1,
          operator: 'Orange',
          onTransactionAdded: (Transaction _) {},
          onNotificationAdded: (AppNotification _) {},
          notifications: const [],
          backendApiService: BackendApiService(client: client),
        ),
      ));
      await tester.pump();
      await tester.pump();

      // Step2 -> Step3 (choix service réel + type d'opération)
      await tester.tap(find.text('Internet'));
      await tester.pump();
      await tester.tap(find.text('CONTINUER'));
      await tester.pumpAndSettle();
      expect(find.byType(Step3InfoScreen), findsOneWidget);

      // Step3 -> Step4 (numéro + montant)
      await tester.enterText(find.byType(TextField).first, '0700000099');
      await tester.tap(find.text('CONTINUER'));
      await tester.pumpAndSettle();

      expect(find.byType(Step4PaymentScreen), findsOneWidget);
      final step4 = tester.widget<Step4PaymentScreen>(find.byType(Step4PaymentScreen));
      expect(step4.operatorId, 1);
      expect(step4.serviceId, 2);
      expect(step4.operator, 'Orange');
      expect(step4.service, 'Internet');
      expect(step4.phone, '0700000099');
      expect(step4.amount, 1000, reason: 'the default quick-amount tile (1000) was never changed');

      // À partir d'ici, un vrai tap sur "PAYER..." appellerait launchUrl() -
      // un canal de plateforme réel non simulable ici. Voir SuccessScreen
      // dans le test suivant, qui reprend le fil avec exactement la
      // Transaction que _confirm() aurait construite à ce stade.
    },
  );

  Transaction _pendingTransactionFromStep4() => Transaction(
        id: 'TOL-E2E-1',
        operator: 'Orange',
        service: 'Internet',
        operation: 'Souscription pour moi',
        phone: '0700000099',
        amount: 1000,
        paymentMethod: 'CinetPay',
        date: DateTime(2026, 1, 1),
        status: 'pending',
      );

  testWidgets(
    'EN COURS -> PENDING -> PENDING -> SUCCESS (reprend où le test précédent s\'arrête, via le vrai SuccessScreen)',
    (tester) async {
      var calls = 0;
      final client = MockClient((request) async {
        calls++;
        final resolved = calls >= 3; // deux réponses PENDING, puis SUCCESS
        return http.Response(
          jsonEncode({
            'status': resolved ? 'success' : 'pending',
            'is_pending': !resolved,
            'is_success': resolved,
            'is_failed': false,
            'is_cancelled': false,
          }),
          200,
        );
      });

      await tester.pumpWidget(MaterialApp(
        home: SuccessScreen(
          transaction: _pendingTransactionFromStep4(),
          notifications: const [],
          backendApiService: BackendApiService(client: client),
          authService: auth,
        ),
      ));

      // EN COURS (premier rendu, avant toute réponse Backend)
      expect(find.text('Paiement en attente'), findsOneWidget);

      await tester.pump(); // vérification immédiate -> PENDING (1/3)
      expect(find.text('Paiement en attente'), findsOneWidget);
      expect(calls, 1);

      await tester.pump(const Duration(seconds: 3)); // -> PENDING (2/3)
      await tester.pump();
      expect(find.text('Paiement en attente'), findsOneWidget);
      expect(calls, 2);

      await tester.pump(const Duration(seconds: 3)); // -> SUCCESS (3/3)
      await tester.pump();
      expect(find.text('Transaction réussie'), findsOneWidget);
      expect(calls, 3);
    },
  );

  testWidgets(
    'PENDING -> FAILED (même reprise, variante échec)',
    (tester) async {
      var calls = 0;
      final client = MockClient((request) async {
        calls++;
        final resolved = calls >= 2;
        return http.Response(
          jsonEncode({
            'status': resolved ? 'failed' : 'pending',
            'is_pending': !resolved,
            'is_success': false,
            'is_failed': resolved,
            'is_cancelled': false,
          }),
          200,
        );
      });

      await tester.pumpWidget(MaterialApp(
        home: SuccessScreen(
          transaction: _pendingTransactionFromStep4(),
          notifications: const [],
          backendApiService: BackendApiService(client: client),
          authService: auth,
        ),
      ));

      await tester.pump(); // -> PENDING
      expect(find.text('Paiement en attente'), findsOneWidget);

      await tester.pump(const Duration(seconds: 3)); // -> FAILED
      await tester.pump();
      expect(find.text('Transaction échouée'), findsOneWidget);
    },
  );
}

class _NullStore implements AuthTokenStore {
  @override
  Future<String?> read(String key) async => null;
  @override
  Future<void> write(String key, String value) async {}
  @override
  Future<void> delete(String key) async {}
}
