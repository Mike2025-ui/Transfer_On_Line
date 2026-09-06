import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme/app_theme.dart';
import '../models/models.dart';
import '../services/backend_api_service.dart';
import '../widgets/widgets.dart';
import 'step4_payment.dart';

class Step3InfoScreen extends StatefulWidget {
  final int operatorId;
  final int serviceId;
  final String operator;
  final String service;
  final String operation;
  final Function(Transaction) onTransactionAdded;
  final Function(AppNotification) onNotificationAdded;
  final List<AppNotification> notifications;
  final BackendApiService? backendApiService;

  const Step3InfoScreen({
    super.key,
    required this.operatorId,
    required this.serviceId,
    required this.operator,
    required this.service,
    required this.operation,
    required this.onTransactionAdded,
    required this.onNotificationAdded,
    required this.notifications,
    this.backendApiService,
  });

  @override
  State<Step3InfoScreen> createState() => _Step3InfoScreenState();
}

class _Step3InfoScreenState extends State<Step3InfoScreen> {
  late final BackendApiService _api =
      widget.backendApiService ?? BackendApiService();
  final _phoneCtrl = TextEditingController();
  final _amountCtrl = TextEditingController(text: '1000');
  // Default, shown immediately - identical to the values this screen has
  // always shown. Only replaced in place if the backend has specific
  // amounts configured for this (operator, service); left untouched on an
  // empty result or a network error, so the screen never looks different
  // just because a fetch failed or hasn't resolved yet.
  List<int> _quickAmounts = [500, 1000, 2000, 5000, 10000, 0];
  int _selectedAmount = 1000;

  @override
  void initState() {
    super.initState();
    _loadAmounts();
  }

  Future<void> _loadAmounts() async {
    try {
      final amounts =
          await _api.getAvailableAmounts(widget.operatorId, widget.serviceId);
      if (!mounted || amounts.isEmpty) return;
      setState(() {
        _quickAmounts = [
          ...amounts.map((a) => a.amount.round()),
          0, // "Autre" (custom amount) stays available even with a fixed catalog.
        ];
      });
    } catch (_) {
      // Silent: the default _quickAmounts above is already a fully working
      // fallback, and this screen has never shown a loading/error state.
    }
  }

  bool get _isTransfer => widget.operation.contains('Transfert');
  bool get _isThird => widget.operation.contains('tiers');

  Color get _modeColor {
    if (_isTransfer && _isThird) return AppColors.purple;
    if (_isTransfer) return const Color(0xFFFF7900);
    if (_isThird) return AppColors.blue;
    return AppColors.primary;
  }

  Color get _modeBg {
    if (_isTransfer && _isThird) return AppColors.purpleLight;
    if (_isTransfer) return AppColors.orangeLight;
    if (_isThird) return AppColors.blueLight;
    return AppColors.primaryLight;
  }

  IconData get _modeIcon {
    if (_isTransfer && _isThird) return Icons.compare_arrows_rounded;
    if (_isTransfer) return Icons.swap_horiz_rounded;
    if (_isThird) return Icons.group_rounded;
    return Icons.person_outline_rounded;
  }

