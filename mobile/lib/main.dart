import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'background/gateway_loop.dart';
import 'screens/onboarding_screen.dart';
import 'services/connectivity_monitor.dart';
import 'services/gateway_api.dart';
import 'services/local_queue_repository.dart';
import 'services/ussd_service.dart';

const _onboardingCompleteKey = 'onboarding_complete';

void main() {
  runApp(const GatewayApp());
}

class GatewayApp extends StatelessWidget {
  const GatewayApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Android Gateway',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
        useMaterial3: true,
      ),
      home: const GatewayHomePage(),
    );
  }
}

class GatewayHomePage extends StatefulWidget {
  const GatewayHomePage({super.key});

  @override
  State<GatewayHomePage> createState() => _GatewayHomePageState();
}

class _GatewayHomePageState extends State<GatewayHomePage> {
  final GatewayApi _api = GatewayApi();
  final UssdService _ussdService = UssdService();
  final LocalQueueRepository _queue = LocalQueueRepository();
  late final GatewayLoop _loop = GatewayLoop(
    api: _api,
    queue: _queue,
    dialUssd: _ussdService.sendUssdCode,
    // Fresh telemetry every tick, never the cached _deviceInfo used for the
    // status card's display - a heartbeat with launch-time-stale battery/
    // network readings would defeat the point of enriched telemetry.
    deviceInfoProvider: _ussdService.getDeviceInfo,
  );
  final ConnectivityMonitor _connectivityMonitor = ConnectivityMonitor();
  bool _isLoading = false;
  bool _serviceActive = false;
  String _message = 'Bienvenue sur le Gateway Android';
  GatewayStatus? _status;
  DeviceInfo? _deviceInfo;

