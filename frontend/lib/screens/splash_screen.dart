import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:local_auth/local_auth.dart';
import '../services/auth_service.dart';
import '../services/backend_api_service.dart';
import 'device_lock_screen.dart';
import 'home_screen.dart';

class SplashScreen extends StatefulWidget {
  final BackendApiService? backendApiService;
  final AuthService? authService;
  final LocalAuthentication? localAuth;

  const SplashScreen({
    super.key,
    this.backendApiService,
    this.authService,
    this.localAuth,
  });

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  late final LocalAuthentication _auth =
      widget.localAuth ?? LocalAuthentication();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _checkLocalAuth());
  }

  Future<void> _checkLocalAuth() async {
    try {
      final isSupported = await _auth.isDeviceSupported();
      final canCheckBiometrics = await _auth.canCheckBiometrics;
      if (!isSupported && !canCheckBiometrics) {
        _goToHome();
        return;
      }

      final authenticated = await _auth.authenticate(
        localizedReason: 'Déverrouillez pour accéder à Transfer On Line',
        options: const AuthenticationOptions(
          stickyAuth: true,
          biometricOnly: false,
        ),
      );

      if (!mounted) return;
      if (authenticated) {
        _goToHome();
      } else {
        _goToLock();
      }
    } catch (_) {
      if (!mounted) return;
      _goToLock();
    }
  }

  void _goToHome() {
    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (_) => HomeScreen(
          backendApiService: widget.backendApiService ?? BackendApiService(),
          authService: widget.authService ?? AuthService(),
        ),
      ),
    );
  }

  void _goToLock() {
    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (_) => DeviceLockScreen(
          localAuth: _auth,
          onAuthenticated: _goToHome,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF02152A),
      body: Container(
        width: double.infinity,
        height: double.infinity,
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              Color(0xFF031529),
              Color(0xFF041D2F),
              Color(0xFF052A32),
              Color(0xFF041D2F),
              Color(0xFF031529),
            ],
          ),
        ),
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Image.asset(
                'assets/images/app_logo.png',
                width: 120,
                height: 120,
                fit: BoxFit.contain,
                errorBuilder: (_, __, ___) => const Icon(
                  Icons.sync_rounded,
                  color: Color(0xFF0BA23E),
                  size: 80,
                ),
              ),
              const SizedBox(height: 24),
              Text(
                'TRANSFER ON LINE',
                style: GoogleFonts.nunito(
                  fontSize: 24,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 1.2,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 20),
              const SizedBox(
                width: 28,
                height: 28,
                child: CircularProgressIndicator(
                  strokeWidth: 2.5,
                  color: Color(0xFF06B43E),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
