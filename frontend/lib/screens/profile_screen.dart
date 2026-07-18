import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../theme/app_theme.dart';
import '../models/models.dart';

// ─── Profile Screen — Profil utilisateur ─────────────────────────────────────
// Affiche les informations de l'utilisateur, ses statistiques et ses paramètres.

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  // Données de démo pour la présentation
  static const _name = 'Konan Yves';
  static const _email = 'k.yves@afritech-ci.com';
  static const _phone = '07 01 23 45 67';
  static const _memberSince = 'Membre depuis Jan 2025';

  @override
  Widget build(BuildContext context) {
    final txns = sampleTransactions;
    final totalOk = txns.where((t) => t.status == 'ok').fold(0, (a, t) => a + t.amount);
    final okCount = txns.where((t) => t.status == 'ok').length;
    final pct = txns.isEmpty ? 0 : (okCount / txns.length * 100).round();

    return Scaffold(
      backgroundColor: AppColors.background,
      body: CustomScrollView(
        slivers: [
          // ── Header ──
          SliverToBoxAdapter(child: _buildHeader(context)),

          // ── Statistiques ──
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 20),
                  Text('Mes statistiques',
                      style: GoogleFonts.nunito(
                          fontSize: 14,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textPrimary))
                      .animate().fadeIn(delay: 200.ms),
                  const SizedBox(height: 12),
                  Row(children: [
                    Expanded(child: _statCard('Total dépensé', _fmtAmt(totalOk), 'FCFA', AppColors.primary)),
                    const SizedBox(width: 10),
                    Expanded(child: _statCard('Transactions', '${txns.length}', 'opérations', AppColors.blue)),
                    const SizedBox(width: 10),
                    Expanded(child: _statCard('Réussite', '$pct%', '$okCount réussies', AppColors.success)),
                  ]).animate().fadeIn(delay: 300.ms),
                ],
              ),
            ),
          ),

          // ── Opérateurs favoris ──
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 20, 16, 0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Opérateurs utilisés',
                      style: GoogleFonts.nunito(
                          fontSize: 14,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textPrimary)),
                  const SizedBox(height: 12),
                  ..._buildOperatorStats(txns),
                ],
              ).animate().fadeIn(delay: 400.ms),
            ),
          ),

          // ── Menu paramètres ──
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 20, 16, 0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Paramètres',
                      style: GoogleFonts.nunito(
                          fontSize: 14,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textPrimary)),
                  const SizedBox(height: 12),
                  _menuCard([
                    _menuItem(Icons.person_outline_rounded, 'Modifier le profil', AppColors.blue),
                    _menuItem(Icons.lock_outline_rounded, 'Sécurité & mot de passe', AppColors.amber),
                    _menuItem(Icons.notifications_outlined, 'Préférences de notifications', AppColors.primary),
                    _menuItem(Icons.language_rounded, 'Langue', AppColors.purple),
                  ]),
                ],
              ).animate().fadeIn(delay: 500.ms),
            ),
          ),

          // ── Bouton déconnexion ──
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(children: [
                const SizedBox(height: 8),
                _menuCard([
                  _menuItem(Icons.help_outline_rounded, 'Aide & Support', AppColors.textSecondary),
                  _menuItem(Icons.info_outline_rounded, 'À propos de l\'app', AppColors.textSecondary),
                ]),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: OutlinedButton.icon(
                    onPressed: () {},
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: AppColors.red, width: 1.5),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                    ),
                    icon: const Icon(Icons.logout_rounded, color: AppColors.red, size: 20),
                    label: Text('Déconnexion',
                        style: GoogleFonts.nunito(
                            fontSize: 15,
                            fontWeight: FontWeight.w800,
                            color: AppColors.red)),
                  ),
                ),
                const SizedBox(height: 8),
                Text('Transfer On Line · AFRITECH-CI · v1.0.0',
                    style: GoogleFonts.nunito(
                        fontSize: 11,
                        color: AppColors.textHint)),
                const SizedBox(height: 20),
              ]).animate().fadeIn(delay: 600.ms),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    return Container(
      width: double.infinity,
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF0D5C2C), Color(0xFF1A7A3C)],
        ),
      ),
      padding: EdgeInsets.only(
        top: MediaQuery.of(context).padding.top + 20,
        left: 20,
        right: 20,
        bottom: 30,
      ),
      child: Column(
        children: [
          // Avatar avec initiales
          Container(
            width: 84,
            height: 84,
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.15),
              shape: BoxShape.circle,
              border: Border.all(color: Colors.white.withValues(alpha: 0.3), width: 2),
            ),
            child: Center(
              child: Text(
                _name.split(' ').map((p) => p[0]).take(2).join(),
                style: GoogleFonts.nunito(
                    fontSize: 32, fontWeight: FontWeight.w900, color: Colors.white),
              ),
            ),
          ).animate().scale(duration: 500.ms, curve: Curves.elasticOut),

          const SizedBox(height: 14),

          Text(_name,
              style: GoogleFonts.nunito(
                  fontSize: 22, fontWeight: FontWeight.w900, color: Colors.white))
              .animate(delay: 100.ms).fadeIn(),

          const SizedBox(height: 4),

          Text(_email,
              style: GoogleFonts.nunito(fontSize: 13, color: Colors.white60))
              .animate(delay: 150.ms).fadeIn(),

          const SizedBox(height: 4),

          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            const Icon(Icons.phone_rounded, color: Colors.white38, size: 14),
            const SizedBox(width: 4),
            Text(_phone,
                style: GoogleFonts.nunito(fontSize: 12, color: Colors.white54)),
            const SizedBox(width: 16),
            const Icon(Icons.calendar_today_rounded, color: Colors.white38, size: 14),
            const SizedBox(width: 4),
            Text(_memberSince,
                style: GoogleFonts.nunito(fontSize: 12, color: Colors.white54)),
          ]).animate(delay: 200.ms).fadeIn(),
        ],
      ),
    );
  }

  List<Widget> _buildOperatorStats(List<Transaction> txns) {
    final ops = ['Orange', 'MTN', 'Moov'];
    return ops.map((op) {
      final opTxns = txns.where((t) => t.operator == op).toList();
      final opTotal = opTxns.fold(0, (a, t) => a + t.amount);
      final pct = txns.isEmpty ? 0.0 : opTxns.length / txns.length;
      return Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Row(children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: AppColors.operatorColor(op),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Center(
              child: Text(
                op == 'Orange' ? 'o' : op,
                style: GoogleFonts.nunito(
                    fontSize: op == 'MTN' ? 12 : 10,
                    fontWeight: FontWeight.w900,
                    color: Colors.white),
              ),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                Text(op,
                    style: GoogleFonts.nunito(
                        fontSize: 13, fontWeight: FontWeight.w800, color: AppColors.textPrimary)),
                Text('${opTxns.length} op. · ${_fmtAmt(opTotal)} FCFA',
                    style: GoogleFonts.nunito(
                        fontSize: 11, color: AppColors.textSecondary)),
              ]),
              const SizedBox(height: 6),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: pct,
                  backgroundColor: AppColors.operatorColor(op).withValues(alpha: 0.12),
                  valueColor: AlwaysStoppedAnimation<Color>(AppColors.operatorColor(op)),
                  minHeight: 5,
                ),
              ),
            ]),
          ),
        ]),
      );
    }).toList();
  }

  Widget _statCard(String label, String value, String sub, Color color) =>
      Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label,
              style: GoogleFonts.nunito(
                  fontSize: 10,
                  color: AppColors.textSecondary,
                  fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(value,
              style: GoogleFonts.nunito(
                  fontSize: 18, fontWeight: FontWeight.w900, color: color)),
          Text(sub,
              style: GoogleFonts.nunito(fontSize: 10, color: AppColors.textHint)),
        ]),
      );

  Widget _menuCard(List<Widget> items) => Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(children: items),
      );

  Widget _menuItem(IconData icon, String label, Color iconColor) => Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: () {},
          borderRadius: BorderRadius.circular(14),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            child: Row(children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: iconColor.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(icon, color: iconColor, size: 18),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Text(label,
                    style: GoogleFonts.nunito(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary)),
              ),
              const Icon(Icons.chevron_right_rounded,
                  color: AppColors.textHint, size: 20),
            ]),
          ),
        ),
      );

  String _fmtAmt(int n) {
    if (n >= 1000000) return '${n ~/ 1000000} M';
    if (n >= 1000) {
      final t = n ~/ 1000;
      final r = n % 1000;
      return r == 0 ? '$t 000' : '$t ${r.toString().padLeft(3, '0')}';
    }
    return '$n';
  }
}
