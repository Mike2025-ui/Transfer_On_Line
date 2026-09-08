import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'screens/device_lock_screen.dart';
import 'screens/splash_screen.dart';
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

  @override
  State<TransferOnLineApp> createState() => _TransferOnLineAppState();
}

class _TransferOnLineAppState extends State<TransferOnLineApp> {
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();

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
