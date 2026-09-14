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

  static String canonicalServiceName(String rawName, String code) {
    final lowerCode = code.toLowerCase();
    final lowerName = rawName.toLowerCase();

    if (lowerCode.contains('sms') || lowerName.contains('sms')) {
      return 'Pass SMS';
    }
    if (lowerCode.contains('internet') ||
        lowerCode.contains('data') ||
        lowerName.contains('internet') ||
        lowerName.contains('data')) {
      return 'Pass data';
    }
    if (lowerCode.contains('apple') ||
        lowerCode.contains('appel') ||
        lowerCode.contains('voix') ||
        lowerCode.contains('voice') ||
        lowerName.contains('appel') ||
        lowerName.contains('voix') ||
        lowerName.contains('voice')) {
      return 'Pass voix';
    }
    if (lowerCode.contains('credit') ||
        lowerCode.contains('transfert') ||
        lowerCode.contains('unite') ||
        lowerName.contains('crédit') ||
        lowerName.contains('credit') ||
        lowerName.contains('communication') ||
        lowerName.contains('unité') ||
        lowerName.contains('transfert')) {
      return 'Crédit de communication';
    }
    return rawName;
  }

  Future<void> _loadServices() async {
    setState(() {
      _loadingServices = true;
      _servicesError = null;
    });

    try {
      final api = widget.backendApiService ?? BackendApiService();
      final services = await api.getServices();
      if (!mounted) return;
      setState(() {
        _services = services;
        _loadingServices = false;
        if (services.isNotEmpty && _selectedServiceId == null) {
          _selectedServiceId = services.first.id;
          _service =
              canonicalServiceName(services.first.name, services.first.code);
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loadingServices = false;
        _servicesError = 'Impossible de charger les services.';
      });
    }
  }

  IconData _serviceIcon(String name) {
    if (name.contains('voix') || name.contains('Appel')) {
      return Icons.phone_rounded;
    } else if (name.contains('data') || name.contains('Internet')) {
      return Icons.language_rounded;
    } else if (name.contains('SMS')) {
      return Icons.sms_rounded;
    } else {
      return Icons.swap_horiz_rounded;
    }
  }

  Color _serviceColor(String name) {
    if (name.contains('voix') || name.contains('Appel')) {
      return const Color(0xFF079A48);
    } else if (name.contains('data') || name.contains('Internet')) {
      return const Color(0xFF1687F7);
    } else if (name.contains('SMS')) {
      return const Color(0xFF7C2CF0);
    } else {
      return const Color(0xFFF7941D);
    }
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
            child: SingleChildScrollView(
              physics: const BouncingScrollPhysics(),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SectionTitle('SERVICES DISPONIBLES'),
                    const SizedBox(height: 6),
                    _servicesSection(),
                    const SizedBox(height: 24),
                    TolButton(label: 'CONTINUER ›', onTap: _next),
                  ],
                ),
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
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (_servicesError != null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 12),
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
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 12),
          Text(
            'Aucun service disponible.',
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
    return LayoutBuilder(
      builder: (context, constraints) => Wrap(
        spacing: 10,
        runSpacing: 10,
        children: services
            .map((service) => SizedBox(
                  width: (constraints.maxWidth - 10) / 2,
                  child: _serviceTile(service),
                ))
            .toList(),
      ),
    );
  }

  Widget _serviceTile(ServiceItem service) {
    final displayName = canonicalServiceName(service.name, service.code);
    final selected = _selectedServiceId == service.id;
    final color = _serviceColor(displayName);
    return GestureDetector(
      onTap: () => setState(() {
        _service = displayName;
        _selectedServiceId = service.id;
      }),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        height: 84,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: selected ? AppColors.success : const Color(0xFFE7EAF2),
            width: selected ? 1.6 : 1,
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.05),
              blurRadius: 10,
              offset: const Offset(0, 3),
            ),
          ],
        ),
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            if (selected)
              Positioned(
                top: -6,
                right: -6,
                child: Container(
                  width: 24,
                  height: 24,
                  decoration: const BoxDecoration(
                    color: AppColors.success,
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(Icons.check_rounded,
                      color: Colors.white, size: 17),
                ),
              ),
            Center(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 6),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 38,
                      height: 38,
                      decoration: BoxDecoration(
                        color: color,
                        shape: BoxShape.circle,
                      ),
                      child: Icon(_serviceIcon(displayName),
                          color: Colors.white, size: 20),
                    ),
                    const SizedBox(height: 5),
                    FittedBox(
                      fit: BoxFit.scaleDown,
                      child: Text(
                        displayName,
                        style: GoogleFonts.nunito(
                          fontSize: 12,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textPrimary,
                        ),
                      ),
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
          backendApiService: widget.backendApiService,
        ),
      ),
    );
  }
}
