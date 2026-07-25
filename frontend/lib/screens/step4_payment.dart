import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:url_launcher/url_launcher.dart';
import '../theme/app_theme.dart';
import '../models/models.dart';
import '../services/backend_api_service.dart';
import '../screens/notifications_screen.dart';
import '../widgets/widgets.dart';

class Step4PaymentScreen extends StatefulWidget {
  final String operator;
  final String service;
  final String operation;
  final String phone;
  final int amount;
  final Function(Transaction) onTransactionAdded;
  final Function(AppNotification) onNotificationAdded;

  const Step4PaymentScreen({
    super.key,
    required this.operator,
    required this.service,
    required this.operation,
    required this.phone,
    required this.amount,
    required this.onTransactionAdded,
    required this.onNotificationAdded,
  });

  @override
  State<Step4PaymentScreen> createState() => _Step4PaymentScreenState();
}

class _Step4PaymentScreenState extends State<Step4PaymentScreen> {
  final BackendApiService _api = BackendApiService();
  bool _loading = false;

  int get _fee => (widget.amount * 0.01).round();
  int get _total => widget.amount + _fee;

  String _operatorLogo(String operator) {
    if (operator == 'MTN') return 'assets/images/mtn.jpg';
    if (operator == 'Moov') return 'assets/images/moov.jpeg';
    return 'assets/images/Orange_logo.png';
  }

  String _formatTime(DateTime date) {
    final h = date.hour.toString().padLeft(2, '0');
    final m = date.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }

  String _formatDate(DateTime date) {
    final d = date.day.toString().padLeft(2, '0');
    final m = date.month.toString().padLeft(2, '0');
    final y = date.year.toString();
    return '$d/$m/$y';
  }

