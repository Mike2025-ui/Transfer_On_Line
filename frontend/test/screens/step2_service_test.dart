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
    // The real screen content (services + all 4 operation rows) is taller
    // than the default 800x600 test surface - widen it so tap() can reach
    // widgets like "CONTINUER" without needing to scroll them into view.
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

  testWidgets('shows a loading indicator while services are being fetched', (tester) async {
    final client = MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpStep2(tester, client);

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    // The operation block does not depend on the services fetch.
    expect(find.text('Souscription pour moi'), findsOneWidget);
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

    expect(find.text('Internet'), findsOneWidget);
    expect(find.text('Appels'), findsOneWidget);
    // A never-returned service (representing one deactivated on the
    // backend) must never appear just because it exists elsewhere.
    expect(find.text('SMS'), findsNothing);
  });

  testWidgets('shows an empty-state message when the backend has no active services', (tester) async {
    final client = MockClient((request) async => http.Response(jsonEncode([]), 200));

    await pumpStep2(tester, client);
    await tester.pump();
    await tester.pump();

    expect(find.text('Aucun service disponible.'), findsOneWidget);
  });

  testWidgets('shows an error message with a retry button on failure, and retry recovers', (tester) async {
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

    expect(find.text('Impossible de charger les services.'), findsOneWidget);
    expect(find.text('RÉESSAYER'), findsOneWidget);

    await tester.tap(find.text('RÉESSAYER'));
    await tester.pump();
    await tester.pump();

    expect(find.text('Internet'), findsOneWidget);
    expect(calls, 2);
  });

  testWidgets('selecting a service and continuing passes the real service name to Step3InfoScreen', (tester) async {
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

    await tester.tap(find.text('Appels'));
    await tester.pump();
    await tester.tap(find.text('CONTINUER'));
    await tester.pumpAndSettle();

    expect(find.byType(Step3InfoScreen), findsOneWidget);
    final step3 = tester.widget<Step3InfoScreen>(find.byType(Step3InfoScreen));
    expect(step3.service, 'Appels');
    expect(step3.serviceId, 2);
    expect(step3.operator, 'Orange');
    expect(step3.operatorId, 1);
  });
}
