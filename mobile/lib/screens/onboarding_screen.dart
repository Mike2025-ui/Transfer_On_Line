import 'package:flutter/material.dart';

import '../services/ussd_service.dart';

/// Best-effort, non-exhaustive: link/setting names shift between OEM
/// firmware versions, so this stays a pointer for the person on-site to
/// find the right screen themselves, not a guaranteed-accurate deep link.
const Map<String, String> _oemAutostartHints = {
  'xiaomi': 'Paramètres > Applications > Autoriser le démarrage automatique > Transfer On Line Gateway.',
  'redmi': 'Paramètres > Applications > Autoriser le démarrage automatique > Transfer On Line Gateway.',
  'oppo': 'Paramètres > Batterie > Démarrage automatique de l\'application > activer.',
  'realme': 'Paramètres > Batterie > Démarrage automatique de l\'application > activer.',
  'vivo': 'Paramètres > Batterie > Gestion de démarrage élevé > activer pour cette app.',
  'huawei': 'Paramètres > Batterie > Lancement des applications > gérer manuellement > tout activer.',
  'honor': 'Paramètres > Batterie > Lancement des applications > gérer manuellement > tout activer.',
  'samsung': 'Paramètres > Batterie > Applications non surveillées > retirer cette app de la liste.',
};

/// Shown once per phone (see `main.dart`'s first-launch check) - walks the
/// person installing a Gateway phone through everything the autonomous
/// loop needs that cannot be granted silently, since these phones are
/// sideloaded with no MDM (see the Phase C plan). Every step is idempotent
/// and safe to revisit from the manual toggle later - this screen does not
/// gate the rest of the app, it just front-loads the friction to a single
/// guided pass instead of leaving it to be discovered piecemeal.
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _ussdService = UssdService();

  bool _telemetryGranted = false;
  bool _callGranted = false;
  bool _notificationsGranted = false;
  bool _batteryExempted = false;
  String? _manufacturer;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _refreshState();
  }

  Future<void> _refreshState() async {
    setState(() => _loading = true);
    final battery = await _ussdService.isIgnoringBatteryOptimizations();
    DeviceInfo? info;
    try {
      info = await _ussdService.getDeviceInfo();
    } catch (_) {
      // Permissions not granted yet - fine, the checklist below is exactly
      // what asks for them.
    }
    if (!mounted) return;
    setState(() {
      _batteryExempted = battery;
      _manufacturer = info?.manufacturer;
      _loading = false;
    });
  }

  Future<void> _requestTelemetry() async {
    final granted = await _ussdService.requestTelemetryPermissions();
    if (!mounted) return;
    setState(() => _telemetryGranted = granted);
  }

  Future<void> _requestCall() async {
    final granted = await _ussdService.requestCallPermission();
    if (!mounted) return;
    setState(() => _callGranted = granted);
  }

  /// Stabilisation RC1 (priorité haute n°3): without this granted upfront,
  /// GatewayForegroundService's persistent notification can silently never
  /// appear on Android 13+ even though the service keeps running fine.
  Future<void> _requestNotifications() async {
    final granted = await _ussdService.requestNotificationPermission();
    if (!mounted) return;
    setState(() => _notificationsGranted = granted);
  }

  Future<void> _requestBattery() async {
    await _ussdService.requestBatteryOptimizationExemption();
    // The system dialog is async and outside our control - re-check on
    // return rather than assuming the outcome.
    await Future.delayed(const Duration(milliseconds: 500));
    await _refreshState();
  }

  String? _autostartHint() {
    final manufacturer = _manufacturer?.toLowerCase();
    if (manufacturer == null) return null;
    for (final entry in _oemAutostartHints.entries) {
      if (manufacturer.contains(entry.key)) return entry.value;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final hint = _autostartHint();
    return Scaffold(
      appBar: AppBar(title: const Text('Configuration du Gateway')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    'Ce téléphone va fonctionner comme un serveur Gateway '
                    '24h/24. Les étapes ci-dessous ne sont à faire qu\'une '
                    'seule fois par téléphone.',
                  ),
                  const SizedBox(height: 20),
                  _ChecklistTile(
                    title: 'Informations téléphonie et SIM',
                    subtitle: 'Nécessaire pour le heartbeat (batterie, réseau, liste des SIM).',
                    done: _telemetryGranted,
                    onPressed: _requestTelemetry,
                  ),
                  _ChecklistTile(
                    title: 'Autorisation d\'appel (USSD)',
                    subtitle: 'Nécessaire pour composer les codes USSD automatiquement.',
                    done: _callGranted,
                    onPressed: _requestCall,
                  ),
                  _ChecklistTile(
                    title: 'Notifications',
                    subtitle: 'Nécessaire (Android 13+) pour afficher la notification persistante du service.',
                    done: _notificationsGranted,
                    onPressed: _requestNotifications,
                  ),
                  _ChecklistTile(
                    title: 'Exemption d\'optimisation de batterie',
                    subtitle: 'Empêche Android d\'arrêter le service en arrière-plan.',
                    done: _batteryExempted,
                    onPressed: _requestBattery,
                  ),
                  const SizedBox(height: 20),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Réglage constructeur (${_manufacturer ?? 'inconnu'})',
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          const SizedBox(height: 8),
                          Text(
                            hint ??
                                'Certains constructeurs (Xiaomi, Oppo, Vivo, '
                                    'Huawei...) tuent les applications en '
                                    'arrière-plan malgré l\'exemption ci-dessus. '
                                    'Vérifiez les paramètres de "démarrage '
                                    'automatique" ou "gestion de la batterie" '
                                    'spécifiques à ce téléphone.',
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('Terminé'),
                  ),
                ],
              ),
            ),
    );
  }
}

class _ChecklistTile extends StatelessWidget {
  const _ChecklistTile({
    required this.title,
    required this.subtitle,
    required this.done,
    required this.onPressed,
  });

  final String title;
  final String subtitle;
  final bool done;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: Icon(
          done ? Icons.check_circle : Icons.radio_button_unchecked,
          color: done ? Colors.green : null,
        ),
        title: Text(title),
        subtitle: Text(subtitle),
        trailing: done
            ? null
            : TextButton(onPressed: onPressed, child: const Text('Autoriser')),
      ),
    );
  }
}
