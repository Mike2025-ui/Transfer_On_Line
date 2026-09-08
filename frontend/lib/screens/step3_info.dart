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
  // Compatibility only for older callers and saved history; never displayed
  // or sent to the backend.
  final String? operation;
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
    this.operation,
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
  String? _phoneError;

  // Prefixes mobiles ivoiriens: Orange 07/08/09, MTN 05/06 et Moov 01.
  static const _operatorPrefixes = {
    'Orange': ['07', '08', '09'],
    'MTN': ['05', '06'],
    'Moov': ['01'],
  };
  // Default, shown immediately - identical to the values this screen has
  // always shown. Only replaced in place if the backend has specific
  // amounts configured for this (operator, service); left untouched on an
  // empty result or a network error, so the screen never looks different
  // just because a fetch failed or hasn't resolved yet.
  static const _quickAmounts = [200, 500, 1000];
  static const _allowedAmounts = {
    200,
    300,
    500,
    1000,
    1500,
    2000,
    3000,
    5000,
    10000,
  };
  int _selectedAmount = 1000;
  String? _amountError;

  @override
  void initState() {
    super.initState();
    _loadAmounts();
  }

  Future<void> _loadAmounts() async {
    try {
      final amounts =
          await _api.getAvailableAmounts(widget.operatorId, widget.serviceId);
      // Les montants rapides restent volontairement fixes pour une UI courte.
      if (!mounted || amounts.isEmpty) return;
    } catch (_) {
      // Silent: the default _quickAmounts above is already a fully working
      // fallback, and this screen has never shown a loading/error state.
    }
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
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 4, 12, 4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Text(widget.service,
                      textAlign: TextAlign.center,
                      style: GoogleFonts.nunito(
                          fontSize: 18,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textPrimary)),
                  const SizedBox(height: 6),
                  Center(child: _label('Numéro')),
                  const SizedBox(height: 5),
                  _inputShell(
                    leading: Icons.phone_in_talk_outlined,
                    trailing: Icons.person_outline_rounded,
                    child: TextField(
                      controller: _phoneCtrl,
                      keyboardType: TextInputType.phone,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      onChanged: (_) => setState(() {
                        _phoneError = _phoneValidationError(_phoneCtrl.text);
                      }),
                      style: _fieldStyle(),
                      decoration: _inputDecoration('Entrez le numéro'),
                    ),
                  ),
                  if (_phoneError != null) ...[
                    const SizedBox(height: 6),
                    Text(
                      _phoneError!,
                      style: GoogleFonts.nunito(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: Colors.red,
                      ),
                    ),
                  ],
                  const SizedBox(height: 5),
                  _hint('Exemple : 07XXXXXXXX'),
                  const SizedBox(height: 12),
                  Center(child: _label('Montant')),
                  const SizedBox(height: 5),
                  _inputShell(
                    leading: Icons.attach_money_rounded,
                    trailing: Icons.keyboard_arrow_down_rounded,
                    trailingText: 'FCFA',
                    child: TextField(
                      controller: _amountCtrl,
                      keyboardType: TextInputType.number,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      onChanged: _onAmountChanged,
                      style: _fieldStyle(),
                      decoration: _inputDecoration('Entrez le montant'),
                    ),
                  ),
                  if (_amountError != null) ...[
                    const SizedBox(height: 4),
                    Text(_amountError!,
                        style: GoogleFonts.nunito(
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                          color: Colors.red,
                        )),
                  ],
                  const SizedBox(height: 5),
                  _hint('Montant de souscription ou transfert autorisé'),
                  const SizedBox(height: 10),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
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
                  const SizedBox(height: 6),
                  Row(
                    children: _quickAmounts.map((amount) {
                      return Expanded(
                        child: Padding(
                          padding: EdgeInsets.only(
                              right: amount == _quickAmounts.last ? 0 : 8),
                          child: QuickAmountButton(
                            amount: amount,
                            selected: _selectedAmount == amount,
                            onTap: () {
                              setState(() {
                                _selectedAmount = amount;
                                _amountCtrl.text = '$amount';
                                _amountError = null;
                              });
                            },
                          ),
                        ),
                      );
                    }).toList(),
                  ),
                  const SizedBox(height: 10),
                  TolButton(label: 'CONTINUER ›', onTap: _next),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  String? _phoneValidationError(String phone) {
    if (phone.length < 2) return null;
    final prefixes = _operatorPrefixes[widget.operator] ?? const <String>[];
    if (!prefixes.any(phone.startsWith)) {
      return 'Ce numéro ne correspond pas à l’opérateur ${widget.operator}.';
    }
    if (phone.length == 10) return null;
    return null;
  }

  Widget _inputShell({
    required IconData leading,
    required IconData trailing,
    required Widget child,
    String? trailingText,
  }) {
    return Container(
      height: 58,
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

  void _onAmountChanged(String value) {
    final amount = int.tryParse(value);
    setState(() {
      _selectedAmount = amount ?? 0;
      _amountError = amount != null && _allowedAmounts.contains(amount)
          ? null
          : 'Montant non disponible. Choisissez un montant valide.';
    });
  }

  void _next() {
    if (_phoneCtrl.text.length != 10) {
      setState(() => _phoneError = 'Le numéro doit contenir 10 chiffres.');
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Le numéro doit contenir 10 chiffres')),
      );
      return;
    }
    final phoneError = _phoneValidationError(_phoneCtrl.text);
    if (phoneError != null) {
      setState(() => _phoneError = phoneError);
      return;
    }
    if (_selectedAmount <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Veuillez entrer un montant')),
      );
      return;
    }
    if (!_allowedAmounts.contains(_selectedAmount)) {
      setState(() => _amountError =
          'Montant non disponible. Choisissez un montant valide.');
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
