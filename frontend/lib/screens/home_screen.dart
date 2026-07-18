import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../models/models.dart';
import '../services/transaction_service.dart';
import '../theme/app_theme.dart';
import 'notifications_screen.dart';
import 'step2_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final List<AppNotification> _notifications = sampleNotifications;
  List<Transaction> _transactions = List.from(sampleTransactions);

  @override
  void initState() {
    super.initState();
    _loadTransactions();
  }

  Future<void> _loadTransactions() async {
    final saved = await TransactionService.load();
    if (saved.isNotEmpty && mounted) {
      setState(() => _transactions = saved);
    }
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
    final unread = _notifications.where((n) => !n.read).length;

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
                        Text(
                          '9:41',
                          style: GoogleFonts.nunito(
                            color: Colors.white,
                            fontSize: 22,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
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
                    _operatorCard(
                      name: 'Orange',
                      color: const Color(0xFFFF5A00),
                      logo: 'assets/images/Orange_logo.png',
                    ),
                    const SizedBox(height: 16),
                    _operatorCard(
                      name: 'MTN',
                      color: const Color(0xFFF7C716),
                      logo: 'assets/images/mtn.jpg',
                      textColor: AppColors.textPrimary,
                    ),
                    const SizedBox(height: 16),
                    _operatorCard(
                      name: 'Moov',
                      color: const Color(0xFF0057DD),
                      logo: 'assets/images/moov.jpeg',
                    ),
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
          builder: (_) => NotificationsScreen(notifications: _notifications),
        ),
      ).then((_) {
        if (mounted) setState(() {});
      }),
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
    return Stack(
      alignment: Alignment.center,
      children: [
        Icon(Icons.sync_rounded, color: Colors.orange.shade600, size: 104),
        const Icon(Icons.sync_rounded, color: Color(0xFF0BA23E), size: 65),
      ],
    );
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
            operator: name,
            onTransactionAdded: _addTransaction,
            onNotificationAdded: _addNotification,
          ),
        ),
      ),
      child: Container(
        height: 106,
        padding: const EdgeInsets.symmetric(horizontal: 28),
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(18),
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
              width: 112,
              child: Image.asset(
                logo,
                fit: BoxFit.contain,
                errorBuilder: (_, __, ___) =>
                    Icon(Icons.business_rounded, color: textColor, size: 54),
              ),
            ),
            const SizedBox(width: 24),
            Expanded(
              child: Text(
                name,
                style: GoogleFonts.nunito(
                  color: textColor,
                  fontSize: 30,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ),
            Icon(Icons.chevron_right_rounded, color: textColor, size: 46),
          ],
        ),
      ),
    );
  }
}
