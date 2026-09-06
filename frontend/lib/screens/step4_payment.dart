import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:url_launcher/url_launcher.dart';
import '../theme/app_theme.dart';
import '../models/models.dart';
import '../services/auth_service.dart';
import '../services/backend_api_service.dart';
import '../services/transaction_service.dart';
import '../screens/notifications_screen.dart';
import '../widgets/widgets.dart';

class Step4PaymentScreen extends StatefulWidget {
  final int operatorId;
  final int serviceId;
  final String operator;
  final String service;
  final String operation;
  final String phone;
  final int amount;
  final Function(Transaction) onTransactionAdded;
  final Function(AppNotification) onNotificationAdded;
  // Business-model audit (frontend, §17): the same evolving notification
  // list HomeScreen holds, threaded down screen by screen exactly like
  // onNotificationAdded already is - so SuccessScreen's "VOIR LES
  // NOTIFICATIONS" button can open the real list instead of the static
  // sampleNotifications fixture.
  final List<AppNotification> notifications;
  final BackendApiService? backendApiService;
  final AuthService? authService;

  const Step4PaymentScreen({
    super.key,
    required this.operatorId,
    required this.serviceId,
    required this.operator,
    required this.service,
    required this.operation,
    required this.phone,
    required this.amount,
    required this.onTransactionAdded,
    required this.onNotificationAdded,
    required this.notifications,
    this.backendApiService,
    this.authService,
  });

  @override
  State<Step4PaymentScreen> createState() => _Step4PaymentScreenState();
}

class _Step4PaymentScreenState extends State<Step4PaymentScreen> {
  late final BackendApiService _api =
      widget.backendApiService ?? BackendApiService();
  late final AuthService _auth = widget.authService ?? AuthService();
  // Business-model audit Phase 5: one key per checkout attempt (this screen
  // instance), generated once and reused across every internal retry of
  // _confirm() - a genuinely new attempt only happens when the user leaves
  // and re-enters this screen, which creates a new instance/key.
  late final String _idempotencyKey = _generateIdempotencyKey();
  bool _loading = false;
  // Djeko est la passerelle unique : son choix d'operateur reste dans sa
  // page web securisee et n'est jamais expose dans l'application.
  static const _paymentMethod = 'djeko';
  static const _paymentLabel = 'Djeko';

  String _operatorLogo(String operator) {
    if (operator == 'MTN') return 'assets/images/mtn.jpg';
    if (operator == 'Moov') return 'assets/images/moov.jpeg';
    return 'assets/images/Orange_logo.png';
  }

  @override
  Widget build(BuildContext context) {
    final isTransfer = widget.operation.contains('Transfert');
    return PopScope(
      // §15 de l'audit : bloquer la fermeture accidentelle de l'écran
      // pendant la création de la transaction - une fois la requête HTTP en
      // vol, un retour arrière ne l'annule pas côté Backend, il ferait juste
      // perdre à l'utilisateur le fil de ce qui se passe.
      canPop: !_loading,
      child: Scaffold(
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
                        ],
                      ),
                    ),
                    const SizedBox(height: 22),
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
                      label: isTransfer
                          ? 'PAYER ET TRANSFÉRER'
                          : 'PAYER ET SOUSCRIRE',
                      loading: _loading,
                      onTap: _confirm,
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
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

