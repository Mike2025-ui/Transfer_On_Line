import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme/app_theme.dart';
import '../models/models.dart';
import '../widgets/widgets.dart';

// Écran d'historique des transactions réelles (TransactionService), avec
// filtres. Les notifications ont leur propre écran (notifications_screen.dart)
// - les anciennes classes NotificationsScreen/NotifDetailScreen dupliquées
// ici ont été retirées (code mort, jamais atteint depuis cet écran).

// ─── HISTORY ──────────────────────────────────────────────────────────────────
class HistoryScreen extends StatefulWidget {
  final List<Transaction> transactions;
  const HistoryScreen({super.key, required this.transactions});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  String _filter = 'Tous';
  final filters = ['Tous', 'Souscription', 'Transfert', 'Réussis', 'Échoués'];

  List<Transaction> get filtered {
    switch (_filter) {
      case 'Réussis':
        return widget.transactions.where((t) => t.status == 'ok').toList();
      case 'Échoués':
        return widget.transactions.where((t) => t.status == 'fail').toList();
      case 'Souscription':
        return widget.transactions
            .where((t) => t.operation.contains('Souscription'))
            .toList();
      case 'Transfert':
        return widget.transactions
            .where((t) => t.operation.contains('Transfert'))
            .toList();
      default:
        return widget.transactions;
    }
  }

