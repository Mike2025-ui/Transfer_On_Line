import 'dart:async';

import 'package:app_links/app_links.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'models/models.dart';
import 'screens/device_lock_screen.dart';
import 'screens/splash_screen.dart';
import 'screens/step4_payment.dart';
import 'services/transaction_service.dart';
import 'theme/app_theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
  ));
  runApp(const TransferOnLineApp());
}

class TransferOnLineApp extends StatefulWidget {
  const TransferOnLineApp({super.key});

  /// Permet l'instanciation et la vérification directe dans les tests unitaires
  /// sans monter l'arborescence des plugins biométriques.
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Transfer On Line',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.theme,
      home: DeviceLockScreen(onAuthenticated: () {}),
    );
  }

  @override
  State<TransferOnLineApp> createState() => _TransferOnLineAppState();
}

class _TransferOnLineAppState extends State<TransferOnLineApp> {
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();
  late final AppLinks _appLinks;
  StreamSubscription<Uri>? _linkSubscription;

  @override
  void initState() {
    super.initState();
    _initDeepLinks();
  }

  @override
  void dispose() {
    _linkSubscription?.cancel();
    super.dispose();
  }

  Future<void> _initDeepLinks() async {
    _appLinks = AppLinks();
    try {
      final initialUri = await _appLinks.getInitialLink();
      if (initialUri != null) {
        _handleDeepLink(initialUri);
      }
    } catch (_) {}

    _linkSubscription = _appLinks.uriLinkStream.listen(
      (uri) => _handleDeepLink(uri),
      onError: (_) {},
    );
  }

  void _handleDeepLink(Uri uri) {
    if (uri.scheme == 'transfertonline' && uri.host == 'payment') {
      final reference = uri.queryParameters['reference'];
      final status = uri.queryParameters['status'];
      if (reference != null && reference.isNotEmpty) {
        _navigateToTransactionStatus(reference, status);
      }
    }
  }

  Future<void> _navigateToTransactionStatus(
      String reference, String? rawStatus) async {
    final status = rawStatus?.toLowerCase();
    final localStatus =
        (status == 'accepted' || status == 'success' || status == 'ok')
            ? 'ok'
            : (status == 'cancelled' || status == 'canceled'
                ? 'cancelled'
                : (status == 'pending' ? 'pending' : 'fail'));

    final saved = await TransactionService.load();
    final existing = saved.cast<Transaction?>().firstWhere(
          (t) => t?.id == reference,
          orElse: () => null,
        );

    final tx = existing != null
        ? Transaction(
            id: existing.id,
            operator: existing.operator,
            service: existing.service,
            operation: existing.operation,
            phone: existing.phone,
            amount: existing.amount,
            paymentMethod: existing.paymentMethod,
            date: existing.date,
            status: localStatus,
          )
        : Transaction(
            id: reference,
            operator: 'Transfer On Line',
            service: 'Souscription',
            operation: 'Souscription',
            phone: '',
            amount: 0,
            paymentMethod: 'Jeko',
            date: DateTime.now(),
            status: localStatus,
          );

    _navigatorKey.currentState?.push(
      MaterialPageRoute(
        builder: (_) => SuccessScreen(
          transaction: tx,
          notifications: const [],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: _navigatorKey,
      title: 'Transfer On Line',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.theme,
      home: DeviceLockScreen(
        onAuthenticated: () {
          _navigatorKey.currentState?.pushReplacement(
            MaterialPageRoute(builder: (_) => const SplashScreen()),
          );
        },
      ),
    );
  }
}
