import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/models.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';

class NotificationsScreen extends StatefulWidget {
  final List<AppNotification> notifications;
  // Identity architecture (Phase 8): called in addition to the local
  // setState below, so "read" is also persisted server-side
  // (POST /notifications/<id>/read/) - never only a local UI flag. Optional
  // so this screen still works standalone (e.g. tests, sampleNotifications
  // with no backend id).
  final void Function(AppNotification)? onMarkRead;
  const NotificationsScreen(
      {super.key, required this.notifications, this.onMarkRead});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  static const _hiddenNotificationsKey = 'locally_hidden_notification_keys';
  String _query = '';
  String _filter = 'Tout';
  final Set<String> _hiddenNotificationKeys = {};
  final filters = const ['Tout', 'Réussies', 'Échecs', 'Informations'];

  @override
  void initState() {
    super.initState();
    _loadHiddenNotifications();
  }

  Future<void> _loadHiddenNotifications() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getStringList(_hiddenNotificationsKey) ?? const [];
    if (!mounted) return;
    setState(() => _hiddenNotificationKeys.addAll(saved));
  }

  String _notificationKey(AppNotification notification) {
    if (notification.id != null) return 'id:${notification.id}';
    return 'local:${notification.title}|${notification.time}|${notification.message}';
  }

  List<AppNotification> get _visibleNotifications => widget.notifications
      .where((notification) =>
          !_hiddenNotificationKeys.contains(_notificationKey(notification)))
      .toList();

  int _count(String filter) {
    final notifications = _visibleNotifications;
    if (filter == 'Tout') return notifications.length;
    if (filter == 'Réussies') {
      return notifications.where((n) => n.type == 'success').length;
    }
    if (filter == 'Échecs') {
      return notifications.where((n) => n.type == 'error').length;
    }
    return notifications.where((n) => n.type == 'info').length;
  }

  List<AppNotification> get _items {
    return _visibleNotifications.where((n) {
      final text = '${n.title} ${n.message}'.toLowerCase();
      final matchesQuery =
          _query.isEmpty || text.contains(_query.toLowerCase());
      final matchesFilter = _filter == 'Tout' ||
          (_filter == 'Réussies' && n.type == 'success') ||
          (_filter == 'Échecs' && n.type == 'error') ||
          (_filter == 'Informations' && n.type == 'info');
      return matchesQuery && matchesFilter;
    }).toList();
  }

  Map<String, List<AppNotification>> get _groups {
    final grouped = <String, List<AppNotification>>{};
    for (final item in _items) {
      final key = item.time.startsWith("Aujourd'hui")
          ? "Aujourd'hui"
          : item.time.startsWith('Hier')
              ? 'Hier'
              : 'Avant-hier';
      grouped.putIfAbsent(key, () => []).add(item);
    }
    return grouped;
  }

  @override
  Widget build(BuildContext context) {
    final unread = _visibleNotifications.where((n) => !n.read).length;
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        surfaceTintColor: Colors.white,
        elevation: 0,
        leading: IconButton(
          onPressed: () => Navigator.pop(context),
          icon: const Icon(Icons.arrow_back_rounded,
              color: AppColors.success, size: 31),
        ),
        centerTitle: true,
        title: Text(
          'Notifications',
          style: GoogleFonts.nunito(
            fontSize: 24,
            fontWeight: FontWeight.w900,
            color: AppColors.textPrimary,
          ),
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 14),
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                CircleAvatar(
                  radius: 24,
                  backgroundColor: Colors.white,
                  child: Icon(Icons.notifications_none_rounded,
                      color: AppColors.textPrimary, size: 28),
                ),
                if (unread > 0)
                  Positioned(
                    top: 2,
                    right: -2,
                    child: Container(
                      width: 20,
                      height: 20,
                      decoration: const BoxDecoration(
                        color: Colors.red,
                        shape: BoxShape.circle,
                      ),
                      child: Center(
                        child: Text(
                          '$unread',
                          style: GoogleFonts.nunito(
                            fontSize: 11,
                            fontWeight: FontWeight.w900,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
      body: CustomScrollView(
        slivers: [
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 8, 14, 0),
              child: Column(
                children: [
                  Container(
                    height: 54,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    decoration: BoxDecoration(
                      border: Border.all(color: const Color(0xFFD9DEEC)),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.search_rounded,
                            color: AppColors.textHint, size: 27),
                        const SizedBox(width: 14),
                        Expanded(
                          child: TextField(
                            onChanged: (value) =>
                                setState(() => _query = value),
                            decoration: InputDecoration(
                              hintText: 'Rechercher une notification...',
                              hintStyle: GoogleFonts.nunito(
                                fontSize: 16,
                                fontWeight: FontWeight.w600,
                                color: AppColors.textHint,
                              ),
                              border: InputBorder.none,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),
                  SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(
                      children: filters.map(_filterChip).toList(),
                    ),
                  ),
                ],
              ),
            ),
          ),
          for (final entry in _groups.entries) ...[
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 18, 14, 8),
                child: Text(
                  entry.key,
                  style: GoogleFonts.nunito(
                    fontSize: 18,
                    fontWeight: FontWeight.w900,
                    color: AppColors.textPrimary,
                  ),
                ),
              ),
            ),
            SliverList.builder(
              itemCount: entry.value.length,
              itemBuilder: (context, index) {
                final item = entry.value[index];
                return Padding(
                  padding: const EdgeInsets.fromLTRB(14, 0, 14, 10),
                  child: _notificationCard(item),
                );
              },
            ),
          ],
          SliverToBoxAdapter(
            child: TextButton.icon(
              onPressed: _hideNotificationsLocally,
              icon: const Icon(Icons.delete_outline_rounded,
                  color: Colors.red, size: 22),
              label: Text(
                'Tout effacer',
                style: GoogleFonts.nunito(
                  color: Colors.red,
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 18)),
        ],
      ),
    );
  }

  Future<void> _hideNotificationsLocally() async {
    final keys = widget.notifications.map(_notificationKey).toSet();
    final prefs = await SharedPreferences.getInstance();
    final allKeys = {..._hiddenNotificationKeys, ...keys};
    await prefs.setStringList(_hiddenNotificationsKey, allKeys.toList());
    if (!mounted) return;
    setState(() => _hiddenNotificationKeys.addAll(keys));
  }

  Widget _filterChip(String label) {
    final active = _filter == label;
    final color = label == 'Échecs'
        ? Colors.red
        : label == 'Informations'
            ? AppColors.blue
            : AppColors.success;
    return GestureDetector(
      onTap: () => setState(() => _filter = label),
      child: Container(
        margin: const EdgeInsets.only(right: 10),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 9),
        decoration: BoxDecoration(
          color: active ? AppColors.success : Colors.white,
          borderRadius: BorderRadius.circular(24),
          border: Border.all(
            color: active ? AppColors.success : const Color(0xFFD9DEEC),
          ),
        ),
        child: Row(
          children: [
            Text(
              label,
              style: GoogleFonts.nunito(
                fontSize: 15,
                fontWeight: FontWeight.w900,
                color: active ? Colors.white : AppColors.textPrimary,
              ),
            ),
            const SizedBox(width: 8),
            CircleAvatar(
              radius: 12,
              backgroundColor: active ? Colors.white : color,
              child: Text(
                '${_count(label)}',
                style: GoogleFonts.nunito(
                  fontSize: 13,
                  fontWeight: FontWeight.w900,
                  color: active ? AppColors.success : Colors.white,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _notificationCard(AppNotification item) {
    final color = _notifColor(item.type);
    final time = item.time.split('·').last.trim();
    return GestureDetector(
      onTap: () {
        final wasUnread = !item.read;
        setState(() => item.read = true);
        if (wasUnread) widget.onMarkRead?.call(item);
        Navigator.push(
          context,
          MaterialPageRoute(
              builder: (_) => NotifDetailScreen(notification: item)),
        );
      },
      child: Container(
        padding: const EdgeInsets.fromLTRB(14, 14, 12, 14),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: const Color(0xFFE4E8F2)),
        ),
        child: Row(
          children: [
            CircleAvatar(
              radius: 32,
              backgroundColor: color,
              child: Icon(_notifIcon(item.type), color: Colors.white, size: 38),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.title,
                    style: GoogleFonts.nunito(
                      fontSize: 16,
                      height: 1.1,
                      fontWeight: FontWeight.w900,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 7),
                  ...item.message.split('\n').map((line) {
                    final isTotal = line.startsWith('Total');
                    final isError = line.contains('Solde insuffisant');
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 2),
                      child: Text(
                        line,
                        style: GoogleFonts.nunito(
                          fontSize: 14,
                          height: 1.15,
                          fontWeight:
                              isTotal ? FontWeight.w900 : FontWeight.w600,
                          color: isTotal
                              ? AppColors.success
                              : isError
                                  ? Colors.red
                                  : AppColors.textPrimary,
                        ),
                      ),
                    );
                  }),
                ],
              ),
            ),
            Container(width: 1, height: 78, color: const Color(0xFFE4E8F2)),
            const SizedBox(width: 12),
            Text(
              time,
              style: GoogleFonts.nunito(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
            const SizedBox(width: 8),
            const Icon(Icons.chevron_right_rounded,
                color: AppColors.textPrimary, size: 31),
          ],
        ),
      ),
    );
  }

  Color _notifColor(String type) {
    if (type == 'error') return Colors.red;
    if (type == 'info') return AppColors.blue;
    return AppColors.success;
  }

  IconData _notifIcon(String type) {
    if (type == 'error') return Icons.close_rounded;
    if (type == 'info') return Icons.info_rounded;
    return Icons.check_rounded;
  }
}

class NotifDetailScreen extends StatelessWidget {
  final AppNotification notification;
  const NotifDetailScreen({super.key, required this.notification});

  @override
  Widget build(BuildContext context) {
    final isOk = notification.type == 'success';
    final statusColor = isOk ? AppColors.success : AppColors.red;
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        surfaceTintColor: Colors.white,
        elevation: 0,
        centerTitle: true,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded,
              color: AppColors.success, size: 36),
          onPressed: () => Navigator.pop(context),
        ),
        title: Text(
          'Détail notification',
          style: GoogleFonts.nunito(
            fontSize: 25,
            fontWeight: FontWeight.w900,
            color: AppColors.textPrimary,
          ),
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(16, 18, 16, 24),
        child: Column(
          children: [
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(16, 22, 16, 25),
              decoration: BoxDecoration(
                color: isOk ? const Color(0xFFF4FCF6) : const Color(0xFFFFF7F7),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(
                  color:
                      isOk ? const Color(0xFFB8E3C2) : const Color(0xFFF5C2C2),
                ),
              ),
              child: Column(
                children: [
                  Container(
                    width: 72,
                    height: 72,
                    decoration: BoxDecoration(
                      color: statusColor,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      isOk ? Icons.check_rounded : Icons.close_rounded,
                      color: Colors.white,
                      size: 48,
                    ),
                  ),
                  const SizedBox(height: 17),
                  Text(
                    isOk ? 'Transaction réussie' : 'Transaction échouée',
                    style: GoogleFonts.nunito(
                      fontSize: 26,
                      fontWeight: FontWeight.w900,
                      color: statusColor,
                    ),
                  ),
                  const SizedBox(height: 5),
                  Text(
                    isOk
                        ? 'Votre opération a été effectuée avec succès'
                        : 'Votre opération n\'a pas pu être effectuée',
                    style: GoogleFonts.nunito(
                      fontSize: 19,
                      fontWeight: FontWeight.w700,
                      color: AppColors.textPrimary,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),
            TolCard(
              padding: const EdgeInsets.fromLTRB(18, 7, 18, 7),
              child: Column(
                children: [
                  _infoRow(
                      Icons.receipt_long_outlined,
                      'Référence transaction',
                      _value(notification.reference, 'TRX-2025-000125'),
                      AppColors.success),
                  _operatorRow(),
                  _infoRow(
                      Icons.language_rounded,
                      'Service',
                      _value(notification.service, _inferService()),
                      AppColors.blue),
                  _infoRow(
                      Icons.sync_rounded,
                      'Type d\'opération',
                      _value(notification.operation, 'Souscription pour moi'),
                      AppColors.success),
                  _infoRow(
                      Icons.phone_in_talk_outlined,
                      'Numéro',
                      _value(
                          notification.phone,
                          _extractField('Numéro', notification.message,
                              fallback: '0701234567')),
                      AppColors.textPrimary),
                  _infoRow(
                      Icons.attach_money_rounded,
                      'Montant du forfait',
                      _value(notification.amount, _extractAmount()),
                      AppColors.textPrimary),
                  _infoRow(
                      Icons.percent_rounded,
                      'Frais de service (1%)',
                      _value(
                          notification.fee,
                          _extractField('Frais', notification.message,
                              fallback: '10 FCFA')),
                      AppColors.textPrimary,
                      info: true),
                  _infoRow(
                      Icons.calendar_today_outlined,
                      'Total débité',
                      _value(
                          notification.total,
                          _extractField('Total débité', notification.message,
                              fallback: '1010 FCFA')),
                      AppColors.success,
                      labelColor: AppColors.success,
                      valueSize: 24),
                  _infoRow(
                      Icons.account_balance_wallet_outlined,
                      'Moyen de paiement',
                      _value(notification.paymentMethod, 'CinetPay'),
                      AppColors.orange),
                  _infoRow(
                      Icons.event_available_outlined,
                      'Date',
                      _value(notification.date, '24/07/2025'),
                      AppColors.textPrimary),
                  _infoRow(
                      Icons.access_time_rounded,
                      'Heure',
                      _value(
                          notification.heure, _extractTime(notification.time)),
                      AppColors.textPrimary),
                  _infoRow(Icons.verified_user_outlined, 'Statut',
                      isOk ? 'Réussie' : 'Échouée', statusColor,
                      last: true),
                ],
              ),
            ),
            const SizedBox(height: 16),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
              decoration: BoxDecoration(
                color: const Color(0xFFF2F8FF),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFC4DDFC)),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 46,
                    height: 46,
                    decoration: const BoxDecoration(
                      color: AppColors.blue,
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.info_rounded,
                        color: Colors.white, size: 32),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Message',
                          style: GoogleFonts.nunito(
                            fontSize: 18,
                            fontWeight: FontWeight.w900,
                            color: AppColors.textPrimary,
                          ),
                        ),
                        Text(
                          'Votre forfait Internet a été activé avec succès.',
                          style: GoogleFonts.nunito(
                            fontSize: 16,
                            height: 1.25,
                            fontWeight: FontWeight.w700,
                            color: AppColors.textPrimary,
                          ),
                        ),
                        const SizedBox(height: 8),
                        const Divider(height: 1, color: Color(0xFFCFE0F5)),
                        const SizedBox(height: 8),
                        _messageLine('Montant du forfait :', _extractAmount(),
                            AppColors.textPrimary),
                        _messageLine(
                            'Frais de service :',
                            _extractField('Frais', notification.message,
                                fallback: '10 FCFA'),
                            AppColors.textPrimary),
                        _messageLine(
                            'Total débité :',
                            _extractField('Total débité', notification.message,
                                fallback: '1010 FCFA'),
                            AppColors.success),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              height: 58,
              child: ElevatedButton(
                onPressed: () => Navigator.pop(context),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.success,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8),
                  ),
                  elevation: 0,
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const Icon(Icons.receipt_long_outlined,
                        color: Colors.white, size: 27),
                    const SizedBox(width: 15),
                    Text(
                      'VOIR DANS L\'HISTORIQUE',
                      style: GoogleFonts.nunito(
                        fontSize: 18,
                        fontWeight: FontWeight.w900,
                        color: Colors.white,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 18),
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: Text(
                'Fermer',
                style: GoogleFonts.nunito(
                  fontSize: 18,
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

  String _value(String? value, String fallback) {
    return value == null || value.trim().isEmpty ? fallback : value;
  }

  String _extractField(String key, String message, {String fallback = '-'}) {
    final lines = message.split('\n');
    final line = lines.firstWhere(
      (l) => l.toLowerCase().startsWith(key.toLowerCase()) && l.contains(':'),
      orElse: () => '',
    );
    return line.isEmpty
        ? fallback
        : line.split(':').sublist(1).join(':').trim();
  }

  String _extractAmount() {
    final value = _extractField('Montant forfait', notification.message);
    if (value != '-') return value;
    return _extractField('Montant demandé', notification.message,
        fallback: '1000 FCFA');
  }

  String _extractTime(String time) {
    final parts = time.split('·');
    return parts.length > 1 ? parts[1].trim() : '10:45';
  }

  String _inferOperator() {
    final text =
        '${notification.operator ?? ''} ${notification.title}'.toLowerCase();
    if (text.contains('mtn')) return 'MTN';
    if (text.contains('moov')) return 'Moov';
    return 'Orange';
  }

  String _inferService() {
    final text =
        '${notification.service ?? ''} ${notification.title}'.toLowerCase();
    if (text.contains('appel')) return 'Appels';
    if (text.contains('sms')) return 'SMS';
    return 'Internet';
  }

  Widget _operatorRow() {
    final operator = _value(notification.operator, _inferOperator());
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFFE8EAF1))),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 46,
            child: Align(
              alignment: Alignment.centerLeft,
              child: Image.asset(
                'assets/images/Orange_logo.png',
                width: 31,
                height: 31,
                fit: BoxFit.contain,
              ),
            ),
          ),
          Expanded(
            child: Text(
              'Opérateur',
              style: GoogleFonts.nunito(
                fontSize: 17,
                color: AppColors.textPrimary,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          Text(
            operator,
            textAlign: TextAlign.right,
            style: GoogleFonts.nunito(
              fontSize: 18,
              fontWeight: FontWeight.w900,
              color: AppColors.orange,
            ),
          ),
        ],
      ),
    );
  }

  Widget _messageLine(String label, String value, Color color) {
    return Text.rich(
      TextSpan(
        text: '$label ',
        children: [TextSpan(text: value)],
      ),
      style: GoogleFonts.nunito(
        fontSize: 16,
        height: 1.25,
        fontWeight:
            color == AppColors.success ? FontWeight.w900 : FontWeight.w700,
        color: color,
      ),
    );
  }

  Widget _infoRow(IconData icon, String key, String val, Color color,
      {bool last = false,
      bool info = false,
      Color? labelColor,
      double valueSize = 17}) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10),
      decoration: BoxDecoration(
        border: last
            ? null
            : const Border(bottom: BorderSide(color: Color(0xFFE8EAF1))),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 46,
            child: Align(
              alignment: Alignment.centerLeft,
              child: Icon(icon, color: color, size: 30),
            ),
          ),
          Expanded(
            child: Row(
              children: [
                Flexible(
                  child: Text(
                    key,
                    style: GoogleFonts.nunito(
                      fontSize: 17,
                      color: labelColor ?? AppColors.textPrimary,
                      fontWeight: labelColor == null
                          ? FontWeight.w700
                          : FontWeight.w900,
                    ),
                  ),
                ),
                if (info) ...[
                  const SizedBox(width: 8),
                  const Icon(Icons.info_outline_rounded,
                      color: AppColors.success, size: 19),
                ],
              ],
            ),
          ),
          const SizedBox(width: 12),
          Flexible(
            child: Text(
              val,
              textAlign: TextAlign.right,
              style: GoogleFonts.nunito(
                fontSize: valueSize,
                fontWeight: FontWeight.w900,
                color: color,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