  @override
  Widget build(BuildContext context) {
    final f = filtered;
    final total =
        f.where((t) => t.status == 'ok').fold(0, (a, t) => a + t.amount);
    final ok = f.where((t) => t.status == 'ok').length;
    final pct = f.isEmpty ? 0 : (ok / f.length * 100).round();

    return Scaffold(
      backgroundColor: AppColors.background,
      body: CustomScrollView(slivers: [
        SliverToBoxAdapter(
            child: Container(
          decoration: const BoxDecoration(
              gradient: LinearGradient(
                  colors: [Color(0xFF0D5C2C), Color(0xFF1A7A3C)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight)),
          padding: EdgeInsets.only(
              top: MediaQuery.of(context).padding.top + 16,
              bottom: 20,
              left: 20,
              right: 20),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Historique',
                style: GoogleFonts.nunito(
                    fontSize: 22,
                    fontWeight: FontWeight.w900,
                    color: Colors.white)),
            const SizedBox(height: 14),
            LayoutBuilder(builder: (context, constraints) {
              final useWrap = constraints.maxWidth < 420;
              final chips = filters
                  .map((f) => GestureDetector(
                        onTap: () => setState(() => _filter = f),
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 200),
                          margin: const EdgeInsets.only(right: 8, bottom: 8),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 14, vertical: 6),
                          decoration: BoxDecoration(
                            color: _filter == f
                                ? Colors.white
                                : Colors.transparent,
                            borderRadius: BorderRadius.circular(20),
                            border: Border.all(
                                color: _filter == f
                                    ? Colors.white
                                    : Colors.white38),
                          ),
                          child: Text(f,
                              style: GoogleFonts.nunito(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  color: _filter == f
                                      ? AppColors.primary
                                      : Colors.white.withValues(alpha: 0.6))),
                        ),
                      ))
                  .toList();
              return useWrap
                  ? Wrap(children: chips)
                  : SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: Row(children: chips),
                    );
            }),
          ]),
        )),
        SliverToBoxAdapter(
            child: Padding(
          padding: const EdgeInsets.all(16),
          child: LayoutBuilder(builder: (context, constraints) {
            final narrow = constraints.maxWidth < 520;
            return narrow
                ? Column(
                    children: [
                      _statCard('Total dépensé', '$total',
                          'FCFA · $ok opération(s)', AppColors.primary),
                      const SizedBox(height: 12),
                      _statCard('Taux de succès', '$pct%',
                          '${f.length} transaction(s)', AppColors.textPrimary),
                    ],
                  )
                : Row(children: [
                    Expanded(
                        child: _statCard('Total dépensé', '$total',
                            'FCFA · $ok opération(s)', AppColors.primary)),
                    const SizedBox(width: 12),
                    Expanded(
                        child: _statCard(
                            'Taux de succès',
                            '$pct%',
                            '${f.length} transaction(s)',
                            AppColors.textPrimary)),
                  ]);
          }),
        )),
        if (f.isEmpty)
          const SliverToBoxAdapter(
              child: Center(
                  child: Padding(
            padding: EdgeInsets.all(40),
            child: Text('Aucune transaction trouvée',
                style: TextStyle(color: AppColors.textSecondary)),
          )))
        else
          SliverList(
              delegate: SliverChildBuilderDelegate(
            (_, i) => Padding(
              padding: EdgeInsets.fromLTRB(16, i == 0 ? 0 : 0, 16, 0),
              child: _txnRow(f[i]),
            ),
            childCount: f.length,
          )),
        const SliverToBoxAdapter(child: SizedBox(height: 100)),
      ]),
    );
  }

  Widget _statCard(String lbl, String val, String sub, Color valColor) =>
      Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
            color: Colors.white, borderRadius: BorderRadius.circular(14)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(lbl,
              style: GoogleFonts.nunito(
                  fontSize: 11,
                  color: AppColors.textSecondary,
                  fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(val,
              style: GoogleFonts.nunito(
                  fontSize: 20, fontWeight: FontWeight.w900, color: valColor)),
          Text(sub,
              style:
                  GoogleFonts.nunito(fontSize: 11, color: AppColors.textHint)),
        ]),
      );

  Widget _txnRow(Transaction t) => GestureDetector(
        onTap: () => Navigator.push(
            context,
            MaterialPageRoute(
                builder: (_) => TransactionDetailScreen(transaction: t))),
        child: Container(
          margin: const EdgeInsets.only(bottom: 1),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          decoration: BoxDecoration(
            color: Colors.white,
            border: Border(bottom: BorderSide(color: AppColors.divider)),
          ),
          child: Row(children: [
            Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                    color: AppColors.operatorColor(t.operator)
                        .withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(12)),
                child: Center(
                    child: Text(t.serviceIcon,
                        style: const TextStyle(fontSize: 18)))),
            const SizedBox(width: 12),
            Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                  Text('${t.operator} · ${t.service}',
                      style: GoogleFonts.nunito(
                          fontSize: 13,
                          fontWeight: FontWeight.w800,
                          color: AppColors.textPrimary)),
                  Text('${t.operation} · ${_dateStr(t.date)}',
                      style: GoogleFonts.nunito(
                          fontSize: 11, color: AppColors.textSecondary)),
                ])),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text('-${t.amount} FCFA',
                  style: GoogleFonts.nunito(
                      fontSize: 13,
                      fontWeight: FontWeight.w900,
                      color: t.status == 'ok'
                          ? AppColors.red
                          : AppColors.textHint)),
              const SizedBox(height: 4),
              StatusBadge(t.status),
            ]),
          ]),
        ),
      );

  String _dateStr(DateTime d) {
    final diff = DateTime.now().difference(d);
    if (diff.inDays == 0) return "Aujourd'hui";
    if (diff.inDays == 1) return 'Hier';
    return '${d.day} ${[
      'Jan',
      'Fév',
      'Mar',
      'Avr',
      'Mai',
      'Jun',
      'Jul',
      'Aoû',
      'Sep',
      'Oct',
      'Nov',
      'Déc'
    ][d.month - 1]}';
  }
}

// ─── Détail d'une transaction (depuis l'historique) ────────────────────────────
class TransactionDetailScreen extends StatelessWidget {
  final Transaction transaction;
  const TransactionDetailScreen({super.key, required this.transaction});

  String _opImage(String op) {
    if (op == 'MTN') return 'assets/images/mtn.jpg';
    if (op == 'Moov') return 'assets/images/moov.jpeg';
    return 'assets/images/Orange_logo.png';
  }

