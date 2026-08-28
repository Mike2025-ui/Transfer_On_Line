import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import '../services/auth_service.dart';
import '../services/otp_service.dart';
import '../theme/app_theme.dart';
import 'home_screen.dart';

/// Shown only on a first install or on a device the backend no longer
/// recognizes (see AuthService.restoreSession) - never on every app open.
/// Two steps: phone number, then the OTP sent to it by SMS via Aion Messaging.
///
/// Aion Messaging Integration:
/// - /verify/start endpoint sends OTP code via SMS
/// - /verify/check endpoint validates the submitted code
/// - Handles rate limiting, retries, and resend functionality
class PhoneVerificationScreen extends StatefulWidget {
  const PhoneVerificationScreen({super.key, this.authService, this.otpService});

  final AuthService? authService;
  final OtpService? otpService;

  @override
  State<PhoneVerificationScreen> createState() =>
      _PhoneVerificationScreenState();
}

class _PhoneVerificationScreenState extends State<PhoneVerificationScreen> {
  late final AuthService _auth = widget.authService ?? AuthService();
  late final OtpService _otpService = widget.otpService ?? OtpService();

  final _phoneCtrl = TextEditingController();
  final _codeCtrl = TextEditingController();

  bool _codeSent = false;
  bool _loading = false;
  String _phoneNumber = '';
  int? _verificationId;

  // Resend timer management
  Timer? _resendTimer;
  int _secondsUntilResend = 0;
  bool _canResend = false;

  @override
  void dispose() {
    _phoneCtrl.dispose();
    _codeCtrl.dispose();
    _resendTimer?.cancel();
    super.dispose();
  }

  Future<void> _requestCode() async {
    final phone = _phoneCtrl.text.trim();

    // Validate phone number
    if (!OtpService.isValidPhoneNumber(phone)) {
      _showError('Numéro invalide. Entrez 10 chiffres (ex: 07XXXXXXXX)');
      return;
    }

    setState(() => _loading = true);
    try {
      _phoneNumber = phone;
      final otpRequest = await _otpService.requestOtp(_phoneNumber);

      if (!mounted) return;

      setState(() {
        _verificationId = otpRequest.verificationId;
        _codeSent = true;
      });

      _startResendTimer();
      _showSuccess('Code de vérification envoyé par SMS');
    } catch (error) {
      if (mounted) {
        _showError(error.toString().replaceFirst('Exception: ', ''));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _verifyCode() async {
    final code = _codeCtrl.text.trim();

    if (code.isEmpty || code.length < 4) {
      _showError('Entrez le code reçu par SMS');
      return;
    }

    final verificationId = _verificationId;
    if (verificationId == null) {
      _showError('Veuillez demander un nouveau code');
      return;
    }

    setState(() => _loading = true);
    try {
          // The backend verifies the code with Aion and persists the JWT tokens.
          await _auth.verifyOtp(_phoneNumber, code, verificationId);
      
          if (!mounted) return;
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(builder: (_) => const HomeScreen()),
          );
    } catch (error) {
      if (mounted) {
        _showError(error.toString().replaceFirst('Exception: ', ''));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _resendCode() async {
    if (!_canResend) {
      _showError('Attendez avant de redemander un code');
      return;
    }

    setState(() => _loading = true);
    try {
      final otpRequest = await _otpService.requestResend(_phoneNumber);

      if (!mounted) return;

      setState(() => _verificationId = otpRequest.verificationId);
      _codeCtrl.clear();
      _startResendTimer();
      _showSuccess('Nouveau code envoyé par SMS');
    } catch (error) {
      if (mounted) {
        _showError(error.toString().replaceFirst('Exception: ', ''));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _startResendTimer() {
    _resendTimer?.cancel();
    setState(() {
      _secondsUntilResend = 60;
      _canResend = false;
    });

    _resendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      setState(() {
        _secondsUntilResend--;
        if (_secondsUntilResend <= 0) {
          _canResend = true;
          _resendTimer?.cancel();
        }
      });
    });
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.red.shade700,
        duration: const Duration(seconds: 4),
      ),
    );
  }

  void _showSuccess(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: AppColors.success,
        duration: const Duration(seconds: 3),
      ),
    );
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
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      TextButton(
                        onPressed: _canResend && !_loading ? _resendCode : null,
                        child: Text(
                          _canResend
                              ? 'Renvoyer le code'
                              : 'Renvoyer (${_secondsUntilResend}s)',
                          style: GoogleFonts.nunito(
                            color:
                                _canResend ? AppColors.success : Colors.white38,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
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
