import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../models/models.dart';
import '../services/auth_service.dart';
import '../services/backend_api_service.dart';
import '../services/transaction_service.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';
import 'notifications_screen.dart';
import 'step2_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, this.backendApiService, this.authService});

  final BackendApiService? backendApiService;
  final AuthService? authService;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late final BackendApiService _api =
      widget.backendApiService ?? BackendApiService();
  late final AuthService _auth = widget.authService ?? AuthService();
  // Identity architecture (Phase 8): starts empty, never sampleNotifications
  // - a brand-new identity genuinely has zero notifications until the
  // backend says otherwise; fabricating sample ones would misrepresent the
  // authenticated user's real history.
  List<AppNotification> _notifications = [];
  List<Transaction> _transactions = [];
  // Backed by GET /notifications/unread-count/, not derived from
  // _notifications (which only ever holds one page) - stays accurate even
  // past the first page of history.
  int _unreadCount = 0;

  List<OperatorItem>? _operators;
  bool _loadingOperators = true;
  String? _operatorsError;

  @override
  void initState() {
    super.initState();
    _loadTransactions();
    _loadNotifications();
    _loadOperators();
  }

  /// Identity architecture (Phase 7): the backend (`GET /transactions/my/`,
  /// filtered by the JWT alone) is now the source of truth for history -
  /// this is what makes a changed/reinstalled phone recover the exact same
  /// purchases after a fresh OTP. The local cache (TransactionService)
  /// stays only as an offline fallback and as the reconciliation seed for
  /// a transaction that was still pending when the app last closed.
  Future<void> _loadTransactions() async {
    final saved = await TransactionService.load();
    if (saved.isNotEmpty && mounted) {
      setState(() => _transactions = saved);
    }
    // Audit frontend D4, §10 : une transaction restée localement "pending"
    // (app fermée ou tuée avant résolution) doit être revérifiée auprès du
    // Backend - jamais supposée encore active sans vérifier, et jamais
    // relancée en parallèle pour toutes à la fois (voir _reconcilePending).
    if (saved.isNotEmpty) await _reconcilePending(saved);

    final accessToken = await _safeAccessToken();
    if (accessToken == null) return;
    try {
      final remote = await _api.fetchMyTransactions(accessToken: accessToken);
      if (!mounted) return;
      setState(() => _transactions = remote.map(_toLocalTransaction).toList());
      await TransactionService.save(_transactions);
    } catch (_) {
      // Backend unreachable/session expired - keep whatever the local
      // cache/reconciliation above already produced rather than clearing
      // a screen that was showing real data a moment ago.
    }
  }

  Transaction _toLocalTransaction(TransactionSummary s) {
    final localStatus = switch (s.status) {
      'success' => 'ok',
      'cancelled' => 'cancelled',
      'pending' || 'processing' => 'pending',
      _ => 'fail',
    };
    return Transaction(
      id: s.reference,
      operator: s.operator,
      service: s.service,
      operation: s.transactionType,
      phone: s.recipientPhone,
      amount: s.amount.round(),
      paymentMethod: s.paymentMethod ?? '',
      date: s.createdAt ?? DateTime.now(),
      status: localStatus,
    );
  }

  /// Identity architecture (Phase 8): `GET /notifications/` +
  /// `GET /notifications/unread-count/`, both filtered by the JWT alone -
  /// this is what makes notifications survive a phone change/reinstall
  /// exactly like transactions do (Phase 7).
  Future<void> _loadNotifications() async {
    final accessToken = await _safeAccessToken();
    if (accessToken == null) return;
    try {
      final remote = await _api.fetchNotifications(accessToken: accessToken);
      if (!mounted) return;
      setState(() => _notifications = remote.map(_toAppNotification).toList());
    } catch (_) {
      // Leave whatever was already shown - never replace real data with an
      // empty/fake list just because of a transient error.
    }
    try {
      final count =
          await _api.fetchUnreadNotificationCount(accessToken: accessToken);
      if (mounted) setState(() => _unreadCount = count);
    } catch (_) {
      // Keep the previous count rather than showing a misleading 0.
    }
  }

  AppNotification _toAppNotification(NotificationItem n) {
    final isSuccess = n.type == 'transaction_success';
    return AppNotification(
      id: n.id,
      title: n.title,
      message: n.message,
      time: _formatNotificationTime(n.createdAt),
      read: n.isRead,
      icon: isSuccess ? 'success' : 'error',
      type: isSuccess ? 'success' : 'error',
      reference: n.transactionReference,
    );
  }

  String _formatNotificationTime(DateTime? date) {
    if (date == null) return '';
    final local = date.toLocal();
    final now = DateTime.now();
    final h = local.hour.toString().padLeft(2, '0');
    final m = local.minute.toString().padLeft(2, '0');
    final isToday = local.year == now.year &&
        local.month == now.month &&
        local.day == now.day;
    final isYesterday = now.difference(local).inDays == 1 && !isToday;
    if (isToday) return "Aujourd'hui · $h:$m";
    if (isYesterday) return 'Hier · $h:$m';
    return '${local.day.toString().padLeft(2, '0')}/${local.month.toString().padLeft(2, '0')}/${local.year} · $h:$m';
  }

  /// Reading the stored session must never crash a load - an unauthenticated
  /// screen simply shows nothing personal yet, which matches reality (the
  /// app always requires OTP before reaching HomeScreen anyway).
  Future<String?> _safeAccessToken() async {
    try {
      return await _auth.currentAccessToken();
    } catch (_) {
      return null;
    }
  }

  Future<void> _markNotificationRead(AppNotification notification) async {
    final id = notification.id;
    if (id == null) return;
    final accessToken = await _safeAccessToken();
    if (accessToken == null) return;
    try {
      await _api.markNotificationRead(
          accessToken: accessToken, notificationId: id);
    } catch (_) {
      // Best-effort: the local `read` flag (already applied by
      // NotificationsScreen) is enough for this session; a future load will
      // pick up the server's real state regardless.
    }
  }

  /// Traitement séquentiel, une transaction à la fois - évite de déclencher
  /// plusieurs requêtes HTTP simultanées au démarrage si plusieurs
  /// transactions sont restées pending. Une erreur réseau/serveur sur l'une
  /// d'elles n'empêche jamais de vérifier les suivantes.
  Future<void> _reconcilePending(List<Transaction> loaded) async {
    final pendingRefs =
        loaded.where((t) => t.status == 'pending').map((t) => t.id).toSet();
    if (pendingRefs.isEmpty) return;
    String? accessToken;
    try {
      accessToken = await _auth.currentAccessToken();
    } catch (_) {
      // Reading the stored session must never crash the reconciliation - an
      // unauthenticated status check still works (both endpoints are
      // AllowAny), it just won't be attributed to a signed-in user.
    }
    var current = List<Transaction>.from(loaded);
    var changed = false;
    for (final reference in pendingRefs) {
      try {
        final result = await _api.getTransactionStatus(reference,
            accessToken: accessToken);
        if (result.isPending) continue; // toujours en cours - rien à changer
        final index = current.indexWhere((t) => t.id == reference);
        if (index == -1) continue;
        final t = current[index];
        final newStatus = result.isSuccess
            ? 'ok'
            : (result.isCancelled ? 'cancelled' : 'fail');
        current[index] = Transaction(
          id: t.id,
          operator: t.operator,
          service: t.service,
          operation: t.operation,
          phone: t.phone,
          amount: t.amount,
          paymentMethod: t.paymentMethod,
          date: t.date,
          status: newStatus,
        );
        changed = true;
      } on TransactionNotFoundException {
        // Ne jamais fabriquer un résultat pour une transaction inconnue du
        // Backend - le dossier local reste inchangé.
      } catch (_) {
        // Erreur réseau/serveur transitoire - reste pending localement,
        // une prochaine ouverture de l'app retentera.
      }
    }
    if (!changed) return;
    await TransactionService.save(current);
    if (mounted) setState(() => _transactions = current);
  }

  Future<void> _loadOperators() async {
    // Maquette hors ligne : on utilise trois opérateurs locaux pour que
    // l'interface reste visible même si le serveur bloque la requête CORS.
    const mockedOperators = [
      OperatorItem(id: 1, name: 'Orange', code: 'orange'),
      OperatorItem(id: 2, name: 'MTN', code: 'mtn'),
      OperatorItem(id: 3, name: 'Moov', code: 'moov'),
    ];

    // On simule une réponse réussie : aucun chargement ni message d'erreur
    // réseau ne doit apparaître pendant le travail sur l'écran graphique.
    setState(() {
      _operators = mockedOperators;
      _loadingOperators = false;
      _operatorsError = null;
    });
  }

  Color _operatorCardColor(String name) {
    switch (name) {
      case 'Orange':
        return const Color(0xFFFF5A00);
      case 'MTN':
        return const Color(0xFFF7C716);
      case 'Moov':
        return const Color(0xFF0057DD);
      default:
        return AppColors.primary;
    }
  }

  Color _operatorCardTextColor(String name) {
    return name == 'MTN' ? AppColors.textPrimary : Colors.white;
  }

  String _operatorLogoAsset(String name) {
    switch (name) {
      case 'Orange':
        return 'assets/images/Orange_logo.png';
      case 'MTN':
        return 'assets/images/mtn.jpg';
      case 'Moov':
        return 'assets/images/moov.jpeg';
      default:
        // No known asset for this operator - Image.asset's errorBuilder in
        // _operatorCard falls back to a generic icon instead of crashing.
        return '';
    }
  }

  Widget _operatorsSection() {
    if (_loadingOperators) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 20),
        child: Center(child: CircularProgressIndicator(color: Colors.white)),
      );
    }
    if (_operatorsError != null) {
      return Column(
        children: [
          Text(
            _operatorsError!,
            textAlign: TextAlign.center,
            style: GoogleFonts.nunito(
              color: Colors.white70,
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 14),
          TolButton(label: 'RÉESSAYER', onTap: _loadOperators),
        ],
      );
    }
    final operators = _operators ?? [];
    if (operators.isEmpty) {
      return Text(
        'Aucun opérateur disponible.',
        textAlign: TextAlign.center,
        style: GoogleFonts.nunito(
          color: Colors.white70,
          fontSize: 16,
          fontWeight: FontWeight.w700,
        ),
      );
    }
    final cards = <Widget>[];
    for (var i = 0; i < operators.length; i++) {
      final operator = operators[i];
      cards.add(_operatorCard(
        operatorId: operator.id,
        name: operator.name,
        color: _operatorCardColor(operator.name),
        logo: _operatorLogoAsset(operator.name),
        textColor: _operatorCardTextColor(operator.name),
      ));
      if (i != operators.length - 1) cards.add(const SizedBox(height: 16));
    }
    return Column(children: cards);
  }

  void _addTransaction(Transaction transaction) {
    setState(() => _transactions.insert(0, transaction));
    TransactionService.save(_transactions);
  }

  void _addNotification(AppNotification notification) {
    setState(() => _notifications.insert(0, notification));
  }

  @override
  Widget build(BuildContext context) {
    final unread = _unreadCount;

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
        child: Stack(
          children: [
            Positioned(
              left: -90,
              right: -90,
              top: 360,
              child: Transform.rotate(
                angle: -0.12,
                child: Container(
                  height: 2,
                  decoration: BoxDecoration(
                    boxShadow: [
                      BoxShadow(
                        color: const Color(0xFF65FF00).withValues(alpha: 0.55),
                        blurRadius: 38,
                        spreadRadius: 18,
                      ),
                    ],
                  ),
                ),
              ),
            ),
            SafeArea(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(28, 10, 28, 18),
                child: Column(
                  children: [
                    Row(
                      children: [
                        const Spacer(),
                        _notificationButton(unread),
                      ],
                    ),
                    const SizedBox(height: 8),
                    _logo(),
                    const SizedBox(height: 12),
                    Text(
                      'TRANSFER',
                      style: GoogleFonts.nunito(
                        fontSize: 44,
                        height: 0.98,
                        fontWeight: FontWeight.w900,
                        color: Colors.white,
                      ),
                    ),
                    Text(
                      'ON LINE',
                      style: GoogleFonts.nunito(
                        fontSize: 44,
                        height: 1,
                        fontWeight: FontWeight.w900,
                        color: const Color(0xFF66D300),
                      ),
                    ),
                    const SizedBox(height: 20),
                    Text(
                      'Souscrivez ou transférez\nvos forfaits en toute simplicité',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.nunito(
                        fontSize: 21,
                        height: 1.25,
                        fontWeight: FontWeight.w800,
                        color: Colors.white,
                      ),
                    ),
                    const SizedBox(height: 42),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        _roundService(Icons.phone_rounded),
                        const SizedBox(width: 32),
                        _roundService(Icons.language_rounded),
                        const SizedBox(width: 32),
                        _roundService(Icons.sms_rounded),
                      ],
                    ),
                    const SizedBox(height: 34),
                    Text(
                      'Choisissez votre opérateur',
                      style: GoogleFonts.nunito(
                        fontSize: 22,
                        fontWeight: FontWeight.w900,
                        color: Colors.white,
                      ),
                    ),
                    const SizedBox(height: 16),
                    _operatorsSection(),
                    const SizedBox(height: 34),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.verified_user_outlined,
                            color: Color(0xFF66D300), size: 28),
                        const SizedBox(width: 10),
                        Text(
                          'Sécurisé à 100%',
                          style: GoogleFonts.nunito(
                            fontSize: 20,
                            fontWeight: FontWeight.w900,
                            color: Colors.white,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Vos transactions sont protégées',
                      style: GoogleFonts.nunito(
                        fontSize: 17,
                        fontWeight: FontWeight.w600,
                        color: Colors.white70,
                      ),
                    ),
                    const SizedBox(height: 30),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.shield_outlined,
                            color: Color(0xFF66D300), size: 24),
                        const SizedBox(width: 9),
                        Text(
                          'AFRITECH-CI',
                          style: GoogleFonts.nunito(
                            fontSize: 20,
                            fontWeight: FontWeight.w900,
                            color: Colors.white,
                          ),
                        ),
                      ],
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

  Widget _notificationButton(int unread) {
    return GestureDetector(
      onTap: () => Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => NotificationsScreen(
            notifications: _notifications,
            onMarkRead: _markNotificationRead,
          ),
        ),
      ).then((_) => _loadNotifications()),
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Container(
            width: 60,
            height: 60,
            decoration: const BoxDecoration(
              color: Colors.white,
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.notifications_none_rounded,
                color: AppColors.textPrimary, size: 34),
          ),
          if (unread > 0)
            Positioned(
              top: -2,
              right: -2,
              child: Container(
                width: 28,
                height: 28,
                decoration: const BoxDecoration(
                    color: Colors.red, shape: BoxShape.circle),
                child: Center(
                  child: Text(
                    '$unread',
                    style: GoogleFonts.nunito(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _logo() {
    // Le logo officiel utilise des arcs en rotation, pas des icones generiques.
    return const TolLogo(size: 108);
  }

  Widget _roundService(IconData icon) {
    return Container(
      width: 74,
      height: 74,
      decoration: BoxDecoration(
        color: const Color(0xFF06B43E),
        shape: BoxShape.circle,
        boxShadow: [
          BoxShadow(
            color: const Color(0xFF06B43E).withValues(alpha: 0.6),
            blurRadius: 25,
            spreadRadius: 3,
          ),
        ],
      ),
      child: Icon(icon, color: Colors.white, size: 40),
    );
  }

  Widget _operatorCard({
    required int operatorId,
    required String name,
    required Color color,
    required String logo,
    Color textColor = Colors.white,
  }) {
    return GestureDetector(
      onTap: () => Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => Step2ServiceScreen(
            operatorId: operatorId,
            operator: name,
            onTransactionAdded: _addTransaction,
            onNotificationAdded: _addNotification,
            notifications: _notifications,
          ),
        ),
      ),
      child: Container(
        // Carte large, espacée et suffisamment haute comme dans la maquette.
        height: 124,
        margin: const EdgeInsets.symmetric(horizontal: 2),
        padding: const EdgeInsets.symmetric(horizontal: 20),
        decoration: BoxDecoration(
          color: color,
          // Moov reçoit une légère variation de bleu pour mieux ressortir.
          gradient: name == 'Moov'
              ? const LinearGradient(
                  begin: Alignment.centerLeft,
                  end: Alignment.centerRight,
                  colors: [Color(0xFF0057DD), Color(0xFF147BFF)],
                )
              : null,
          borderRadius: BorderRadius.circular(22),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.18),
              blurRadius: 16,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: Row(
          children: [
            SizedBox(
              // Le logo reste compact sur mobile pour laisser de la place au
              // nom et a la fleche de navigation.
              width: 92,
              height: 84,
              child: logo.isEmpty
                  // Placeholder local : la carte reste correcte si un logo
                  // manque dans assets/images.
                  ? Icon(Icons.business_rounded, color: textColor, size: 54)
                  : Image.asset(
                      logo,
                      fit: BoxFit.contain,
                      errorBuilder: (_, __, ___) => Icon(
                        Icons.business_rounded,
                        color: textColor,
                        size: 54,
                      ),
                    ),
            ),
            const SizedBox(width: 12),
            Expanded(
              // FittedBox reduit le texte si l'ecran est etroit. Le nom
              // reste toujours sur une seule ligne et ne se coupe jamais.
              child: FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: GoogleFonts.nunito(
                    color: textColor,
                    fontSize: 30,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
            ),
            // Flèche blanche toujours visible à droite de la carte.
            Icon(Icons.chevron_right_rounded, color: textColor, size: 42),
          ],
        ),
      ),
    );
  }
}