  @override
  Widget build(BuildContext context) {
    final t = transaction;
    final date =
        '${t.date.day.toString().padLeft(2, '0')}/${t.date.month.toString().padLeft(2, '0')}/${t.date.year}';
    final heure =
        '${t.date.hour.toString().padLeft(2, '0')}:${t.date.minute.toString().padLeft(2, '0')}';
    final opLogo = ClipRRect(
      borderRadius: BorderRadius.circular(6),
      child: Image.asset(_opImage(t.operator),
          width: 24, height: 24, fit: BoxFit.cover),
    );

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        surfaceTintColor: Colors.white,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded, color: AppColors.primary),
          onPressed: () => Navigator.pop(context),
        ),
        centerTitle: true,
        title: Text('Détail transaction',
            style: GoogleFonts.nunito(
                fontSize: 17,
                fontWeight: FontWeight.w900,
                color: AppColors.textPrimary)),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(children: [
          // Badge statut
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 20),
            decoration: BoxDecoration(
              color: t.status == 'ok'
                  ? AppColors.primaryLight
                  : const Color(0xFFFFF3F3),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Column(children: [
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: t.status == 'ok' ? AppColors.primary : AppColors.red,
                  shape: BoxShape.circle,
                ),
                child: Center(
                    child: Icon(
                  t.status == 'ok' ? Icons.check_rounded : Icons.close_rounded,
                  color: Colors.white,
                  size: 30,
                )),
              ),
              const SizedBox(height: 12),
              Text(
                t.status == 'ok'
                    ? 'Transaction réussie'
                    : 'Transaction échouée',
                style: GoogleFonts.nunito(
                    fontSize: 18,
                    fontWeight: FontWeight.w900,
                    color:
                        t.status == 'ok' ? AppColors.primary : AppColors.red),
              ),
            ]),
          ),
          const SizedBox(height: 16),
          TolCard(
            padding: EdgeInsets.zero,
            child: Column(children: [
              _row('Référence', t.id, AppColors.primary),
              _rowWidget(opLogo, 'Opérateur', t.operator,
                  AppColors.operatorColor(t.operator)),
              _row('Service', t.service, AppColors.blue),
              _row('Type d\'opération', t.operation, AppColors.primary),
              _row('Numéro', t.phone, null),
              _row('Montant', '${t.amount} FCFA', null),
              _row('Moyen de paiement', t.paymentMethod, AppColors.orange),
              _row('Date', date, null),
              _row('Heure', heure, null),
              _row('Statut', t.status == 'ok' ? 'Réussie' : 'Échouée',
                  t.status == 'ok' ? AppColors.primary : AppColors.red,
                  last: true),
            ]),
          ),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton(
              onPressed: () => Navigator.pop(context),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primary,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
                elevation: 0,
              ),
              child: Text('Fermer',
                  style: GoogleFonts.nunito(
                      fontSize: 15,
                      fontWeight: FontWeight.w900,
                      color: Colors.white)),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _row(String key, String val, Color? color, {bool last = false}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
          border: last
              ? null
              : const Border(bottom: BorderSide(color: Color(0xFFF0F0F0)))),
      child: Row(children: [
        Expanded(
            child: Text(key,
                style: GoogleFonts.nunito(
                    fontSize: 12,
                    color: AppColors.textSecondary,
                    fontWeight: FontWeight.w600))),
        Text(val,
            style: GoogleFonts.nunito(
                fontSize: 12,
                fontWeight: FontWeight.w900,
                color: color ?? AppColors.textPrimary)),
      ]),
    );
  }

  Widget _rowWidget(Widget leading, String key, String val, Color? color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: Color(0xFFF0F0F0)))),
      child: Row(children: [
        leading,
        const SizedBox(width: 8),
        Expanded(
            child: Text(key,
                style: GoogleFonts.nunito(
                    fontSize: 12,
                    color: AppColors.textSecondary,
                    fontWeight: FontWeight.w600))),
        Text(val,
            style: GoogleFonts.nunito(
                fontSize: 12,
                fontWeight: FontWeight.w900,
                color: color ?? AppColors.textPrimary)),
      ]),
    );
  }
}
