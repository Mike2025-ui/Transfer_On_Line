import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:local_auth/local_auth.dart';

class DeviceLockScreen extends StatefulWidget {
  const DeviceLockScreen({super.key, required this.onAuthenticated});

  final VoidCallback onAuthenticated;

  @override
  State<DeviceLockScreen> createState() => _DeviceLockScreenState();
}

class _DeviceLockScreenState extends State<DeviceLockScreen> {
  final LocalAuthentication _auth = LocalAuthentication();
  bool _loading = false;

  Future<void> _authenticate() async {
    setState(() => _loading = true);
    try {
      final canAuthenticate = await _auth.isDeviceSupported();
      if (!canAuthenticate) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Ce téléphone ne prend pas en charge le déverrouillage local.',
            ),
          ),
        );
        return;
      }

      final bool authenticated = await _auth.authenticate(
        localizedReason:
            'Vérifiez votre téléphone pour reprendre l’application.',
        options: const AuthenticationOptions(
          stickyAuth: true,
          biometricOnly: false,
        ),
      );

      if (!mounted) return;
      if (authenticated) {
        widget.onAuthenticated();
        return;
      }

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Authentification locale refusée.')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Impossible de vérifier votre appareil : $error'),
      ));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return WillPopScope(
      onWillPop: () async => false,
      child: Scaffold(
        backgroundColor: const Color(0xFF02152A),
        body: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                    width: 96,
                    height: 96,
                    decoration: const BoxDecoration(
                      color: Color(0xFF06B43E),
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.lock_outline_rounded,
                        color: Colors.white, size: 52),
                  ),
                  const SizedBox(height: 24),
                  Text(
                    'Vérification locale',
                    style: GoogleFonts.nunito(
                      fontSize: 28,
                      fontWeight: FontWeight.w900,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    'Déverrouillez votre téléphone pour réouvrir l’application.',
                    textAlign: TextAlign.center,
                    style: GoogleFonts.nunito(
                      fontSize: 16,
                      color: Colors.white70,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 28),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: _loading ? null : _authenticate,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF06B43E),
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16),
                        ),
                      ),
                      child: _loading
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : Text(
                              'VÉRIFIER LE TÉLÉPHONE',
                              style: GoogleFonts.nunito(
                                fontSize: 16,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
