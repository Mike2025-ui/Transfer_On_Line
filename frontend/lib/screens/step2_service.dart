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
  late final BackendApiService _api = widget.backendApiService ?? BackendApiService();

  String? _service;
  int? _selectedServiceId;
  String _operation = 'Souscription pour moi';

  List<ServiceItem>? _services;
  bool _loadingServices = true;
  String? _servicesError;

  @override
  void initState() {
    super.initState();
    _loadServices();
  }

  Future<void> _loadServices() async {
    setState(() {
      _loadingServices = true;
      _servicesError = null;
    });
    try {
      final services = await _api.getServices();
      if (!mounted) return;
      setState(() {
        _services = services;
        _loadingServices = false;
        _service = services.isNotEmpty ? services.first.name : null;
        _selectedServiceId = services.isNotEmpty ? services.first.id : null;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _servicesError = 'Impossible de charger les services.';
        _loadingServices = false;
      });
    }
  }

  IconData _serviceIcon(String name) {
    switch (name) {
      case 'Appels':
        return Icons.phone_rounded;
      case 'Internet':
        return Icons.language_rounded;
      case 'SMS':
        return Icons.sms_rounded;
      default:
        return Icons.apps_rounded;
    }
  }

  String _serviceSubtitle(String name) {
    switch (name) {
      case 'Appels':
        return 'Forfaits voix';
      case 'Internet':
        return 'Forfaits data';
      case 'SMS':
        return 'Forfaits SMS';
      default:
        return '';
    }
  }

  Color _serviceColor(String name) {
    switch (name) {
      case 'Appels':
        return const Color(0xFF079A48);
      case 'Internet':
        return const Color(0xFF1687F7);
      case 'SMS':
        return const Color(0xFF7C2CF0);
      default:
        return AppColors.primary;
    }
  }

  final operations = const [
    {
      'name': 'Souscription pour moi',
      'sub': 'Acheter un forfait pour\nmon propre numéro',
      'icon': Icons.post_add_rounded,
      'color': 0xFF078C3A,
    },
    {
      'name': 'Souscription pour un tiers',
      'sub': 'Acheter un forfait pour\nun autre numéro',
      'icon': Icons.group_rounded,
      'color': 0xFF1687F7,
    },
    {
      'name': 'Transfert pour moi',
      'sub': 'Transférer un forfait de mon\nnuméro vers un autre',
      'icon': Icons.swap_horiz_rounded,
      'color': 0xFFFF7900,
    },
    {
      'name': 'Transfert pour un tiers',
      'sub': 'Transférer un forfait d\'un autre\nnuméro vers un autre',
      'icon': Icons.compare_arrows_rounded,
      'color': 0xFF842DE8,
    },
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: Column(
        children: [
          const GreenHeader(
            title: 'Choisir le service',
            subtitle:
                'Sélectionnez le type de service\net l’opération souhaitée',
            icon: 'service',
            step: 2,
          ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 24, 20, 22),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SectionTitle('1. TYPE DE SERVICE'),
                  const SizedBox(height: 8),
                  _servicesSection(),
                  const SizedBox(height: 26),
                  const SectionTitle('2. TYPE D’OPÉRATION'),
                  const SizedBox(height: 8),
                  TolCard(
                    padding: EdgeInsets.zero,
                    child: Column(
                      children: operations.asMap().entries.map((entry) {
                        return _operationRow(
                          entry.value,
                          last: entry.key == operations.length - 1,
                        );
                      }).toList(),
                    ),
                  ),
                  const SizedBox(height: 26),
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
    return Row(
      children: services.map((service) {
        final isLast = service == services.last;
        return Expanded(
          child: Padding(
            padding: EdgeInsets.only(right: isLast ? 0 : 14),
            child: _serviceTile(service),
          ),
        );
      }).toList(),
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
        height: 142,
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
                    width: 50,
                    height: 50,
                    decoration: BoxDecoration(
                      color: color,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(_serviceIcon(service.name),
                        color: Colors.white, size: 30),
                  ),
                  const SizedBox(height: 20),
                  Text(
                    service.name,
                    style: GoogleFonts.nunito(
                      fontSize: 16,
                      fontWeight: FontWeight.w900,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  Text(
                    _serviceSubtitle(service.name),
                    style: GoogleFonts.nunito(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.textSecondary,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _operationRow(Map<String, dynamic> op, {required bool last}) {
    final selected = _operation == op['name'];
    final color = Color(op['color'] as int);
    return InkWell(
      onTap: () => setState(() => _operation = op['name'] as String),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        decoration: BoxDecoration(
          border: last
              ? null
              : const Border(bottom: BorderSide(color: Color(0xFFECEEF5))),
        ),
        child: Row(
          children: [
            Container(
              width: 58,
              height: 58,
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              child:
                  Icon(op['icon'] as IconData, color: Colors.white, size: 30),
            ),
            const SizedBox(width: 18),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    op['name'] as String,
                    style: GoogleFonts.nunito(
                      fontSize: 17,
                      fontWeight: FontWeight.w900,
                      color: AppColors.textPrimary,
                      height: 1.1,
                    ),
                  ),
                  const SizedBox(height: 5),
                  Text(
                    op['sub'] as String,
                    style: GoogleFonts.nunito(
                      fontSize: 15,
                      height: 1.25,
                      fontWeight: FontWeight.w600,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ],
              ),
            ),
            Container(
              width: 26,
              height: 26,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(
                  color: selected ? AppColors.success : const Color(0xFFD8DCE8),
                  width: 2,
                ),
              ),
              child: selected
                  ? Center(
                      child: Container(
                        width: 16,
                        height: 16,
                        decoration: const BoxDecoration(
                          color: AppColors.success,
                          shape: BoxShape.circle,
                        ),
                      ),
                    )
                  : null,
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
          operation: _operation,
          onTransactionAdded: widget.onTransactionAdded,
          onNotificationAdded: widget.onNotificationAdded,
          notifications: widget.notifications,
        ),
      ),
    );
  }
}
