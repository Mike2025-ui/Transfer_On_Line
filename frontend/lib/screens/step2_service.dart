import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme/app_theme.dart';
import '../models/models.dart';
import '../services/backend_api_service.dart';
import '../widgets/widgets.dart';
import 'step3_info.dart';

class Step2ServiceScreen extends StatefulWidget {
  final int operatorId;
  final String operator;
  final Function(Transaction) onTransactionAdded;
  final Function(AppNotification) onNotificationAdded;
  final List<AppNotification> notifications;
  final BackendApiService? backendApiService;

  const Step2ServiceScreen({
    super.key,
    required this.operatorId,
    required this.operator,
    required this.onTransactionAdded,
    required this.onNotificationAdded,
    required this.notifications,
    this.backendApiService,
  });

  @override
  State<Step2ServiceScreen> createState() => _Step2ServiceScreenState();
}

class _Step2ServiceScreenState extends State<Step2ServiceScreen> {
  String? _service;
  int? _selectedServiceId;
  List<ServiceItem>? _services;
  bool _loadingServices = true;
  String? _servicesError;

  @override
  void initState() {
    super.initState();
    _loadServices();
  }

  Future<void> _loadServices() async {
    try {
      final services =
          await (widget.backendApiService ?? BackendApiService()).getServices();
      const displayOrder = {'Appels': 0, 'Internet': 1, 'Crédit': 2, 'SMS': 3};
      final visibleServices = services.toList()
        ..sort((a, b) => (displayOrder[a.name.split(' (').first] ?? 99)
            .compareTo(displayOrder[b.name.split(' (').first] ?? 99));
      if (!mounted) return;
      setState(() {
        _services = visibleServices.isEmpty ? null : visibleServices;
        _loadingServices = false;
        _servicesError = null;
        if (visibleServices.isNotEmpty) {
          _service = visibleServices.first.name;
          _selectedServiceId = visibleServices.first.id;
        }
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loadingServices = false;
        _servicesError = 'Impossible de charger les services.';
      });
    }
  }

  IconData _serviceIcon(String name) {
    final normalized = name.toLowerCase();
    if (normalized.contains('voix') || normalized.contains('appel')) {
      return Icons.phone_rounded;
    }
    if (normalized.contains('data') || normalized.contains('internet')) {
      return Icons.language_rounded;
    }
    if (normalized.contains('sms')) return Icons.sms_rounded;
    return Icons.account_balance_wallet_rounded;
  }

  Color _serviceColor(String name) {
    final normalized = name.toLowerCase();
    if (normalized.contains('voix') || normalized.contains('appel')) {
      return const Color(0xFF079A48);
    }
    if (normalized.contains('data') || normalized.contains('internet')) {
      return const Color(0xFF1687F7);
    }
    if (normalized.contains('sms')) return const Color(0xFF7C2CF0);
    return const Color(0xFFCE8A00);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: Column(
        children: [
          const GreenHeader(
            title: 'Choisir le service',
            subtitle: 'Sélectionnez votre service',
            icon: 'service',
            step: 2,
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  const Center(child: SectionTitle('SERVICES DISPONIBLES')),
                  const SizedBox(height: 4),
                  _servicesSection(),
                  const Spacer(),
                  TolButton(label: 'CONTINUER ›', onTap: _next),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _servicesSection() {
    if (_loadingServices) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 20),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (_servicesError != null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            _servicesError!,
            textAlign: TextAlign.center,
            style: GoogleFonts.nunito(
              color: AppColors.textSecondary,
              fontSize: 15,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 12),
          TolButton(label: 'RÉESSAYER', onTap: _loadServices),
        ],
      );
    }
    final services = _services ?? [];
    if (services.isEmpty) {
      return Text(
        'Aucun service disponible.',
        textAlign: TextAlign.center,
        style: GoogleFonts.nunito(
          color: AppColors.textSecondary,
          fontSize: 15,
          fontWeight: FontWeight.w700,
        ),
      );
    }
    return LayoutBuilder(
      builder: (context, constraints) => Wrap(
        alignment: WrapAlignment.center,
        spacing: 10,
        runSpacing: 10,
        children: services
            .map((service) => SizedBox(
                  width: (constraints.maxWidth - 18) / 2,
                  child: _serviceTile(service),
                ))
            .toList(),
      ),
    );
  }

  Widget _serviceTile(ServiceItem service) {
    final selected = _service == service.name;
    final color = _serviceColor(service.name);
    return GestureDetector(
      onTap: () => setState(() {
        _service = service.name;
        _selectedServiceId = service.id;
      }),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        height: 86,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: selected ? AppColors.success : const Color(0xFFE7EAF2),
            width: selected ? 1.6 : 1,
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.06),
              blurRadius: 15,
              offset: const Offset(0, 5),
            ),
          ],
        ),
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            if (selected)
              Positioned(
                top: -10,
                right: -8,
                child: Container(
                  width: 30,
                  height: 30,
                  decoration: const BoxDecoration(
                    color: AppColors.success,
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(Icons.check_rounded,
                      color: Colors.white, size: 23),
                ),
              ),
            Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 38,
                    height: 38,
                    padding: const EdgeInsets.all(7),
                    decoration: BoxDecoration(
                      color: color,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(_serviceIcon(service.name),
                        color: Colors.white, size: 20),
                  ),
                  const SizedBox(height: 3),
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text(
                      service.name,
                      style: GoogleFonts.nunito(
                        fontSize: 11,
                        fontWeight: FontWeight.w900,
                        color: AppColors.textPrimary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _next() {
    final service = _service;
    final serviceId = _selectedServiceId;
    if (service == null || serviceId == null) return;
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => Step3InfoScreen(
          operatorId: widget.operatorId,
          serviceId: serviceId,
          operator: widget.operator,
          service: service,
          onTransactionAdded: widget.onTransactionAdded,
          onNotificationAdded: widget.onNotificationAdded,
          notifications: widget.notifications,
        ),
      ),
    );
  }
}
