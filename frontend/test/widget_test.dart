// Smoke test for the real app root, TransferOnLineApp (see lib/main.dart).
//
// This used to be Flutter's default counter-app boilerplate, still testing
// a `MyApp`/`Icons.add` counter widget that was renamed away long ago and no
// longer exists anywhere in this project - it only ever failed to compile,
// it never verified anything about this app.
//
// TransferOnLineApp.build() hardcodes `home: const SplashScreen()`, and
// SplashScreen.initState() unconditionally kicks off a real
// AuthService().restoreSession() call (a real flutter_secure_storage
// platform-channel read, which has no in-memory fake in a plain
// `flutter test` run - see AuthTokenStore's own doc comment in
// lib/services/auth_service.dart) plus a 2.5s Future.delayed. SplashScreen
// exposes no injection seam (unlike e.g. Step4PaymentScreen), and adding
// one is out of scope here.
//
// So this test deliberately never calls tester.pumpWidget(TransferOnLineApp())
// - doing so would mount SplashScreen for real, hit that uncachable platform
// channel, and leave a 2.5s Timer pending past the end of the test (Flutter's
// test binding fails a test over exactly that). Calling .build() directly
// exercises the real, unmodified production code (main.dart is untouched)
// without ever mounting the widget it returns, which is what keeps this
// deterministic and network-free while still proving the app root builds
// without throwing and is wired the way main.dart actually uses it.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:transfer_on_line/main.dart';
import 'package:transfer_on_line/screens/splash_screen.dart';
import 'package:transfer_on_line/theme/app_theme.dart';

void main() {
  testWidgets(
    'TransferOnLineApp builds a MaterialApp shell wired to SplashScreen, without mounting it',
    (WidgetTester tester) async {
      // A real, mounted BuildContext, borrowed from an unrelated, inert
      // widget - TransferOnLineApp.build() never reads its context argument,
      // so this is only here to satisfy the method signature.
      await tester.pumpWidget(const MaterialApp(home: SizedBox()));
      final context = tester.element(find.byType(SizedBox));

      final built = const TransferOnLineApp().build(context);

      expect(built, isA<MaterialApp>());
      final app = built as MaterialApp;
      expect(app.title, 'Transfer On Line');
      expect(app.debugShowCheckedModeBanner, isFalse);
      expect(app.theme, AppTheme.theme);
      expect(app.home, isA<SplashScreen>());
    },
  );
}
