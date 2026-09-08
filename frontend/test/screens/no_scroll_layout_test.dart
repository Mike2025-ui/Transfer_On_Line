import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:transfer_on_line/models/models.dart';
import 'package:transfer_on_line/screens/home_screen.dart';
import 'package:transfer_on_line/screens/step2_service.dart';
import 'package:transfer_on_line/screens/step3_info.dart';
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
  const phone = '0700000001';
  final auth = AuthService(
    store: _NullStore(),
    client: MockClient((request) async => http.Response('{}', 200)),
  );
  final api = BackendApiService(
    client: MockClient((request) async => http.Response(jsonEncode([]), 200)),
  );

  Future<void> pumpAtS8(WidgetTester tester, Widget child) async {
    await tester.binding.setSurfaceSize(const Size(360, 740));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(home: child));
    await tester.pump();
    await tester.pump();
    expect(tester.takeException(), isNull);
  }

  testWidgets('les écrans du tunnel restent visibles sur une hauteur S8',
      (tester) async {
    SharedPreferences.setMockInitialValues({});

    await pumpAtS8(
      tester,
      HomeScreen(backendApiService: api, authService: auth),
    );
    expect(find.byType(SingleChildScrollView), findsNothing);

    await pumpAtS8(
      tester,
      Step2ServiceScreen(
        operatorId: 1,
        operator: 'Orange',
        onTransactionAdded: (_) {},
        onNotificationAdded: (_) {},
        notifications: const [],
        backendApiService: api,
      ),
    );
    expect(find.byType(SingleChildScrollView), findsNothing);

    await pumpAtS8(
      tester,
      Step3InfoScreen(
        operatorId: 1,
        serviceId: 1,
        operator: 'Orange',
        service: 'Internet (Pass data)',
        operation: 'Souscription pour moi',
        onTransactionAdded: (_) {},
        onNotificationAdded: (_) {},
        notifications: const [],
        backendApiService: api,
      ),
    );
    expect(find.byType(SingleChildScrollView), findsNothing);

    await pumpAtS8(
      tester,
      Step4PaymentScreen(
        operatorId: 1,
        serviceId: 1,
        operator: 'Orange',
        service: 'Internet (Pass data)',
        operation: 'Souscription pour moi',
        phone: phone,
        amount: 1000,
        onTransactionAdded: (_) {},
        onNotificationAdded: (_) {},
        notifications: const [],
        backendApiService: api,
        authService: auth,
      ),
    );
    expect(find.byType(SingleChildScrollView), findsNothing);
  });
}