  Future<void> _confirm() async {
    setState(() => _loading = true);
    try {
      final result = await _confirmServer();
      if (result.checkoutUrl.isEmpty) {
        throw Exception('URL de paiement Djeko indisponible');
      }
      final launched = await launchUrl(
        Uri.parse(result.checkoutUrl),
        mode: LaunchMode.externalApplication,
      );
      if (!launched) {
        throw Exception('Impossible d’ouvrir Djeko');
      }
      final now = DateTime.now();
      final transaction = Transaction(
        id: result.reference,
        operator: widget.operator,
        service: widget.service,
        operation: widget.operation,
        phone: widget.phone,
        amount: widget.amount,
        paymentMethod: _paymentLabel,
        date: now,
        status: 'pending',
      );
      widget.onTransactionAdded(transaction);
      // Identity architecture (Phase 8): no notification is fabricated here
      // - a Notification only ever exists once the backend genuinely
      // confirms a terminal outcome (see TransactionStateMachine.transition
      // -> Notification.create_for_transaction_status on the backend).
      // HomeScreen re-fetches the real list from GET /notifications/, it
      // never invents one from a transaction that just started.
      if (!mounted) return;
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => SuccessScreen(
            transaction: transaction,
            notifications: widget.notifications,
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(error.toString().replaceFirst('Exception: ', ''))),
      );
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<BackendTransactionResult> _confirmServer() async {
    try {
      final accessToken = await _auth.currentAccessToken();
      return await _api.createTransaction(
        operatorId: widget.operatorId,
        serviceId: widget.serviceId,
        operator: widget.operator,
        service: widget.service,
        operation: widget.operation,
        phone: widget.phone,
        amount: widget.amount,
        paymentMethod: _paymentMethod,
        accessToken: accessToken,
        idempotencyKey: _idempotencyKey,
      );
    } catch (_) {
      rethrow;
    }
  }
}

/// Random UUID v4, generated locally with no added dependency - only used as
/// an opaque Idempotency-Key value, never parsed or displayed.
String _generateIdempotencyKey() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0F) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3F) | 0x80; // variant 10xx
  String hex(int start, int end) => bytes
      .sublist(start, end)
      .map((b) => b.toRadixString(16).padLeft(2, '0'))
      .join();
  return '${hex(0, 4)}-${hex(4, 6)}-${hex(6, 8)}-${hex(8, 10)}-${hex(10, 16)}';
}

class SuccessScreen extends StatefulWidget {
  final Transaction transaction;
  final List<AppNotification> notifications;
  final BackendApiService? backendApiService;
  final AuthService? authService;

  const SuccessScreen({
    super.key,
    required this.transaction,
    required this.notifications,
    this.backendApiService,
    this.authService,
  });

  @override
  State<SuccessScreen> createState() => _SuccessScreenState();
}