  @override
  Widget build(BuildContext context) {
    final isTransfer = widget.operation.contains('Transfert');
    return Scaffold(
      backgroundColor: Colors.white,
      body: Column(
        children: [
          const GreenHeader(
            title: 'Récapitulatif & Paiement',
            subtitle:
                'Vérifiez les informations avant\nde procéder au paiement',
            icon: 'payment',
            step: 4,
          ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(18, 22, 18, 22),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  TolCard(
                    padding: EdgeInsets.zero,
                    child: Column(
                      children: [
                        _summaryRow(
                          Image.asset(_operatorLogo(widget.operator),
                              width: 34, height: 34, fit: BoxFit.contain),
                          'Opérateur',
                          widget.operator,
                          AppColors.operatorColor(widget.operator),
                        ),
                        _summaryRow(
                            const Icon(Icons.language_rounded,
                                color: AppColors.blue, size: 34),
                            'Service',
                            widget.service,
                            AppColors.blue),
                        _summaryRow(
                            const Icon(Icons.sync_rounded,
                                color: AppColors.success, size: 34),
                            'Opération',
                            widget.operation
                                .replaceAll(' pour moi', '')
                                .replaceAll(' pour un tiers', ''),
                            AppColors.success),
                        _summaryRow(
                            const Icon(Icons.phone_in_talk_outlined,
                                color: AppColors.textPrimary, size: 34),
                            'Numéro',
                            widget.phone,
                            AppColors.textPrimary),
                        _summaryRow(
                            const Icon(Icons.attach_money_rounded,
                                color: AppColors.textPrimary, size: 34),
                            'Montant du forfait',
                            '${widget.amount} FCFA',
                            AppColors.textPrimary),
                        _summaryRow(
                            const Icon(Icons.percent_rounded,
                                color: AppColors.textPrimary, size: 34),
                            'Frais de service (1%)  ⓘ',
                            '$_fee FCFA',
                            AppColors.textPrimary),
                        Container(
                          padding: const EdgeInsets.fromLTRB(18, 14, 18, 18),
                          decoration: const BoxDecoration(
                            border: Border(
                              top: BorderSide(
                                color: Color(0xFFCED4E0),
                                style: BorderStyle.solid,
                              ),
                            ),
                          ),
                          child: Row(
                            children: [
                              Expanded(
                                child: Text(
                                  'Total à payer',
                                  style: GoogleFonts.nunito(
                                    fontSize: 18,
                                    fontWeight: FontWeight.w900,
                                    color: AppColors.success,
                                  ),
                                ),
                              ),
                              Text(
                                '$_total',
                                style: GoogleFonts.nunito(
                                  fontSize: 26,
                                  fontWeight: FontWeight.w900,
                                  color: AppColors.success,
                                ),
                              ),
                              const SizedBox(width: 6),
                              Text(
                                'FCFA',
                                style: GoogleFonts.nunito(
                                  fontSize: 18,
                                  fontWeight: FontWeight.w900,
                                  color: AppColors.success,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 18),
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: AppColors.primaryLight,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: const Color(0xFFD0E8D8)),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.info_rounded,
                            color: AppColors.success, size: 27),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Information tarifaire',
                                style: GoogleFonts.nunito(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w900,
                                  color: AppColors.success,
                                ),
                              ),
                              Text(
                                'Des frais de service de 1% sont appliqués à cette transaction.',
                                style: GoogleFonts.nunito(
                                  fontSize: 14,
                                  color: const Color(0xFF555555),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 22),
                  _cinetPayPanel(),
                  const SizedBox(height: 16),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.lock_outline_rounded,
                          size: 18, color: AppColors.textSecondary),
                      const SizedBox(width: 8),
                      Text(
                        'Paiement 100% sécurisé',
                        style: GoogleFonts.nunito(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 18),
                  TolButton(
                    label: isTransfer ? 'PAYER ET TRANSFÉRER' : 'PAYER ET SOUSCRIRE',
                    loading: _loading,
                    onTap: _confirm,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _summaryRow(Widget leading, String label, String value, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 13),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFFECEEF5))),
      ),
      child: Row(
        children: [
          SizedBox(width: 38, child: Center(child: leading)),
          const SizedBox(width: 16),
          Expanded(
            child: Text(
              label,
              style: GoogleFonts.nunito(
                fontSize: 17,
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
          ),
          Text(
            value,
            textAlign: TextAlign.right,
            style: GoogleFonts.nunito(
              fontSize: 17,
              fontWeight: FontWeight.w900,
              color: color,
            ),
          ),
        ],
      ),
    );
  }

  Widget _cinetPayPanel() => Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFFE7EAF2)),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.04),
              blurRadius: 10,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: Row(
          children: [
            const Icon(Icons.verified_user_rounded, color: AppColors.success, size: 34),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Paiement CinetPay',
                    style: GoogleFonts.nunito(
                      fontSize: 17,
                      fontWeight: FontWeight.w900,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  Text(
                    'Mobile Money, carte et canaux activés sur votre compte marchand.',
                    style: GoogleFonts.nunito(fontSize: 14, color: AppColors.textSecondary),
                  ),
                ],
              ),
            ),
          ],
        ),
      );

  Future<void> _confirm() async {
    setState(() => _loading = true);
    try {
      final result = await _confirmServer();
      if (result.checkoutUrl.isEmpty) {
        throw Exception('URL de paiement CinetPay indisponible');
      }
      final launched = await launchUrl(
        Uri.parse(result.checkoutUrl),
        mode: LaunchMode.externalApplication,
      );
      if (!launched) {
        throw Exception('Impossible d’ouvrir CinetPay');
      }
      final now = DateTime.now();
      final transaction = Transaction(
        id: result.reference,
        operator: widget.operator,
        service: widget.service,
        operation: widget.operation,
        phone: widget.phone,
        amount: widget.amount,
        paymentMethod: 'CinetPay',
        date: now,
        status: 'pending',
      );
      widget.onTransactionAdded(transaction);
      widget.onNotificationAdded(_buildNotification(transaction));
      if (!mounted) return;
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => SuccessScreen(transaction: transaction)),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.toString().replaceFirst('Exception: ', ''))),
      );
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<BackendTransactionResult> _confirmServer() async {
    try {
      return await _api.createTransaction(
        operator: widget.operator,
        service: widget.service,
        operation: widget.operation,
        phone: widget.phone,
        amount: widget.amount,
      );
    } catch (_) {
      rethrow;
    }
  }

  AppNotification _buildNotification(Transaction transaction) {
    final success = transaction.status == 'ok';
    final pending = transaction.status == 'pending';
    final now = DateTime.now();
    return AppNotification(
      title: success
          ? '${transaction.operation} ${transaction.service} réussie'
          : pending
              ? 'Paiement CinetPay en attente'
              : '${transaction.operation} ${transaction.service} échouée',
      message:
          'Numéro : ${transaction.phone}\nMontant : ${transaction.amount} FCFA\nFrais : ${transaction.fee} FCFA\nTotal débité : ${transaction.total} FCFA\nMoyen de paiement : ${transaction.paymentMethod}',
      time: 'Aujourd\'hui · ${_formatTime(now)}',
      read: false,
      icon: success ? 'success' : pending ? 'info' : 'error',
      type: success ? 'success' : pending ? 'info' : 'error',
      reference: transaction.id,
      operator: transaction.operator,
      service: transaction.service,
      operation: transaction.operation,
      phone: transaction.phone,
      amount: '${transaction.amount} FCFA',
      fee: '${transaction.fee} FCFA',
      total: '${transaction.total} FCFA',
      paymentMethod: transaction.paymentMethod,
      date: _formatDate(now),
      heure: _formatTime(now),
    );
  }

}

