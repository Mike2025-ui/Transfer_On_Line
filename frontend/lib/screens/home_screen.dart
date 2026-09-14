import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../models/models.dart';
import '../services/backend_api_service.dart';
import '../services/notification_service.dart';
import '../services/transaction_service.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';
import 'notifications_screen.dart';
import 'step2_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, this.backendApiService});

  final BackendApiService? backendApiService;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late final BackendApiService _api =
      widget.backendApiService ?? BackendApiService();
  List<AppNotification> _notifications = [];
  List<Transaction> _transactions = [];
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
  }

  Future<void> _loadNotifications() async {
    final saved = await NotificationService.load();
    if (!mounted) return;
    setState(() {
      _notifications = saved;
      _unreadCount = saved.where((notification) => !notification.read).length;
    });
  }

  Future<void> _markNotificationRead(AppNotification notification) async {
    final index = _notifications.indexWhere(
      (item) =>
          item.id == notification.id &&
          item.reference == notification.reference &&
          item.title == notification.title &&
          item.time == notification.time,
    );
    if (index == -1 || _notifications[index].read) return;
    setState(() {
      _notifications[index].read = true;
      _unreadCount = _notifications.where((item) => !item.read).length;
    });
    await NotificationService.save(_notifications);
  }

  /// Traitement séquentiel, une transaction à la fois - évite de déclencher
  /// plusieurs requêtes HTTP simultanées au démarrage si plusieurs
  /// transactions sont restées pending. Une erreur réseau/serveur sur l'une
  /// d'elles n'empêche jamais de vérifier les suivantes.
  Future<void> _reconcilePending(List<Transaction> loaded) async {
    final pendingRefs =
        loaded.where((t) => t.status == 'pending').map((t) => t.id).toSet();
    if (pendingRefs.isEmpty) return;
    var current = List<Transaction>.from(loaded);
    var changed = false;
    for (final reference in pendingRefs) {
      try {
        final result = await _api.getTransactionStatus(reference);
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
    try {
      final operators = await _api.getOperators();
      if (!mounted) return;
      const displayOrder = {'Orange': 0, 'MTN': 1, 'Moov': 2};
      operators.sort((a, b) =>
          (displayOrder[a.name] ?? 99).compareTo(displayOrder[b.name] ?? 99));
      setState(() {
        _operators = operators;
        _loadingOperators = false;
        _operatorsError = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loadingOperators = false;
        _operatorsError = 'Impossible de charger les opérateurs.';
      });
    }
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

  String _operatorLogoAsset(String name, [String? logoSlug]) {
    final slug = (logoSlug ?? name).toLowerCase();
    switch (slug) {
      case 'orange':
        return 'assets/images/Orange_logo.png';
      case 'mtn':
        return 'assets/images/mtn.jpg';
      case 'moov':
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
      return Column(
        children: [
          Text(
            'Aucun opérateur disponible.',
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
    final cards = <Widget>[];
    for (var i = 0; i < operators.length; i++) {
      final operator = operators[i];
      cards.add(_operatorCard(
        operatorId: operator.id,
        name: operator.name,
        color: _operatorCardColor(operator.name),
        logo: _operatorLogoAsset(operator.name, operator.logo),
        textColor: _operatorCardTextColor(operator.name),
      ));
      if (i != operators.length - 1) cards.add(const SizedBox(height: 18));
    }
    return Column(children: cards);
  }

  void _addTransaction(Transaction transaction) {
    setState(() => _transactions.insert(0, transaction));
    TransactionService.save(_transactions);
  }

  void _addNotification(AppNotification notification) {
    setState(() {
      _notifications.insert(0, notification);
      _unreadCount = _notifications.where((item) => !item.read).length;
    });
    NotificationService.save(_notifications);
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
              child: LayoutBuilder(
                builder: (context, constraints) {
                  return SingleChildScrollView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    child: ConstrainedBox(
                      constraints: BoxConstraints(
                        minHeight: constraints.maxHeight,
                      ),
                      child: Center(
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 580),
                          child: Padding(
                            padding: const EdgeInsets.fromLTRB(18, 6, 18, 16),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              crossAxisAlignment: CrossAxisAlignment.center,
                              children: [
                                Row(
                                  children: [
                                    const Spacer(),
                                    _notificationButton(unread),
                                  ],
                                ),
                                const SizedBox(height: 6),
                                _logo(),
                                const SizedBox(height: 6),
                                Text(
                                  'TRANSFER',
                                  style: GoogleFonts.nunito(
                                    fontSize: 30,
                                    height: 0.98,
                                    fontWeight: FontWeight.w900,
                                    color: Colors.white,
                                  ),
                                ),
                                Text(
                                  'ON LINE',
                                  style: GoogleFonts.nunito(
                                    fontSize: 30,
                                    height: 1,
                                    fontWeight: FontWeight.w900,
                                    color: const Color(0xFF66D300),
                                  ),
                                ),
                                const SizedBox(height: 6),
                                Text(
                                  'Souscrivez ou transférez\nvos forfaits en toute simplicité',
                                  textAlign: TextAlign.center,
                                  style: GoogleFonts.nunito(
                                    fontSize: 14,
                                    height: 1.3,
                                    fontWeight: FontWeight.w800,
                                    color: Colors.white,
                                  ),
                                ),
                                const SizedBox(height: 10),
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: [
                                    _roundService(Icons.phone_rounded),
                                    const SizedBox(width: 12),
                                    _roundService(Icons.language_rounded),
                                    const SizedBox(width: 12),
                                    _roundService(Icons.sms_rounded),
                                  ],
                                ),
                                const SizedBox(height: 12),
                                Text(
                                  'Choisissez votre opérateur',
                                  style: GoogleFonts.nunito(
                                    fontSize: 18,
                                    fontWeight: FontWeight.w900,
                                    color: Colors.white,
                                  ),
                                ),
                                const SizedBox(height: 10),
                                _operatorsSection(),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                  );
                },
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
            width: 44,
            height: 44,
            decoration: const BoxDecoration(
              color: Colors.white,
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.notifications_none_rounded,
                color: AppColors.textPrimary, size: 25),
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
    return Stack(
      alignment: Alignment.center,
      children: [
        Icon(Icons.sync_rounded, color: Colors.orange.shade600, size: 82),
        const Icon(Icons.sync_rounded, color: Color(0xFF0BA23E), size: 52),
      ],
    );
  }

  Widget _roundService(IconData icon) {
    return Container(
      width: 52,
      height: 52,
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
      child: Icon(icon, color: Colors.white, size: 24),
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
        height: 76,
        margin: const EdgeInsets.symmetric(horizontal: 2),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        decoration: BoxDecoration(
          color: color,
          gradient: name == 'Moov'
              ? const LinearGradient(
                  begin: Alignment.centerLeft,
                  end: Alignment.centerRight,
                  colors: [Color(0xFF0057DD), Color(0xFF147BFF)],
                )
              : null,
          borderRadius: BorderRadius.circular(24),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.20),
              blurRadius: 18,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: Row(
          children: [
            SizedBox(
              width: 66,
              height: 60,
              child: logo.isEmpty
                  ? Icon(Icons.business_rounded, color: textColor, size: 50)
                  : Image.asset(
                      logo,
                      fit: BoxFit.contain,
                      errorBuilder: (_, __, ___) => Icon(
                        Icons.business_rounded,
                        color: textColor,
                        size: 50,
                      ),
                    ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: GoogleFonts.nunito(
                    color: textColor,
                    fontSize: 22,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
            ),
            Icon(Icons.chevron_right_rounded, color: textColor, size: 34),
          ],
        ),
      ),
    );
  }
}
