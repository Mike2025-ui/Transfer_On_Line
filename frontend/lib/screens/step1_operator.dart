// ignore_for_file: use_build_context_synchronously
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../theme/app_theme.dart';
import '../models/models.dart';
import 'step2_service.dart';
import 'notifications_screen.dart';

// ─── Step 1 : Sélection de l'opérateur ───────────────────────────────────────
// Écran d'accueil / landing page. L'utilisateur choisit son opérateur
// pour lancer le flux de souscription ou de transfert.

class Step1OperatorScreen extends StatelessWidget {
  const Step1OperatorScreen({
    super.key,
    required this.onTransactionAdded,
    required this.onNotificationAdded,
    this.preselectedOp,
  });

  final Function(Transaction) onTransactionAdded;
  final Function(AppNotification) onNotificationAdded;
  final String? preselectedOp;

  void _goToStep2(BuildContext context, String op) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => Step2ServiceScreen(
          // This screen is unreachable (never instantiated anywhere in the
          // app - confirmed dead code, HomeScreen is the real entry point)
          // and only ever carried operator names, never ids - kept
          // compiling with a placeholder rather than invented data.
          operatorId: -1,
          operator: op,
          onTransactionAdded: onTransactionAdded,
          onNotificationAdded: onNotificationAdded,
          notifications: const [],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // Si un opérateur est présélectionné, naviguer directement vers Step2
    if (preselectedOp != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _goToStep2(context, preselectedOp!);
      });
    }

    final unread = sampleNotifications.where((n) => !n.read).length;

    return Scaffold(
      body: Container(
        width: double.infinity,
        height: double.infinity,
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              Color(0xFF03100A),
              Color(0xFF071E10),
              Color(0xFF0A2A15),
              Color(0xFF071E10),
              Color(0xFF03100A),
            ],
          ),
        ),
        child: SafeArea(
          child: Column(
            children: [
              // ── Cloche de notification (haut droite) ──
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    GestureDetector(
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) => NotificationsScreen(
                              notifications: sampleNotifications),
                        ),
                      ),
                      child: Container(
                        width: 44,
                        height: 44,
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.08),
                          shape: BoxShape.circle,
                          border: Border.all(
                              color: Colors.white.withValues(alpha: 0.15)),
                        ),
                        child: Stack(
                          children: [
                            const Center(
                              child: Icon(Icons.notifications_outlined,
                                  color: Colors.white, size: 22),
                            ),
                            if (unread > 0)
                              Positioned(
                                top: 6,
                                right: 6,
                                child: Container(
                                  width: 16,
                                  height: 16,
                                  decoration: const BoxDecoration(
                                      color: AppColors.primary,
                                      shape: BoxShape.circle),
                                  child: Center(
                                    child: Text('$unread',
                                        style: const TextStyle(
                                            fontSize: 9,
                                            color: Colors.white,
                                            fontWeight: FontWeight.w900)),
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const Spacer(flex: 1),

              // ── Logo circulaire (flèches orange/vertes) ──
              Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(
                      color: AppColors.orange.withValues(alpha: 0.8), width: 3),
                ),
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    Container(
                      width: 58,
                      height: 58,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: Colors.white.withValues(alpha: 0.05),
                      ),
                    ),
                    // Flèches circulaires
                    const Icon(Icons.sync_rounded,
                        color: AppColors.success, size: 36),
                  ],
                ),
              ).animate().scale(duration: 600.ms, curve: Curves.elasticOut),

              const SizedBox(height: 14),

              // ── Titre principal ──
              Text('TRANSFER',
                      style: GoogleFonts.nunito(
                          fontSize: 34,
                          fontWeight: FontWeight.w900,
                          color: Colors.white,
                          letterSpacing: 1.5))
                  .animate(delay: 100.ms)
                  .fadeIn(duration: 400.ms)
                  .slideY(begin: 0.2, end: 0),

              Text('ON LINE',
                      style: GoogleFonts.nunito(
                          fontSize: 34,
                          fontWeight: FontWeight.w900,
                          color: AppColors.success,
                          letterSpacing: 1.5))
                  .animate(delay: 150.ms)
                  .fadeIn(duration: 400.ms)
                  .slideY(begin: 0.2, end: 0),

              const SizedBox(height: 8),

              Text(
                'Souscrivez ou transférez\nvos forfaits en toute simplicité',
                style: GoogleFonts.nunito(
                    fontSize: 13, color: Colors.white60, height: 1.5),
                textAlign: TextAlign.center,
              ).animate(delay: 200.ms).fadeIn(duration: 400.ms),

              const Spacer(flex: 1),

              // ── Icônes de service avec glow ──
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _serviceIcon(Icons.phone_rounded),
                  const SizedBox(width: 28),
                  _serviceIcon(Icons.language_rounded),
                  const SizedBox(width: 28),
                  _serviceIcon(Icons.message_rounded),
                ],
              ).animate(delay: 300.ms).fadeIn(duration: 500.ms),

              const Spacer(flex: 1),

              // ── Label opérateur ──
              Text(
                'Choisissez votre opérateur',
                style: GoogleFonts.nunito(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: Colors.white70),
              ).animate(delay: 400.ms).fadeIn(),

              const SizedBox(height: 14),

              // ── Cartes opérateurs ──
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Column(
                  children: [
                    _opCard(context, 'Orange', AppColors.orange,
                            'assets/images/Orange_logo.png')
                        .animate(delay: 450.ms)
                        .fadeIn(duration: 300.ms)
                        .slideX(begin: -0.05, end: 0),
                    const SizedBox(height: 12),
                    _opCard(context, 'MTN', AppColors.mtn,
                            'assets/images/mtn.jpg')
                        .animate(delay: 520.ms)
                        .fadeIn(duration: 300.ms)
                        .slideX(begin: -0.05, end: 0),
                    const SizedBox(height: 12),
                    _opCard(context, 'Moov', AppColors.moov,
                            'assets/images/moov.jpeg',
                            logoWhiteBg: false)
                        .animate(delay: 590.ms)
                        .fadeIn(duration: 300.ms)
                        .slideX(begin: -0.05, end: 0),
                  ],
                ),
              ),

              const Spacer(flex: 1),

              // ── Badge sécurité ──
              Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.verified_user_outlined,
                          color: AppColors.success, size: 14),
                      const SizedBox(width: 6),
                      Text('Sécurisé à 100%',
                          style: GoogleFonts.nunito(
                              fontSize: 12,
                              fontWeight: FontWeight.w800,
                              color: Colors.white70)),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text('Vos transactions sont protégées',
                      style: GoogleFonts.nunito(
                          fontSize: 11, color: Colors.white38)),
                ],
              ).animate(delay: 700.ms).fadeIn(),

              const SizedBox(height: 10),

              // ── AFRITECH-CI ──
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.shield_outlined,
                      color: AppColors.success, size: 14),
                  const SizedBox(width: 6),
                  Text('AFRITECH-CI',
                      style: GoogleFonts.nunito(
                          fontSize: 12,
                          fontWeight: FontWeight.w900,
                          color: AppColors.success,
                          letterSpacing: 2)),
                ],
              ).animate(delay: 800.ms).fadeIn(),

              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }

  // Icône de service avec cercle vert et glow
  Widget _serviceIcon(IconData icon) {
    return Container(
      width: 52,
      height: 52,
      decoration: BoxDecoration(
        color: AppColors.success.withValues(alpha: 0.2),
        shape: BoxShape.circle,
        boxShadow: [
          BoxShadow(
            color: AppColors.success.withValues(alpha: 0.35),
            blurRadius: 16,
            spreadRadius: 2,
          ),
        ],
      ),
      child: Icon(icon, color: AppColors.success, size: 24),
    );
  }

  // Carte opérateur cliquable avec fond coloré + vrai logo
  Widget _opCard(
      BuildContext context, String name, Color bgColor, String imagePath,
      {bool logoWhiteBg = true}) {
    return GestureDetector(
      onTap: () => _goToStep2(context, name),
      child: Container(
        height: 68,
        decoration: BoxDecoration(
          color: bgColor,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          children: [
            const SizedBox(width: 12),
            // Logo dans carré arrondi
            Container(
              width: 46,
              height: 46,
              decoration: BoxDecoration(
                color: logoWhiteBg ? Colors.white : Colors.transparent,
                borderRadius: BorderRadius.circular(12),
              ),
              clipBehavior: Clip.antiAlias,
              child: Image.asset(
                imagePath,
                fit: BoxFit.contain,
                errorBuilder: (_, __, ___) =>
                    Icon(Icons.business_rounded, color: Colors.white, size: 28),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Text(
                name,
                style: GoogleFonts.nunito(
                    fontSize: 20,
                    fontWeight: FontWeight.w900,
                    color: Colors.white),
              ),
            ),
            const Icon(Icons.arrow_forward_ios_rounded,
                color: Colors.white, size: 20),
            const SizedBox(width: 18),
          ],
        ),
      ),
    );
  }
}