class SuccessScreen extends StatelessWidget {
  final Transaction transaction;

  const SuccessScreen({
    super.key,
    required this.transaction,
  });

  String _operatorLogo(String operator) {
    if (operator == 'MTN') return 'assets/images/mtn.jpg';
    if (operator == 'Moov') return 'assets/images/moov.jpeg';
    return 'assets/images/Orange_logo.png';
  }

  String _formatTime(DateTime date) {
    final h = date.hour.toString().padLeft(2, '0');
    final m = date.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }

  String _formatDate(DateTime date) {
    final d = date.day.toString().padLeft(2, '0');
    final m = date.month.toString().padLeft(2, '0');
    final y = date.year.toString();
    return '$d/$m/$y';
  }

  @override
  Widget build(BuildContext context) {
    final t = transaction;
    final isSuccess = t.status == 'ok';
    final isPending = t.status == 'pending';
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        surfaceTintColor: Colors.white,
        elevation: 0,
        centerTitle: true,
        leading: IconButton(
          icon: Icon(
            isSuccess || isPending ? Icons.arrow_back_rounded : Icons.close_rounded,
            color: isSuccess || isPending ? AppColors.success : AppColors.red,
            size: 30,
          ),
          onPressed: () => Navigator.pop(context),
        ),
        title: Text(
          'Détail notification',
          style: GoogleFonts.nunito(
            fontSize: 22,
            fontWeight: FontWeight.w900,
            color: AppColors.textPrimary,
          ),
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 28),
        child: Column(
          children: [
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 12),
              decoration: BoxDecoration(
                color: isSuccess || isPending ? AppColors.primaryLight : AppColors.redLight,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                    color: isSuccess || isPending
                        ? const Color(0xFFC5E7CE)
                        : const Color(0xFFF5C2C2)),
              ),
              child: Column(
                children: [
                  Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(
                      color: isSuccess || isPending ? AppColors.success : AppColors.red,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      isSuccess ? Icons.check_rounded : isPending ? Icons.hourglass_top_rounded : Icons.close_rounded,
                      color: Colors.white,
                      size: 42,
                    ),
                  ),
                  const SizedBox(height: 14),
                  Text(
                    isSuccess ? 'Transaction réussie' : isPending ? 'Paiement en attente' : 'Transaction échouée',
                    style: GoogleFonts.nunito(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: isSuccess || isPending ? AppColors.success : AppColors.red,
                    ),
                  ),
                  const SizedBox(height: 5),
                  Text(
                    isSuccess
                        ? 'Votre opération a été effectuée avec succès'
                        : isPending
                            ? 'Finalisez le paiement CinetPay. La Gateway Android exécutera ensuite l’opération.'
                            : 'Une erreur est survenue lors du paiement. Vérifiez votre solde ou réessayez.',
                    style: GoogleFonts.nunito(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: AppColors.textSecondary,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),
            TolCard(
              padding: EdgeInsets.zero,
              child: Column(
                children: [
                  _detailRow(
                      const Icon(Icons.receipt_long_outlined,
                          color: AppColors.success, size: 28),
                      'Référence transaction',
                      t.id,
                      AppColors.success),
                  _detailRow(
                      Image.asset(_operatorLogo(t.operator),
                          width: 30, height: 30, fit: BoxFit.contain),
                      'Opérateur',
                      t.operator,
                      AppColors.orange),
                  _detailRow(
                      const Icon(Icons.language_rounded,
                          color: AppColors.blue, size: 30),
                      'Service',
                      t.service,
                      AppColors.blue),
                  _detailRow(
                      const Icon(Icons.sync_rounded,
                          color: AppColors.success, size: 30),
                      'Type d\'opération',
                      t.operation,
                      AppColors.success),
                  _detailRow(
                      const Icon(Icons.phone_in_talk_outlined,
                          color: AppColors.textPrimary, size: 30),
                      'Numéro',
                      t.phone,
                      AppColors.textPrimary),
                  _detailRow(
                      const Icon(Icons.attach_money_rounded,
                          color: AppColors.textPrimary, size: 30),
                      'Montant du forfait',
                      '${t.amount} FCFA',
                      AppColors.textPrimary),
                  _detailRow(
                      const Icon(Icons.percent_rounded,
                          color: AppColors.success, size: 30),
                      'Frais de service (1%)  ⓘ',
                      '${t.fee} FCFA',
                      AppColors.textPrimary),
                  _detailRow(
                      const Icon(Icons.calendar_today_outlined,
                          color: AppColors.success, size: 28),
                      'Total débité',
                      '${t.total} FCFA',
                      AppColors.success),
                  _detailRow(
                      const Icon(Icons.account_balance_wallet_outlined,
                          color: AppColors.orange, size: 30),
                      'Moyen de paiement',
                      t.paymentMethod,
                      AppColors.orange),
                  _detailRow(
                      const Icon(Icons.event_available_outlined,
                          color: AppColors.success, size: 30),
                      'Date',
                      _formatDate(t.date),
                      AppColors.textPrimary),
                  _detailRow(
                      const Icon(Icons.access_time_rounded,
                          color: AppColors.success, size: 30),
                      'Heure',
                      _formatTime(t.date),
                      AppColors.textPrimary),
                  _detailRow(
                      const Icon(Icons.verified_user_outlined,
                          color: AppColors.success, size: 30),
                      'Statut',
                      isSuccess ? 'Réussie' : isPending ? 'En attente' : 'Échouée',
                      AppColors.success,
                      last: true),
                ],
              ),
            ),
            const SizedBox(height: 18),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFFEAF4FF),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: const Color(0xFFC9DFFF)),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const CircleAvatar(
                    radius: 18,
                    backgroundColor: AppColors.blue,
                    child: Icon(Icons.info_rounded, color: Colors.white),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Message',
                            style: GoogleFonts.nunito(
                                fontSize: 16,
                                fontWeight: FontWeight.w900,
                                color: AppColors.textPrimary)),
                        Text(
                          isPending
                              ? 'Votre paiement CinetPay est ouvert. Après confirmation, la Gateway Android traitera automatiquement l’opération.\n\nMontant du forfait : ${t.amount} FCFA\nFrais de service : ${t.fee} FCFA\nTotal à payer : ${t.total} FCFA'
                              : 'Votre forfait ${t.service} a été activé avec succès.\n\nMontant du forfait : ${t.amount} FCFA\nFrais de service : ${t.fee} FCFA\nTotal débité : ${t.total} FCFA',
                          style: GoogleFonts.nunito(
                            fontSize: 15,
                            height: 1.25,
                            fontWeight: FontWeight.w700,
                            color: AppColors.textPrimary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),
            TolButton(
              label: 'VOIR LES NOTIFICATIONS',
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) =>
                      NotificationsScreen(notifications: sampleNotifications),
                ),
              ),
            ),
            const SizedBox(height: 10),
            TextButton(
              onPressed: () =>
                  Navigator.popUntil(context, (route) => route.isFirst),
              child: Text(
                'Fermer',
                style: GoogleFonts.nunito(
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textSecondary,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _detailRow(
    Widget leading,
    String label,
    String value,
    Color valueColor, {
    bool last = false,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
      decoration: BoxDecoration(
        border: last
            ? null
            : const Border(bottom: BorderSide(color: Color(0xFFECEEF5))),
      ),
      child: Row(
        children: [
          SizedBox(width: 34, child: Center(child: leading)),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              label,
              style: GoogleFonts.nunito(
                fontSize: 16,
                fontWeight:
                    label == 'Total débité' ? FontWeight.w900 : FontWeight.w700,
                color: label == 'Total débité'
                    ? AppColors.success
                    : AppColors.textPrimary,
              ),
            ),
          ),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: GoogleFonts.nunito(
                fontSize: label == 'Total débité' ? 20 : 16,
                fontWeight: FontWeight.w900,
                color: valueColor,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
