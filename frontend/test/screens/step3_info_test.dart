import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:transfer_on_line/models/models.dart';
import 'package:transfer_on_line/screens/step3_info.dart';
import 'package:transfer_on_line/screens/step4_payment.dart';
import 'package:transfer_on_line/services/backend_api_service.dart';

void main() {
  Future<void> pumpStep3(WidgetTester tester, http.Client client) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: Step3InfoScreen(
        operatorId: 1,
        serviceId: 2,
        operator: 'Orange',
        service: 'Internet',
        operation: 'Souscription pour moi',
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
      ),
    ));
  }

  testWidgets(
      'shows the existing default amounts immediately - no loading state, ever',
      (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    // Deliberately not pumping past the first frame - proves the default
    // tiles are already correct before the fetch has any chance to resolve.
    await pumpStep3(tester, client);

    expect(find.text('200f'), findsOneWidget);
    expect(find.text('500f'), findsOneWidget);
    expect(find.text('1000f'), findsOneWidget);
    expect(find.text('Autre'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });

  testWidgets(
      'replaces the quick-amount tiles when the backend has specific amounts configured',
      (tester) async {
    final client = MockClient((request) async {
      expect(request.url.path, contains('/operators/1/services/2/amounts/'));
      return http.Response(
        jsonEncode([
          {'amount': 300},
          {'amount': 700},
        ]),
        200,
      );
    });

    await pumpStep3(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('200f'), findsOneWidget);
    expect(find.text('500f'), findsOneWidget);
    expect(find.text('1000f'), findsOneWidget);
    expect(find.text('300f'), findsNothing);
  });

  testWidgets('an empty amounts list leaves the default tiles untouched',
      (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpStep3(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('200f'), findsOneWidget);
    expect(find.text('500f'), findsOneWidget);
    expect(find.text('1000f'), findsOneWidget);
  });

  testWidgets(
      'a network error leaves the default tiles untouched - no error message shown',
      (tester) async {
    final client = MockClient(
        (request) async => http.Response('Internal Server Error', 500));

    await pumpStep3(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('200f'), findsOneWidget);
    expect(find.text('500f'), findsOneWidget);
    expect(find.text('1000f'), findsOneWidget);
    expect(find.textContaining('Impossible'), findsNothing);
  });

  testWidgets('aucun bouton de montant personnalisé n’est affiché',
      (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpStep3(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Autre'), findsNothing);
  });

  testWidgets(
      'continuing navigates to Step4PaymentScreen with the same arguments as before',
      (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpStep3(tester, client);
    await tester.pump();
    await tester.pump();

    await tester.enterText(find.byType(TextField).first, '0700000001');
    await tester.tap(find.text('CONTINUER'));
    await tester.pumpAndSettle();

    expect(find.byType(Step4PaymentScreen), findsOneWidget);
    final step4 =
        tester.widget<Step4PaymentScreen>(find.byType(Step4PaymentScreen));
    expect(step4.operatorId, 1);
    expect(step4.serviceId, 2);
    expect(step4.operator, 'Orange');
    expect(step4.service, 'Internet');
    expect(step4.operation, 'Souscription pour moi');
    expect(step4.phone, '0700000001');
    expect(step4.amount, 1000);
  });

  testWidgets('adapts the operator instruction to MTN', (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: Step3InfoScreen(
        operatorId: 2,
        serviceId: 2,
        operator: 'MTN',
        service: 'Internet',
        operation: 'Souscription pour moi',
        onTransactionAdded: (Transaction _) {},
        onNotificationAdded: (AppNotification _) {},
        notifications: const [],
        backendApiService: BackendApiService(client: client),
      ),
    ));

    expect(find.text('Saisissez votre numéro MTN.'), findsOneWidget);
  });

  testWidgets('refuses an MTN number when Orange is selected', (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpStep3(tester, client);
    await tester.enterText(find.byType(TextField).first, '0500000001');
    await tester.pump();

    expect(find.text('Ce numéro ne correspond pas à l’opérateur Orange.'),
        findsOneWidget);
    await tester.tap(find.text('CONTINUER'));
    await tester.pumpAndSettle();

    expect(find.byType(Step4PaymentScreen), findsNothing);
  });

  testWidgets('refuses a non catalog amount such as 123', (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpStep3(tester, client);
    await tester.enterText(find.byType(TextField).first, '0700000001');
    await tester.enterText(find.byType(TextField).at(1), '123');
    await tester.pump();

    expect(find.text('Montant non disponible. Choisissez un montant valide.'),
        findsOneWidget);
    await tester.tap(find.text('CONTINUER'));
    await tester.pumpAndSettle();
    expect(find.byType(Step4PaymentScreen), findsNothing);
  });
}