class _SuccessScreenState extends State<SuccessScreen>
    with WidgetsBindingObserver {
  /// Calendrier de vérification progressif (audit frontend D4, §6) : des
  /// vérifications rapprochées au début, de plus en plus espacées ensuite -
  /// jamais un `Timer.periodic` à cadence fixe qui marteler le Backend, et
  /// surtout jamais un plafond qui déclare l'opération abandonnée. Une
  /// session USSD interactive peut dépasser largement l'ancienne limite de
  /// 60s (voir UssdAccessibilityService/D4 côté Gateway - jamais mentionné
  /// ici, seul le Backend importe pour ce Client).
  static const List<Duration> _pollDelays = [
    Duration(seconds: 3),
    Duration(seconds: 3),
    Duration(seconds: 4),
    Duration(seconds: 5),
    Duration(seconds: 5),
    Duration(seconds: 10),
    Duration(seconds: 15),
    Duration(seconds: 15),
    Duration(seconds: 30),
    Duration(seconds: 30),
  ];
  // Rythme de croisière une fois le calendrier ci-dessus épuisé (120s
  // cumulés) - continue indéfiniment tant que le Backend répond "pending",
  // sans jamais déclarer l'opération terminée de son propre chef.
  static const _steadyPollDelay = Duration(seconds: 60);
  // Seuil à partir duquel l'écran informe explicitement l'utilisateur que
  // l'attente se prolonge et propose une vérification manuelle immédiate -
  // le suivi automatique, lui, continue de tourner sans interruption.
  static const _extendedWaitThreshold = Duration(seconds: 60);

  late final BackendApiService _api =
      widget.backendApiService ?? BackendApiService();
  late final AuthService _auth = widget.authService ?? AuthService();
  late Transaction _transaction = widget.transaction;
  Timer? _pollTimer;
  int _attempts = 0;
  bool _checking = false;
  bool _pollingStarted = false;
  // Temps cumulé des délais programmés déjà écoulés (audit frontend D4, §8) -
  // délibérément PAS une horloge murale (`DateTime.now()`) : dans les tests
  // widget, `tester.pump(duration)` avance l'horloge virtuelle des `Timer`
  // mais jamais `DateTime.now()`, qui resterait bloqué sur l'instant réel du
  // test. En comptant les délais réellement programmés/écoulés, l'attente
  // prolongée reste déterministe en test ET fidèle en production (elle ne
  // progresse que lorsqu'un tick programmé se déclenche réellement).
  Duration _elapsedPolling = Duration.zero;
  bool _lifecycleObserverAdded = false;

  @override
  void initState() {
    super.initState();
    // Opening the checkout URL only means the browser opened - it is not
    // proof of anything. Only a status still 'pending' needs confirming;
    // never re-poll an already-resolved local transaction.
    if (_transaction.status == 'pending') {
      _pollingStarted = true;
      WidgetsBinding.instance.addObserver(this);
      _lifecycleObserverAdded = true;
      // Vérification immédiate (0s) plutôt que d'attendre le premier délai
      // du calendrier - voir _checkStatus/_scheduleNext pour la suite.
      _checkStatus();
    }
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    if (_lifecycleObserverAdded) WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Audit frontend D4, §9 : au retour au premier plan, vérifier
    // immédiatement plutôt que d'attendre le prochain tick programmé - le
    // Backend a pu terminer le traitement pendant que l'app était en
    // arrière-plan.
    if (state == AppLifecycleState.resumed &&
        _transaction.status == 'pending' &&
        !_checking) {
      _pollTimer?.cancel();
      _checkStatus();
    }
  }

  Duration _nextPollDelay() {
    if (_attempts < _pollDelays.length) return _pollDelays[_attempts];
    return _steadyPollDelay;
  }

  /// True une fois l'attente prolongée au-delà de [_extendedWaitThreshold] -
  /// pilote uniquement le texte affiché et la présence du bouton de
  /// vérification manuelle, jamais une décision de statut.
  bool get _isLongWait =>
      _pollingStarted && _elapsedPolling >= _extendedWaitThreshold;

  Future<void> _checkStatus() async {
    if (_checking || !mounted || _transaction.status != 'pending') return;
    _checking = true;
    var stillPending = false;
    try {
      final accessToken = await _auth.currentAccessToken();
      // transaction.id already holds the backend `reference` (see
      // _confirm() above: `id: result.reference`), which is exactly what
      // GET /transactions/<reference>/status/ expects.
      final result = await _api.getTransactionStatus(_transaction.id,
          accessToken: accessToken);
      if (result.isPending) {
        stillPending = true;
      } else {
        final newStatus = result.isSuccess
            ? 'ok'
            : (result.isCancelled ? 'cancelled' : 'fail');
        final updated = Transaction(
          id: _transaction.id,
          operator: _transaction.operator,
          service: _transaction.service,
          operation: _transaction.operation,
          phone: _transaction.phone,
          amount: _transaction.amount,
          paymentMethod: _transaction.paymentMethod,
          date: _transaction.date,
          status: newStatus,
        );
        if (mounted) setState(() => _transaction = updated);
        await _persistStatus(updated);
      }
    } on TransactionNotFoundException {
      // Never fabricate an outcome for a transaction the backend doesn't
      // recognize - just stop asking.
    } catch (_) {
      // Transient network/server error on this one tick only - stay
      // pending and retry on the next scheduled tick. A polling error must
      // never be turned into FAILED: only the Backend decides the outcome.
      stillPending = true;
    } finally {
      _checking = false;
    }
    if (stillPending && mounted && _transaction.status == 'pending') {
      final delay = _nextPollDelay();
      _attempts++;
      _elapsedPolling += delay;
      setState(() {}); // reflect a newly-crossed _isLongWait threshold, if any
      _pollTimer?.cancel();
      _pollTimer = Timer(delay, _checkStatus);
    }
  }

  /// Bouton "VÉRIFIER MAINTENANT" (audit frontend D4, §8) : court-circuite
  /// l'attente du prochain tick programmé sans perturber le calendrier -
  /// _checkStatus reprogramme normalement la suite s'il reste pending.
  void _checkNow() {
    if (_checking) return;
    _pollTimer?.cancel();
    _checkStatus();
  }

  /// Corrects the locally-persisted record too, not just what is shown on
  /// this screen - so the fix reaches the actual source of the P0-2 defect
  /// (a transaction permanently stuck at 'pending' in local history).
  Future<void> _persistStatus(Transaction updated) async {
    final saved = await TransactionService.load();
    final index = saved.indexWhere((t) => t.id == updated.id);
    if (index == -1) return;
    saved[index] = updated;
    await TransactionService.save(saved);
  }

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
    final t = _transaction;
    final isSuccess = t.status == 'ok';
    final isPending = t.status == 'pending';
    final isCancelled = t.status == 'cancelled';
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        surfaceTintColor: Colors.white,
        elevation: 0,
        centerTitle: true,
        leading: IconButton(
          icon: Icon(
            isSuccess || isPending
                ? Icons.arrow_back_rounded
                : Icons.close_rounded,
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
                color: isSuccess || isPending
                    ? AppColors.primaryLight
                    : AppColors.redLight,
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
                      color: isSuccess || isPending
                          ? AppColors.success
                          : AppColors.red,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      isSuccess
                          ? Icons.check_rounded
                          : isPending
                              ? Icons.hourglass_top_rounded
                              : isCancelled
                                  ? Icons.cancel_outlined
                                  : Icons.close_rounded,
                      color: Colors.white,
                      size: 42,
                    ),
                  ),
                  const SizedBox(height: 14),
                  Text(
                    isSuccess
                        ? 'Transaction réussie'
                        : isPending
                            ? 'Paiement en attente'
                            : isCancelled
                                ? 'Paiement annulé'
                                : 'Transaction échouée',
                    style: GoogleFonts.nunito(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: isSuccess || isPending
                          ? AppColors.success
                          : AppColors.red,
                    ),
                  ),
                  const SizedBox(height: 5),
                  Text(
                    isSuccess
                        ? 'Votre opération a été effectuée avec succès'
                        : isPending
                            ? 'Finalisez le paiement ${t.paymentMethod}. Votre opération sera ensuite traitée automatiquement.'
                            : isCancelled
                                ? 'Le paiement a été annulé. Vous pouvez réessayer si vous le souhaitez.'
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
                      t.statusLabel,
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
                              ? 'Votre paiement ${t.paymentMethod} est ouvert. Après confirmation, votre opération sera traitée automatiquement.\n\nMontant du forfait : ${t.amount} FCFA\nFrais de service : ${t.fee} FCFA\nTotal à payer : ${t.total} FCFA'
                              : isSuccess
                                  ? 'Votre forfait ${t.service} a été activé avec succès.\n\nMontant du forfait : ${t.amount} FCFA\nFrais de service : ${t.fee} FCFA\nTotal débité : ${t.total} FCFA'
                                  : isCancelled
                                      ? 'Le paiement ${t.paymentMethod} a été annulé avant sa confirmation. Aucun montant n’a été débité.'
                                      : 'Le paiement ${t.paymentMethod} n’a pas pu être confirmé. Vérifiez votre solde ou réessayez depuis l’accueil.',
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
            if (isPending && _isLongWait) ...[
              const SizedBox(height: 18),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: AppColors.amberLight,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xFFF5E0B8)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.schedule_rounded,
                            color: AppColors.amber, size: 24),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            'Votre opération est toujours en cours.',
                            style: GoogleFonts.nunito(
                              fontSize: 15,
                              fontWeight: FontWeight.w900,
                              color: AppColors.amber,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Cela peut prendre un peu plus de temps que d\'habitude. Le suivi continue automatiquement - vous pouvez aussi vérifier maintenant.',
                      style: GoogleFonts.nunito(
                          fontSize: 13, color: AppColors.textSecondary),
                    ),
                    const SizedBox(height: 12),
                    TolButton(
                      label: 'VÉRIFIER MAINTENANT',
                      color: AppColors.amber,
                      loading: _checking,
                      onTap: _checkNow,
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 18),
            TolButton(
              label: 'VOIR LES NOTIFICATIONS',
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) =>
                      NotificationsScreen(notifications: widget.notifications),
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