  @override
  void initState() {
    super.initState();
    _loadDeviceInfo();
    _refreshStatus();
    _connectivityMonitor.start();
    _connectivityMonitor.onReconnected.listen((_) => _drainOnReconnect());
    // Post-frame: pushing a route requires the first frame (and this
    // widget's Navigator ancestor) to already be built.
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeShowOnboarding());
  }

  /// Shown once per install (see [_onboardingCompleteKey]) - this app is
  /// sideloaded onto dedicated Gateway phones with no MDM, so there is no
  /// other moment a human is guaranteed to be looking at the screen to
  /// grant what the autonomous loop needs (see OnboardingScreen's doc).
  Future<void> _maybeShowOnboarding() async {
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_onboardingCompleteKey) ?? false) return;
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (context) => const OnboardingScreen()),
    );
    await prefs.setBool(_onboardingCompleteKey, true);
  }

  @override
  void dispose() {
    _connectivityMonitor.dispose();
    _queue.close();
    super.dispose();
  }

  /// Triggered by [ConnectivityMonitor], not a button - deliberately does
  /// not touch `_isLoading`/show the loading spinner (a manual action, if
  /// one happens to be in flight at the same moment, keeps driving the UI)
  /// and swallows its own errors, since there is no user waiting on a
  /// result to report a failure to.
  Future<void> _drainOnReconnect() async {
    if (_isLoading) return;
    try {
      final result = await _loop.runOnce(gatewayId: _status?.id);
      if (!mounted) return;
      setState(() {
        _status = result.status;
        if (result.dialed > 0 || result.reported > 0) {
          _message = 'Reconnexion: ${result.dialed} composée(s), ${result.reported} rapportée(s).';
        }
      });
    } catch (_) {
      // Best-effort: the next heartbeat/manual action will retry.
    }
  }

  Future<void> _loadDeviceInfo() async {
    try {
      // Best-effort: a denial just means signalStrength/sims stay empty on
      // the resulting DeviceInfo, getDeviceInfo() below still succeeds.
      await _ussdService.requestTelemetryPermissions();
      final deviceInfo = await _ussdService.getDeviceInfo();
      setState(() => _deviceInfo = deviceInfo);
    } catch (error) {
      setState(() => _message = 'Impossible de charger le device: $error');
    }
  }

  Future<void> _refreshStatus() async {
    setState(() {
      _isLoading = true;
      _message = 'Chargement du statut...';
    });
    try {
      final status = await _api.fetchGatewayStatus();
      setState(() {
        _status = status;
        _message = 'Statut chargé.';
      });
    } catch (error) {
      setState(() => _message = 'Erreur de connexion: $error');
    } finally {
      setState(() => _isLoading = false);
    }
  }

  DeviceSnapshot? _deviceSnapshot() {
    final device = _deviceInfo;
    if (device == null) return null;
    return DeviceSnapshot(
      uuid: device.uuid,
      operatorName: device.operatorName,
      phoneNumber: device.phoneNumber,
      deviceModel: device.deviceModel,
      osVersion: device.osVersion,
      appVersion: device.appVersion,
      batteryLevel: device.batteryLevel,
      temperature: device.temperature,
      networkType: device.networkType,
      signalStrength: device.signalStrength,
      ipAddress: device.ipAddress,
      ramAvailableMb: device.ramAvailableMb,
      storageAvailableMb: device.storageAvailableMb,
      isBusy: device.isBusy,
      currentTaskCount: device.currentTaskCount,
      sims: device.sims,
    );
  }

  Future<void> _sendHeartbeat() async {
    final device = _deviceSnapshot();
    if (device == null) {
      _showSnack('Impossible: informations appareil indisponibles');
      return;
    }
    setState(() {
      _isLoading = true;
      _message = 'Envoi du heartbeat...';
    });
    try {
      final status = await _api.sendHeartbeat(_status?.id, device);
      setState(() {
        _status = status;
        _message = 'Heartbeat envoyé.';
      });
      _showSnack('Heartbeat réussi');
    } catch (error) {
      _showSnack('Échec du heartbeat: $error');
    } finally {
      setState(() => _isLoading = false);
    }
  }

  String _buildUssdCode(TransactionRequest request) {
    if (request.type.toLowerCase().contains('transfer') ||
        request.type.toLowerCase().contains('transfert')) {
      return '*123*${request.recipientPhone}*${request.amount.toInt()}#';
    }
    return '*456*${request.amount.toInt()}#';
  }

  Future<void> _processPendingTransactions() async {
    setState(() {
      _isLoading = true;
      _message = 'Recherche des transactions en attente...';
    });
    try {
      // GatewayLoop.runOnce() does heartbeat -> fetch -> enqueue -> dial ->
      // report as one unit - this is the exact same tick the autonomous
      // Foreground Service will run on a timer from Étape 3 onward, just
      // triggered once by hand here.
      final result = await _loop.runOnce(gatewayId: _status?.id);
      setState(() {
        _status = result.status;
        _message = result.pendingFetched == 0
            ? 'Aucune transaction en attente.'
            : '${result.dialed} composée(s), ${result.reported} rapportée(s) sur ${result.pendingFetched}.';
      });
      _showSnack('Traitement terminé');
    } catch (error) {
      _showSnack('Erreur traitement: $error');
    } finally {
      setState(() => _isLoading = false);
    }
  }

  /// Manual on/off for GatewayForegroundService. Kept alongside every
  /// existing button (never replaces them) - this is a convenience toggle
  /// for testing the autonomous loop, not a required step for the manual
  /// buttons above to keep working exactly as they did before Étape 3.
  Future<void> _toggleGatewayService() async {
    try {
      if (_serviceActive) {
        await _ussdService.stopGatewayService();
      } else {
        await _ussdService.startGatewayService();
      }
      setState(() => _serviceActive = !_serviceActive);
      _showSnack(
        _serviceActive
            ? 'Service arrière-plan démarré'
            : 'Service arrière-plan arrêté',
      );
    } catch (error) {
      _showSnack('Erreur service: $error');
    }
  }

  Future<void> _openUssdTestActivity() async {
    try {
      await _ussdService.openUssdTestActivity();
    } catch (error) {
      _showSnack('Erreur ouverture test USSD: $error');
    }
  }

  Future<void> _executeTransaction(String type) async {
    final request = await showDialog<TransactionRequest>(
      context: context,
      builder: (context) => TransactionDialog(type: type),
    );
    if (request == null) return;

    setState(() {
      _isLoading = true;
      _message = 'Exécution de $type...';
    });

    final code = _buildUssdCode(request);
    try {
      // No sim_slot/operator here - this is the manual "test transaction"
      // button, not a server-assigned task, so it dials on the default SIM
      // with no operator cross-check.
      final ussdResult = await _ussdService.sendUssdCode(code, null, null);
      final result = await _api.executeTransaction(
        request,
        ussdResponse: ussdResult,
      );
      setState(
        () => _message = 'Transaction envoyée: ${result['reference'] ?? 'OK'}',
      );
      _showSnack('USSD envoyé, réponse reçue');
    } catch (error) {
      _showSnack('Erreur transaction: $error');
    } finally {
      setState(() => _isLoading = false);
    }
  }

  void _showSnack(String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Widget _statusCard() {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Gateway Android',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text('UUID local: ${_deviceInfo?.uuid ?? 'non disponible'}'),
            Text(
              'Numéro local: ${_deviceInfo?.phoneNumber ?? 'non disponible'}',
            ),
            Text(
              'Opérateur local: ${_deviceInfo?.operatorName ?? 'non disponible'}',
            ),
            Text(
              'Batterie: ${_deviceInfo?.batteryLevel != null ? '${_deviceInfo!.batteryLevel}%' : 'non disponible'}'
              ' • Réseau: ${_deviceInfo?.networkType ?? 'non disponible'}',
            ),
            Text('SIM détectées: ${_deviceInfo?.sims.length ?? 0}'),
            const SizedBox(height: 12),
            Text('Statut backend: ${_status?.heartbeatStatus ?? 'non chargé'}'),
            Text('Backend UUID: ${_status?.uuid ?? 'non chargé'}'),
            Text('Backend numéro: ${_status?.phoneNumber ?? 'non chargé'}'),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Gateway Android'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _refreshStatus,
            tooltip: 'Rafraîchir',
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _statusCard(),
              ElevatedButton.icon(
                icon: Icon(
                  _serviceActive ? Icons.stop_circle : Icons.play_circle,
                ),
                label: Text(
                  _serviceActive
                      ? 'Service arrière-plan : Actif (arrêter)'
                      : 'Service arrière-plan : Inactif (démarrer)',
                ),
                style: _serviceActive
                    ? ElevatedButton.styleFrom(
                        backgroundColor: Colors.green.shade100,
                      )
                    : null,
                onPressed: _toggleGatewayService,
              ),
              const SizedBox(height: 12),
              ElevatedButton.icon(
                icon: const Icon(Icons.monitor_heart),
                label: const Text('Envoyer heartbeat'),
                onPressed: _isLoading ? null : _sendHeartbeat,
              ),
              const SizedBox(height: 12),
              ElevatedButton.icon(
                icon: const Icon(Icons.sync),
                label: const Text('Traiter transactions en attente'),
                onPressed: _isLoading ? null : _processPendingTransactions,
              ),
              const SizedBox(height: 12),
              ElevatedButton.icon(
                icon: const Icon(Icons.send),
                label: const Text('Test transfert de crédit'),
                onPressed: _isLoading
                    ? null
                    : () => _executeTransaction('transfer'),
              ),
              const SizedBox(height: 12),
              ElevatedButton.icon(
                icon: const Icon(Icons.wifi),
                label: const Text('Test souscription'),
                onPressed: _isLoading
                    ? null
                    : () => _executeTransaction('subscription'),
              ),
              const SizedBox(height: 12),
              ElevatedButton.icon(
                icon: const Icon(Icons.accessibility_new),
                label: const Text('TEST ACCESSIBILITY USSD'),
                onPressed: _openUssdTestActivity,
              ),
              const SizedBox(height: 16),
              if (_isLoading) const LinearProgressIndicator(),
              const SizedBox(height: 10),
              Text(_message, style: Theme.of(context).textTheme.bodyLarge),
            ],
          ),
        ),
      ),
    );
  }
}

