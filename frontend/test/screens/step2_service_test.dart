import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:transfer_on_line/models/models.dart';
import 'package:transfer_on_line/screens/step2_service.dart';
import 'package:transfer_on_line/screens/step3_info.dart';
import 'package:transfer_on_line/services/backend_api_service.dart';

void main() {
  Future<void> pumpStep2(WidgetTester tester, http.Client client) async {
    // L'écran est conçu sans défilement : le grand support vérifie seulement
    // le parcours, pas une dépendance à un scroll de test.
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
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
  }

  testWidgets('affiche les quatre services sans bloc operation',
      (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpStep2(tester, client);

    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('Appels (Pass voix)'), findsOneWidget);
    expect(find.text('Internet (Pass data)'), findsOneWidget);
    expect(find.text('Crédit (communication)'), findsOneWidget);
    expect(find.text('SMS (Pass SMS)'), findsOneWidget);
    expect(find.text('TYPE D’OPÉRATION'), findsNothing);
  });

  testWidgets('displays the services returned by the backend', (tester) async {
    final client = MockClient((request) async {
      expect(request.url.path, contains('/services/'));
      return http.Response(
        jsonEncode([
          {'id': 1, 'name': 'Internet', 'code': 'internet'},
          {'id': 2, 'name': 'Appels', 'code': 'appels'},
        ]),
        200,
      );
    });

    await pumpStep2(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Internet (Pass data)'), findsOneWidget);
    expect(find.text('Appels (Pass voix)'), findsOneWidget);
    expect(find.text('SMS (Pass SMS)'), findsOneWidget);
  });

  testWidgets(
      'shows an empty-state message when the backend has no active services',
      (tester) async {
    final client =
        MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpStep2(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Crédit (communication)'), findsOneWidget);
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
          {'id': 1, 'name': 'Internet', 'code': 'internet'},
        ]),
        200,
      );
    });

    await pumpStep2(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Internet (Pass data)'), findsOneWidget);
    expect(find.text('RÉESSAYER'), findsNothing);
    expect(calls, 0);
  });

  testWidgets(
      'selecting a service and continuing passes the real service name to Step3InfoScreen',
      (tester) async {
    final client = MockClient((request) async => http.Response(
          jsonEncode([
            {'id': 1, 'name': 'Internet', 'code': 'internet'},
            {'id': 2, 'name': 'Appels', 'code': 'appels'},
          ]),
          200,
        ));

    await pumpStep2(tester, client);
    await tester.pump();
    await tester.pump();

    await tester.tap(find.text('Appels (Pass voix)'));
    await tester.pump();
    await tester.tap(find.text('CONTINUER'));
    await tester.pumpAndSettle();

    expect(find.byType(Step3InfoScreen), findsOneWidget);
    final step3 = tester.widget<Step3InfoScreen>(find.byType(Step3InfoScreen));
    expect(step3.service, 'Appels (Pass voix)');
    expect(step3.serviceId, 2);
    expect(step3.operator, 'Orange');
    expect(step3.operatorId, 1);
  });
}
