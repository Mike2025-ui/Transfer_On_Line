import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../theme/app_theme.dart';
import 'home_screen.dart';

// ═══════════════════════════════════════════════════════════════════════════
//  SPLASH SCREEN — Premier écran affiché au démarrage de l'app
//  Affiche l'animation de bienvenue pendant 2,5 secondes,
//  puis redirige automatiquement vers le HomeScreen.
// ═══════════════════════════════════════════════════════════════════════════

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();

    // Rend la barre de statut (heure, batterie) transparente sur ce fond sombre
    SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light, // Icônes blanches
    ));

    // Redirige vers HomeScreen après 2,5 secondes
    Future.delayed(const Duration(milliseconds: 2500), _goHome);
  }

  // Navigue vers l'écran principal avec une animation de fondu
  void _goHome() {
    if (!mounted) return; // Sécurité : vérifie que le widget est encore affiché
    Navigator.pushReplacement(
      context,
      PageRouteBuilder(
        pageBuilder: (_, __, ___) => const HomeScreen(),
        // Transition : fondu enchaîné (fade in/out)
        transitionsBuilder: (_, anim, __, child) =>
            FadeTransition(opacity: anim, child: child),
        transitionDuration: const Duration(milliseconds: 500),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // Fond transparent car le gradient est dans le Container ci-dessous
      backgroundColor: Colors.transparent,
      body: Container(
        width: double.infinity,
        height: double.infinity,
        // ── Fond dégradé sombre vert (identique au HomeScreen) ───────────
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              Color(0xFF031A0A), // Vert très sombre (presque noir)
              Color(0xFF062E14), // Vert sombre
              Color(0xFF0A4020), // Vert moyen
              Color(0xFF062E14), // Vert sombre (retour)
              Color(0xFF031A0A), // Vert très sombre
            ],
            stops: [0.0, 0.2, 0.5, 0.8, 1.0],
          ),
        ),
        child: SafeArea(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // ── Espace flexible en haut ─────────────────────────────────
              const Spacer(flex: 2),

              // ── Logo circulaire (flèche de transfert) ───────────────────
              // .animate() ajoute l'animation d'apparition (scale + fade)
              Container(
                width: 100, height: 100,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.orange, width: 3),
                ),
                child: Center(
                  child: Container(
                    width: 78, height: 78,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: Colors.white.withValues(alpha: 0.06),
                    ),
                    // Icône de synchronisation (double flèche circulaire)
                    child: const Icon(
                      Icons.sync_rounded,
                      color: AppColors.success, // Vert
                      size: 48,
                    ),
                  ),
                ),
              )
                  .animate()
                  // Animation d'agrandissement avec rebond élastique
                  .scale(duration: 600.ms, curve: Curves.elasticOut)
                  // Animation d'apparition en fondu
                  .fadeIn(duration: 400.ms),

              const SizedBox(height: 28),

              // ── Titre "TRANSFER" (blanc) ─────────────────────────────────
              Text(
                'TRANSFER',
                style: GoogleFonts.nunito(
                  fontSize: 38,
                  fontWeight: FontWeight.w900,
                  color: Colors.white,
                  letterSpacing: 2,
                ),
              )
                  .animate(delay: 300.ms) // Démarre 300ms après le logo
                  .slideY(begin: 0.3, end: 0, duration: 500.ms, curve: Curves.easeOut)
                  .fadeIn(duration: 500.ms),

              // ── Titre "ON LINE" (vert) ───────────────────────────────────
              Text(
                'ON LINE',
                style: GoogleFonts.nunito(
                  fontSize: 38,
                  fontWeight: FontWeight.w900,
                  color: AppColors.success, // Vert vif
                  letterSpacing: 2,
                ),
              )
                  .animate(delay: 450.ms) // 150ms après "TRANSFER"
                  .slideY(begin: 0.3, end: 0, duration: 500.ms, curve: Curves.easeOut)
                  .fadeIn(duration: 500.ms),

              const SizedBox(height: 12),

              // ── Sous-titre descriptif ──────────────────────────────────
              Text(
                'Souscrivez ou transférez vos forfaits\nen toute simplicité',
                style: GoogleFonts.nunito(
                  fontSize: 13,
                  color: Colors.white60,
                  fontWeight: FontWeight.w500,
                  height: 1.5, // Interligne 1,5
                ),
                textAlign: TextAlign.center,
              )
                  .animate(delay: 600.ms)
                  .fadeIn(duration: 500.ms),

              // ── Espace flexible au milieu ──────────────────────────────
              const Spacer(flex: 2),

              // ── Badges des opérateurs supportés ──────────────────────
              // Affiche Orange, MTN et Moov sous forme de petites étiquettes
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: ['Orange', 'MTN', 'Moov'].map((op) => Container(
                  margin: const EdgeInsets.symmetric(horizontal: 6),
                  padding: const EdgeInsets.symmetric(
                      horizontal: 14, vertical: 6),
                  decoration: BoxDecoration(
                    // Couleur de l'opérateur avec transparence
                    color: AppColors.operatorColor(op).withValues(alpha: 0.2),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(
                      color: AppColors.operatorColor(op).withValues(alpha: 0.5),
                    ),
                  ),
                  child: Text(
                    op,
                    style: GoogleFonts.nunito(
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      color: Colors.white,
                    ),
                  ),
                )).toList(),
              )
                  .animate(delay: 800.ms)
                  .fadeIn(duration: 600.ms),

              const SizedBox(height: 24),

              // ── Marque AFRITECH-CI ────────────────────────────────────
              Text(
                'AFRITECH-CI',
                style: GoogleFonts.nunito(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: Colors.white38,
                  letterSpacing: 3,
                ),
              )
                  .animate(delay: 1000.ms)
                  .fadeIn(duration: 600.ms),

              const SizedBox(height: 32),
            ],
          ),
        ),
      ),
    );
  }
}
