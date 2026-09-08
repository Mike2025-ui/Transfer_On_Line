import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme/app_theme.dart';
import 'home_screen.dart';

/// Ce parcours est conservé uniquement pour compatibilité UI, mais il ne
/// demande plus d’OTP ni de JWT. Le téléphone est simplement utilisé comme
/// entrée du flux de transaction et le verrouillage de l’app se fait par le
/// système de l’appareil (empreinte / mot de passe) sans collecte
/// d’informations complémentaires.
class PhoneVerificationScreen extends StatefulWidget {
  const PhoneVerificationScreen({super.key});

  @override
  State<PhoneVerificationScreen> createState() =>
      _PhoneVerificationScreenState();
}

class _PhoneVerificationScreenState extends State<PhoneVerificationScreen> {
  final _phoneCtrl = TextEditingController();
  final _codeCtrl = TextEditingController();

  bool _codeSent = false;
  bool _loading = false;
  String _phoneNumber = '';

  // Resend cooldown - a UI convenience only (not a security control; the
  // backend's own 3-attempts/5-minutes limit, see OTP_MAX_ATTEMPTS/
  // OTP_TTL_MINUTES in apps.accounts.services.otp_service, is what actually
  // protects the OTP).
  Timer? _resendTimer;
  int _secondsUntilResend = 0;

  @override
  void dispose() {
    _phoneCtrl.dispose();
    _codeCtrl.dispose();
    _resendTimer?.cancel();
    super.dispose();
  }

  Future<void> _requestCode() async {
    if (_phoneCtrl.text.length != 10) {
      _showError('Le numéro doit contenir 10 chiffres');
      return;
    }
    setState(() => _loading = true);
    try {
      _phoneNumber = _phoneCtrl.text;
      if (!mounted) return;
      setState(() => _codeSent = true);
      _startResendCooldown();
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _verifyCode() async {
    if (_codeCtrl.text.length < 4) {
      _showError('Entrez le code reçu par SMS');
      return;
    }
    setState(() => _loading = true);
    try {
      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const HomeScreen()),
      );
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _resendCode() async {
    if (_secondsUntilResend > 0) return;
    setState(() => _loading = true);
    try {
      _codeCtrl.clear();
      _startResendCooldown();
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _startResendCooldown() {
    _resendTimer?.cancel();
    setState(() => _secondsUntilResend = 60);
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() {
        _secondsUntilResend--;
        if (_secondsUntilResend <= 0) _resendTimer?.cancel();
      });
    });
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Container(
        width: double.infinity,
        height: double.infinity,
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              Color(0xFF031A0A),
              Color(0xFF062E14),
              Color(0xFF0A4020),
              Color(0xFF062E14),
              Color(0xFF031A0A),
            ],
            stops: [0.0, 0.2, 0.5, 0.8, 1.0],
          ),
        ),
        child: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(28, 48, 28, 32),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Icon(
                  _codeSent ? Icons.sms_outlined : Icons.phone_iphone_rounded,
                  color: AppColors.success,
                  size: 56,
                ),
                const SizedBox(height: 20),
                Text(
                  _codeSent ? 'Entrez le code reçu' : 'Votre numéro',
                  style: GoogleFonts.nunito(
                    fontSize: 26,
                    fontWeight: FontWeight.w900,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  _codeSent
                      ? 'Un code a été envoyé par SMS au $_phoneNumber.'
                      : 'Il sert à identifier votre compte. Un code de vérification vous sera envoyé par SMS.',
                  style: GoogleFonts.nunito(
                    fontSize: 15,
                    color: Colors.white60,
                    fontWeight: FontWeight.w500,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 32),
                if (!_codeSent) ...[
                  _fieldShell(
                    child: TextField(
                      controller: _phoneCtrl,
                      keyboardType: TextInputType.phone,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      style: _fieldStyle(),
                      decoration: _fieldDecoration('Exemple : 07XXXXXXXX'),
                    ),
                  ),
                  const SizedBox(height: 24),
                  _submitButton('CONTINUER', _requestCode),
                ] else ...[
                  _fieldShell(
                    child: TextField(
                      controller: _codeCtrl,
                      keyboardType: TextInputType.number,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      style: _fieldStyle(),
                      decoration: _fieldDecoration('Code à 6 chiffres'),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      TextButton(
                        onPressed: _loading
                            ? null
                            : () => setState(() => _codeSent = false),
                        child: Text(
                          'Changer de numéro',
                          style: GoogleFonts.nunito(
                              color: Colors.white60,
                              fontWeight: FontWeight.w700),
                        ),
                      ),
                      TextButton(
                        onPressed: _secondsUntilResend == 0 && !_loading
                            ? _resendCode
                            : null,
                        child: Text(
                          _secondsUntilResend == 0
                              ? 'Renvoyer le code'
                              : 'Renvoyer (${_secondsUntilResend}s)',
                          style: GoogleFonts.nunito(
                            color: _secondsUntilResend == 0
                                ? AppColors.success
                                : Colors.white38,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  _submitButton('VALIDER', _verifyCode),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _fieldShell({required Widget child}) {
    return Container(
      height: 60,
      padding: const EdgeInsets.symmetric(horizontal: 18),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white.withValues(alpha: 0.18)),
      ),
      child: Center(child: child),
    );
  }

  TextStyle _fieldStyle() => GoogleFonts.nunito(
        fontSize: 17,
        fontWeight: FontWeight.w700,
        color: Colors.white,
      );

  InputDecoration _fieldDecoration(String hint) => InputDecoration(
        hintText: hint,
        hintStyle: GoogleFonts.nunito(
            color: Colors.white38, fontWeight: FontWeight.w600),
        border: InputBorder.none,
      );

  Widget _submitButton(String label, VoidCallback onTap) {
    return SizedBox(
      height: 58,
      child: ElevatedButton(
        onPressed: _loading ? null : onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.success,
          foregroundColor: Colors.white,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          elevation: 6,
        ),
        child: _loading
            ? const SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(
                    color: Colors.white, strokeWidth: 2.4),
              )
            : Text(
                label,
                style: GoogleFonts.nunito(
                    fontSize: 17, fontWeight: FontWeight.w900),
              ),
      ),
    );
  }
}