  @override
  void dispose() {
    _phoneCtrl.dispose();
    _amountCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: Column(
        children: [
          const GreenHeader(
            title: 'Saisir les informations',
            subtitle: 'Entrez le numéro et le montant',
            icon: 'info',
            step: 3,
          ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(18, 26, 18, 22),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _modeBanner(),
                  const SizedBox(height: 26),
                  _label('Numéro'),
                  const SizedBox(height: 10),
                  _inputShell(
                    leading: Icons.phone_in_talk_outlined,
                    trailing: _isThird
                        ? Icons.contacts_outlined
                        : Icons.person_outline_rounded,
                    child: TextField(
                      controller: _phoneCtrl,
                      keyboardType: TextInputType.phone,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      style: _fieldStyle(),
                      decoration: _inputDecoration('Entrez le numéro'),
                    ),
                  ),
                  const SizedBox(height: 10),
                  _hint('Exemple : 07XXXXXXXX'),
                  const SizedBox(height: 26),
                  _label('Montant'),
                  const SizedBox(height: 10),
                  _inputShell(
                    leading: Icons.attach_money_rounded,
                    trailing: Icons.keyboard_arrow_down_rounded,
                    trailingText: 'FCFA',
                    child: TextField(
                      controller: _amountCtrl,
                      keyboardType: TextInputType.number,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      onChanged: (value) {
                        setState(
                            () => _selectedAmount = int.tryParse(value) ?? 0);
                      },
                      style: _fieldStyle(),
                      decoration: _inputDecoration('Entrez le montant'),
                    ),
                  ),
                  const SizedBox(height: 10),
                  _hint(_isTransfer
                      ? 'Entrez le montant à transférer'
                      : 'Entrez le montant à souscrire ou transférer'),
                  const SizedBox(height: 22),
                  Row(
                    children: [
                      const Icon(Icons.flash_on_rounded,
                          color: AppColors.success, size: 25),
                      const SizedBox(width: 8),
                      Text(
                        'Montants rapides',
                        style: GoogleFonts.nunito(
                          fontSize: 17,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textPrimary,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  GridView.count(
                    crossAxisCount: 3,
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    mainAxisSpacing: 10,
                    crossAxisSpacing: 10,
                    // Une hauteur fixe evite que le contenu des boutons
                    // depasse sur les petits ecrans comme le Samsung S8.
                    mainAxisExtent: 62,
                    children: _quickAmounts.map((amount) {
                      final selected = amount == 0
                          ? !_quickAmounts.contains(_selectedAmount)
                          : _selectedAmount == amount;
                      return QuickAmountButton(
                        amount: amount,
                        selected: selected,
                        onTap: () {
                          if (amount == 0) {
                            _showCustomAmountDialog();
                          } else {
                            setState(() {
                              _selectedAmount = amount;
                              _amountCtrl.text = '$amount';
                            });
                          }
                        },
                      );
                    }).toList(),
                  ),
                  const SizedBox(height: 22),
                  TolButton(label: 'CONTINUER ›', onTap: _next),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _modeBanner() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
      decoration: BoxDecoration(
        color: _modeBg,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Container(
            width: 70,
            height: 70,
            decoration:
                BoxDecoration(color: _modeColor, shape: BoxShape.circle),
            child: Icon(_modeIcon, color: Colors.white, size: 38),
          ),
          const SizedBox(width: 20),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.operation,
                  style: GoogleFonts.nunito(
                    fontSize: 20,
                    height: 1.08,
                    fontWeight: FontWeight.w900,
                    color: AppColors.textPrimary,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  _isThird
                      ? 'Saisissez le numéro du bénéficiaire.'
                      : 'Saisissez votre numéro Orange, MTN ou Moov.',
                  style: GoogleFonts.nunito(
                    fontSize: 16,
                    height: 1.2,
                    fontWeight: FontWeight.w600,
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _inputShell({
    required IconData leading,
    required IconData trailing,
    required Widget child,
    String? trailingText,
  }) {
    return Container(
      height: 68,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE6E9F2)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.035),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Row(
        children: [
          Icon(leading, color: AppColors.textPrimary, size: 30),
          const SizedBox(width: 18),
          Expanded(child: child),
          Container(width: 1, height: 34, color: const Color(0xFFE2E5EF)),
          const SizedBox(width: 14),
          if (trailingText != null)
            Text(
              trailingText,
              style: GoogleFonts.nunito(
                fontSize: 17,
                fontWeight: FontWeight.w900,
                color: AppColors.success,
              ),
            ),
          const SizedBox(width: 8),
          Icon(trailing, color: AppColors.success, size: 28),
        ],
      ),
    );
  }

  TextStyle _fieldStyle() {
    return GoogleFonts.nunito(
      fontSize: 17,
      fontWeight: FontWeight.w700,
      color: AppColors.textPrimary,
    );
  }

  InputDecoration _inputDecoration(String hint) {
    return InputDecoration(
      hintText: hint,
      hintStyle: GoogleFonts.nunito(
        fontSize: 17,
        fontWeight: FontWeight.w600,
        color: AppColors.textHint,
      ),
      border: InputBorder.none,
    );
  }

  Widget _label(String text) {
    return Text(
      text,
      style: GoogleFonts.nunito(
        fontSize: 18,
        fontWeight: FontWeight.w900,
        color: AppColors.textPrimary,
      ),
    );
  }

  Widget _hint(String text) {
    return Text(
      text,
      style: GoogleFonts.nunito(
        fontSize: 15,
        fontWeight: FontWeight.w600,
        color: AppColors.textSecondary,
      ),
    );
  }

  void _showCustomAmountDialog() {
    final controller = TextEditingController();
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Text(
          'Montant personnalisé',
          style: GoogleFonts.nunito(fontWeight: FontWeight.w900),
        ),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: TextInputType.number,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          decoration: const InputDecoration(suffixText: 'FCFA'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Annuler'),
          ),
          ElevatedButton(
            onPressed: () {
              final value = int.tryParse(controller.text) ?? 0;
              if (value > 0) {
                setState(() {
                  _selectedAmount = value;
                  _amountCtrl.text = '$value';
                });
              }
              Navigator.pop(context);
            },
            child: const Text('Valider'),
          ),
        ],
      ),
    );
  }

  void _next() {
    if (_phoneCtrl.text.length != 10) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Le numéro doit contenir 10 chiffres')),
      );
      return;
    }
    if (_selectedAmount <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Veuillez entrer un montant')),
      );
      return;
    }
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => Step4PaymentScreen(
          operatorId: widget.operatorId,
          serviceId: widget.serviceId,
          operator: widget.operator,
          service: widget.service,
          operation: widget.operation,
          phone: _phoneCtrl.text,
          amount: _selectedAmount,
          onTransactionAdded: widget.onTransactionAdded,
          onNotificationAdded: widget.onNotificationAdded,
          notifications: widget.notifications,
        ),
      ),
    );
  }
}
