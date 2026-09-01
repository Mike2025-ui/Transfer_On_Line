import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:transfer_on_line/screens/home_screen.dart';
import 'package:transfer_on_line/screens/phone_verification_screen.dart';
import 'package:transfer_on_line/services/auth_service.dart';

class _InMemoryStore implements AuthTokenStore {
  final Map<String, String> values = {};
  @override
  Future<String?> read(String key) async => values[key];
  @override
  Future<void> write(String key, String value) async => values[key] = value;
  @override
  Future<void> delete(String key) async => values.remove(key);
}

/// IKODDI is the sole OTP/SMS/WhatsApp provider - this screen only ever
/// talks to MY backend (`/auth/otp/request/`, `/auth/otp/verify/`); it
/// never contacts IKODDI directly and never sees a plaintext code. The
/// backend resolves the pending code by phone_number alone - no external
/// id to carry between request and verify.
void main() {
  Future<void> pumpScreen(WidgetTester tester, AuthService auth) async {
    await tester.pumpWidget(MaterialApp(
      home: PhoneVerificationScreen(authService: auth),
    ));
  }

  Future<void> enterPhoneAndContinue(WidgetTester tester) async {
    await tester.enterText(find.byType(TextField), '0700000001');
    await tester.tap(find.text('RECEVOIR PAR SMS'));
    await tester.pump();
  }

  testWidgets('a successful OTP request moves to the code screen', (tester) async {
    final auth = AuthService(
      store: _InMemoryStore(),
      client: MockClient((request) async {
        expect(request.url.path, contains('/auth/otp/request/'));
        return http.Response(jsonEncode({'status': 'sent', 'verification_id': 42}), 200);
      }),
    );

    await pumpScreen(tester, auth);
    await enterPhoneAndContinue(tester);
    await tester.pumpAndSettle();

    expect(find.text('Entrez le code reçu'), findsOneWidget);
    expect(find.text('482910'), findsNothing, reason: 'the backend never returns a code to the client - nothing to auto-fill');
  });

  testWidgets('a request error is shown and the screen stays on the phone step', (tester) async {
    final auth = AuthService(
      store: _InMemoryStore(),
      client: MockClient((request) async => http.Response(jsonEncode({'error': 'Unable to send verification code'}), 400)),
    );

    await pumpScreen(tester, auth);
    await enterPhoneAndContinue(tester);
    await tester.pump();

    expect(find.text('Unable to send verification code'), findsOneWidget);
    expect(find.text('Votre numéro'), findsOneWidget, reason: 'must not advance to the code step on failure');
  });

  testWidgets('a network error during the request is shown, not a crash', (tester) async {
    final auth = AuthService(
      store: _InMemoryStore(),
      client: MockClient((request) async => throw Exception('network unreachable')),
    );

    await pumpScreen(tester, auth);
    await enterPhoneAndContinue(tester);
    await tester.pump();

    expect(find.textContaining('network unreachable'), findsOneWidget);
  });

  testWidgets('shows a loading indicator while the request is in flight', (tester) async {
    final auth = AuthService(
      store: _InMemoryStore(),
      client: MockClient((request) async {
        await Future<void>.delayed(const Duration(milliseconds: 50));
        return http.Response(jsonEncode({'status': 'sent', 'verification_id': 1}), 200);
      }),
    );

    await pumpScreen(tester, auth);
    await tester.enterText(find.byType(TextField), '0700000001');
    await tester.tap(find.text('RECEVOIR PAR SMS'));
    await tester.pump();

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await tester.pumpAndSettle();
  });

  testWidgets('the button becomes a loading indicator on tap, preventing a second request', (tester) async {
    var calls = 0;
    final auth = AuthService(
      store: _InMemoryStore(),
      client: MockClient((request) async {
        calls++;
        await Future<void>.delayed(const Duration(milliseconds: 50));
        return http.Response(jsonEncode({'status': 'sent', 'verification_id': 1}), 200);
      }),
    );

    await pumpScreen(tester, auth);
    await tester.enterText(find.byType(TextField), '0700000001');
    await tester.tap(find.text('RECEVOIR PAR SMS'));
    await tester.pump();

    // The tapped button's label is replaced entirely by a spinner while
    // _loading is true - there is no "RECEVOIR PAR SMS" text left to tap a
    // second time at all (the WhatsApp button is disabled, not hidden).
    expect(find.text('RECEVOIR PAR SMS'), findsNothing, reason: 'the button must not remain tappable while the request is in flight');
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await tester.pumpAndSettle();
    expect(calls, 1, reason: 'exactly one request must have been made');
  });

  testWidgets('the WhatsApp button sends channel=whatsapp and shows a WhatsApp confirmation', (tester) async {
    Map<String, dynamic>? requestBody;
    final auth = AuthService(
      store: _InMemoryStore(),
      client: MockClient((request) async {
        requestBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(jsonEncode({'status': 'sent', 'channel': 'whatsapp'}), 200);
      }),
    );

    await pumpScreen(tester, auth);
    await tester.enterText(find.byType(TextField), '0700000001');
    await tester.tap(find.text('RECEVOIR PAR WHATSAPP'));
    await tester.pumpAndSettle();

    expect(requestBody, isNotNull);
    expect(requestBody!['channel'], 'whatsapp');
    expect(find.textContaining('WhatsApp'), findsWidgets);
  });

  testWidgets('a successful verification sends only phone_number/code and navigates to HomeScreen', (tester) async {
    Map<String, dynamic>? verifyBody;
    final auth = AuthService(
      store: _InMemoryStore(),
      client: MockClient((request) async {
        if (request.url.path.contains('/auth/otp/request/')) {
          return http.Response(jsonEncode({'status': 'sent'}), 200);
        }
        verifyBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({'access': 'a.b.c', 'refresh': 'r', 'phone_number': '+2250700000001'}),
          200,
        );
      }),
    );

    await pumpScreen(tester, auth);
    await enterPhoneAndContinue(tester);
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), '482910');
    await tester.tap(find.text('VALIDER'));
    await tester.pumpAndSettle();

    expect(verifyBody, isNotNull);
    expect(verifyBody!.containsKey('verification_id'), isFalse,
        reason: 'IKODDI/Django resolve the pending code by phone_number alone - no external id to carry');
    expect(verifyBody!['code'], '482910');
    expect(find.byType(HomeScreen), findsOneWidget);
  });

  testWidgets('an invalid code shows the backend error and stays on the code screen', (tester) async {
    final auth = AuthService(
      store: _InMemoryStore(),
      client: MockClient((request) async {
        if (request.url.path.contains('/auth/otp/request/')) {
          return http.Response(jsonEncode({'status': 'sent', 'verification_id': 42}), 200);
        }
        return http.Response(jsonEncode({'error': 'Code invalide ou expiré'}), 400);
      }),
    );

    await pumpScreen(tester, auth);
    await enterPhoneAndContinue(tester);
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), '000000');
    await tester.tap(find.text('VALIDER'));
    await tester.pump();

    expect(find.text('Code invalide ou expiré'), findsOneWidget);
    expect(find.byType(HomeScreen), findsNothing);
  });
}