class TransactionDialog extends StatefulWidget {
  const TransactionDialog({super.key, required this.type});
  final String type;

  @override
  State<TransactionDialog> createState() => _TransactionDialogState();
}

class _TransactionDialogState extends State<TransactionDialog> {
  final _formKey = GlobalKey<FormState>();
  final _phoneController = TextEditingController();
  final _amountController = TextEditingController();

  @override
  void dispose() {
    _phoneController.dispose();
    _amountController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(
        widget.type == 'transfer' ? 'Transfert crédit' : 'Souscription',
      ),
      content: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextFormField(
              controller: _phoneController,
              decoration: const InputDecoration(
                labelText: 'Numéro destinataire',
              ),
              keyboardType: TextInputType.phone,
              validator: (value) =>
                  value == null || value.isEmpty ? 'Numéro requis' : null,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _amountController,
              decoration: const InputDecoration(labelText: 'Montant'),
              keyboardType: TextInputType.number,
              validator: (value) =>
                  value == null || value.isEmpty ? 'Montant requis' : null,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Annuler'),
        ),
        ElevatedButton(
          onPressed: () {
            if (_formKey.currentState?.validate() ?? false) {
              Navigator.of(context).pop(
                TransactionRequest(
                  type: widget.type,
                  recipientPhone: _phoneController.text.trim(),
                  amount: double.tryParse(_amountController.text.trim()) ?? 0,
                ),
              );
            }
          },
          child: const Text('Envoyer'),
        ),
      ],
    );
  }
}
