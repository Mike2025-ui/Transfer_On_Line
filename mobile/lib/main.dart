import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'background/gateway_loop.dart';
import 'screens/onboarding_screen.dart';
import 'services/connectivity_monitor.dart';
import 'services/gateway_api.dart';
import 'services/local_queue_repository.dart';
import 'services/ussd_service.dart';

const _onboardingCompleteKey = 'onboarding_complete';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await GatewayApi.initPreferences();
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

class _GatewayHomePageState extends State<GatewayHomePage>
    with WidgetsBindingObserver {
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
  String _configuredUrl = GatewayApi.baseUrl;
  bool _hasConfiguredSecret = false;
  bool _isAccessibilityEnabled = false;
  bool _isOverlayEnabled = false;
  bool _hasSim0DistributorCode = false;
  bool _hasSim1DistributorCode = false;
  Map<String, dynamic> _cachedScenarioVersions = {};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadConfig();
    _loadDeviceInfo();
    _refreshStatus();
    _checkAccessibility();
    _loadDistributorCodeStatus();
    _connectivityMonitor.start();
    _connectivityMonitor.onReconnected.listen((_) => _drainOnReconnect());
    // Post-frame: pushing a route requires the first frame (and this
    // widget's Navigator ancestor) to already be built.
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeShowOnboarding());
  }

  Future<void> _checkAccessibility() async {
    try {
      final accessEnabled = await _ussdService.isUssdAccessibilityEnabled();
      final overlayEnabled = await _ussdService.isOverlayPermissionGranted();
      if (!mounted) return;
      setState(() {
        _isAccessibilityEnabled = accessEnabled;
        _isOverlayEnabled = overlayEnabled;
      });
    } catch (_) {}
  }

  Future<void> _loadConfig() async {
    final url = await GatewayApi.getConfiguredBaseUrl();
    final secret = await GatewayApi.getConfiguredSecret();
    if (!mounted) return;
    setState(() {
      _configuredUrl = url;
      _hasConfiguredSecret = secret.trim().isNotEmpty;
    });
  }

  /// Shown once per install (see [_onboardingCompleteKey]) - this app is
  /// sideloaded onto dedicated Gateway phones with no MDM, so there is no
  /// other moment a human is guaranteed to be looking at the screen to
  /// grant what the autonomous loop needs (see OnboardingScreen's doc).
  Future<void> _maybeShowOnboarding() async {
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_onboardingCompleteKey) ?? false) return;
    if (!mounted) return;
    await Navigator.of(
      context,
    ).push(MaterialPageRoute(builder: (context) => const OnboardingScreen()));
    await prefs.setBool(_onboardingCompleteKey, true);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _connectivityMonitor.dispose();
    _queue.close();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _checkAccessibility();
      _refreshStatus();
    }
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
          _message =
              'Reconnexion: ${result.dialed} composée(s), ${result.reported} rapportée(s).';
        }
      });
    } catch (_) {
      // Best-effort: the next heartbeat/manual action will retry.
    }
  }

  Future<DeviceInfo?> _loadDeviceInfo() async {
    try {
      // Best-effort: a denial just means signalStrength/sims stay empty on
      // the resulting DeviceInfo, getDeviceInfo() below still succeeds.
      await _ussdService.requestTelemetryPermissions();
      final deviceInfo = await _ussdService.getDeviceInfo();
      if (mounted) {
        setState(() => _deviceInfo = deviceInfo);
      }
      return deviceInfo;
    } catch (error) {
      if (mounted) {
        setState(() => _message = 'Impossible de charger le device: $error');
      }
      return null;
    }
  }

  Future<void> _refreshStatus() async {
    setState(() {
      _isLoading = true;
      _message = 'Chargement du statut...';
    });
    try {
      final freshDevice = await _loadDeviceInfo();
      final status = await _api.fetchGatewayStatus(
        deviceUuid: freshDevice?.uuid ?? _deviceInfo?.uuid,
      );
      if (mounted) {
        setState(() {
          _status = status;
          _message = 'Statut chargé.';
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() => _message = 'Erreur de connexion: $error');
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
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
    setState(() {
      _isLoading = true;
      _message = 'Envoi du heartbeat...';
    });
    try {
      await _loadDeviceInfo();
      final device = _deviceSnapshot();
      if (device == null) {
        _showSnack('Impossible: informations appareil indisponibles');
        return;
      }
      final status = await _api.sendHeartbeat(_status?.id, device);
      if (mounted) {
        setState(() {
          _status = status;
          _message = 'Heartbeat envoyé.';
        });
      }
      _showSnack('Heartbeat réussi');
    } catch (error) {
      _showSnack('Échec du heartbeat: $error');
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
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

  void _showSnack(String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _loadDistributorCodeStatus() async {
    try {
      final sim0 = await _ussdService.hasDistributorCode(0);
      final sim1 = await _ussdService.hasDistributorCode(1);
      final scenarios = await _ussdService.getCachedScenarioVersions();
      if (!mounted) return;
      setState(() {
        _hasSim0DistributorCode = sim0;
        _hasSim1DistributorCode = sim1;
        _cachedScenarioVersions = scenarios;
      });
    } catch (_) {}
  }

  Future<void> _syncScenarios() async {
    setState(() => _isLoading = true);
    try {
      final rawJson = await _api.fetchScenariosRaw();
      final count = await _ussdService.syncScenarios(rawJson);
      await _loadDistributorCodeStatus();
      _showSnack('Synchronisation réussie : $count scénario(s) mis à jour');
    } catch (e) {
      _showSnack('Erreur synchronisation scénarios : $e');
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _openDistributorCodeDialog(int slot) async {
    final codeController = TextEditingController();
    bool obscure = true;
    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlgState) => AlertDialog(
          title: Row(
            children: [
              const Icon(Icons.shield_outlined, color: Colors.indigo),
              const SizedBox(width: 8),
              Text('Code Distributeur — SIM ${slot + 1}'),
            ],
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Ce secret est chiffré dans l\'Android KeyStore matériel (AES-256 GCM). '
                'Il n\'est JAMAIS transmis au serveur ni exposé dans les logs.',
                style: TextStyle(fontSize: 12, color: Colors.black87),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: codeController,
                obscureText: obscure,
                keyboardType: TextInputType.number,
                decoration: InputDecoration(
                  labelText: 'Code Distributeur SIM ${slot + 1}',
                  hintText: 'Saisir le code secret',
                  border: const OutlineInputBorder(),
                  prefixIcon: const Icon(Icons.password),
                  suffixIcon: IconButton(
                    icon: Icon(
                      obscure ? Icons.visibility : Icons.visibility_off,
                    ),
                    onPressed: () => setDlgState(() => obscure = !obscure),
                  ),
                ),
              ),
            ],
          ),
          actions: [
            if (slot == 0 ? _hasSim0DistributorCode : _hasSim1DistributorCode)
              TextButton(
                style: TextButton.styleFrom(foregroundColor: Colors.red),
                child: const Text('Effacer'),
                onPressed: () async {
                  await _ussdService.clearDistributorCode(slot);
                  await _loadDistributorCodeStatus();
                  if (ctx.mounted) Navigator.pop(ctx);
                  _showSnack('Code distributeur SIM ${slot + 1} effacé');
                },
              ),
            TextButton(
              child: const Text('Annuler'),
              onPressed: () => Navigator.pop(ctx),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.indigo,
                foregroundColor: Colors.white,
              ),
              child: const Text('Enregistrer'),
              onPressed: () async {
                final code = codeController.text.trim();
                if (code.isNotEmpty) {
                  await _ussdService.saveDistributorCode(slot, code);
                  await _loadDistributorCodeStatus();
                  if (ctx.mounted) Navigator.pop(ctx);
                  _showSnack(
                    'Code distributeur SIM ${slot + 1} chiffré dans KeyStore',
                  );
                }
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _distributorCodeCard() {
    return Card(
      elevation: 2,
      margin: const EdgeInsets.only(bottom: 16),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: Colors.blueGrey.shade200),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.security, color: Colors.indigo),
                const SizedBox(width: 8),
                const Text(
                  'Sécurité Edge & Codes Distributeur',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                ),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.sync, color: Colors.indigo),
                  tooltip: 'Synchroniser scénarios',
                  onPressed: _isLoading ? null : _syncScenarios,
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Scénarios en cache : ${_cachedScenarioVersions.length} actif(s)',
              style: const TextStyle(fontSize: 12, color: Colors.black54),
            ),
            const Divider(height: 20),
            _simCodeRow(slot: 0, isConfigured: _hasSim0DistributorCode),
            const SizedBox(height: 10),
            _simCodeRow(slot: 1, isConfigured: _hasSim1DistributorCode),
          ],
        ),
      ),
    );
  }

  Widget _simCodeRow({required int slot, required bool isConfigured}) {
    return Row(
      children: [
        Icon(
          isConfigured ? Icons.lock : Icons.lock_open,
          color: isConfigured ? Colors.green : Colors.orange,
          size: 20,
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'SIM ${slot + 1} — Code Distributeur',
                style: const TextStyle(
                  fontWeight: FontWeight.w600,
                  fontSize: 13,
                ),
              ),
              Text(
                isConfigured
                    ? 'Chiffré dans Android KeyStore'
                    : 'Non configuré (requis pour AGENT_AUTH)',
                style: TextStyle(
                  fontSize: 11,
                  color: isConfigured
                      ? Colors.green.shade800
                      : Colors.orange.shade900,
                ),
              ),
            ],
          ),
        ),
        OutlinedButton(
          style: OutlinedButton.styleFrom(
            visualDensity: VisualDensity.compact,
            padding: const EdgeInsets.symmetric(horizontal: 12),
          ),
          onPressed: () => _openDistributorCodeDialog(slot),
          child: Text(isConfigured ? 'Modifier' : 'Configurer'),
        ),
      ],
    );
  }

  Future<void> _openSettingsDialog() async {
    final currentUrl = await GatewayApi.getConfiguredBaseUrl();
    final currentSecret = await GatewayApi.getConfiguredSecret();
    if (!mounted) return;

    final urlController = TextEditingController(text: currentUrl);
    final secretController = TextEditingController(text: currentSecret);
    bool obscureSecret = true;
    bool isTesting = false;
    String? testMessage;
    bool? testSuccess;

    await showDialog(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) {
          return AlertDialog(
            title: const Row(
              children: [
                Icon(Icons.settings_cell, color: Colors.indigo),
                SizedBox(width: 8),
                Text('Configuration Serveur'),
              ],
            ),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    'Configurez l\'adresse du serveur et le secret généré par python manage.py setup_gateway :',
                    style: TextStyle(fontSize: 13, color: Colors.black87),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: urlController,
                    decoration: const InputDecoration(
                      labelText: 'URL API Backend',
                      hintText: 'https://transfert-online.site/api',
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.link),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: secretController,
                    obscureText: obscureSecret,
                    decoration: InputDecoration(
                      labelText: 'X-Gateway-Secret',
                      hintText: 'Secret généré (SHA-256)',
                      border: const OutlineInputBorder(),
                      prefixIcon: const Icon(Icons.key),
                      suffixIcon: IconButton(
                        icon: Icon(
                          obscureSecret
                              ? Icons.visibility
                              : Icons.visibility_off,
                        ),
                        onPressed: () => setDialogState(
                          () => obscureSecret = !obscureSecret,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  ElevatedButton.icon(
                    icon: isTesting
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.wifi_protected_setup),
                    label: Text(
                      isTesting ? 'Vérification...' : 'Tester la connexion',
                    ),
                    onPressed: isTesting
                        ? null
                        : () async {
                            setDialogState(() {
                              isTesting = true;
                              testMessage = null;
                              testSuccess = null;
                            });
                            final res = await _api.testConnection(
                              baseUrl: urlController.text,
                              secret: secretController.text,
                            );
                            if (dialogContext.mounted) {
                              setDialogState(() {
                                isTesting = false;
                                testSuccess = res['success'] as bool? ?? false;
                                testMessage = res['message'] as String? ?? '';
                              });
                            }
                          },
                  ),
                  if (testMessage != null) ...[
                    const SizedBox(height: 10),
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: (testSuccess ?? false)
                            ? Colors.green.shade50
                            : Colors.red.shade50,
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(
                          color: (testSuccess ?? false)
                              ? Colors.green
                              : Colors.red,
                        ),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            (testSuccess ?? false)
                                ? Icons.check_circle
                                : Icons.error_outline,
                            size: 18,
                            color: (testSuccess ?? false)
                                ? Colors.green
                                : Colors.red,
                          ),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              testMessage!,
                              style: TextStyle(
                                fontSize: 12,
                                color: (testSuccess ?? false)
                                    ? Colors.green.shade900
                                    : Colors.red.shade900,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
            actions: [
              TextButton(
                child: const Text('Fermer'),
                onPressed: () => Navigator.of(dialogContext).pop(),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.indigo,
                  foregroundColor: Colors.white,
                ),
                child: const Text('Enregistrer'),
                onPressed: () async {
                  await GatewayApi.saveSettings(
                    baseUrl: urlController.text,
                    secret: secretController.text,
                  );
                  await _loadConfig();
                  if (dialogContext.mounted) {
                    Navigator.of(dialogContext).pop();
                  }
                  _showSnack('Configuration enregistrée');
                  _refreshStatus();
                },
              ),
            ],
          );
        },
      ),
    );
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
            const Divider(),
            const SizedBox(height: 4),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Serveur: $_configuredUrl',
                        style: const TextStyle(
                          fontSize: 12,
                          color: Colors.black87,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Icon(
                            _hasConfiguredSecret
                                ? Icons.check_circle
                                : Icons.warning_amber_rounded,
                            size: 16,
                            color: _hasConfiguredSecret
                                ? Colors.green
                                : Colors.orange,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            _hasConfiguredSecret
                                ? 'Secret Gateway configuré'
                                : 'Secret Gateway manquant',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: _hasConfiguredSecret
                                  ? Colors.green.shade800
                                  : Colors.orange.shade900,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.settings, color: Colors.indigo),
                  tooltip: 'Paramètres Serveur',
                  onPressed: _openSettingsDialog,
                ),
              ],
            ),
            const SizedBox(height: 8),
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
            icon: const Icon(Icons.settings),
            onPressed: _openSettingsDialog,
            tooltip: 'Configuration Serveur',
          ),
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
              _distributorCodeCard(),
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
              const SizedBox(height: 16),
              Card(
                elevation: 2,
                color: Colors.indigo.shade50,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                  side: BorderSide(color: Colors.indigo.shade200),
                ),
                child: InkWell(
                  onTap: () async {
                    await _openUssdTestActivity();
                    _checkAccessibility();
                  },
                  borderRadius: BorderRadius.circular(12),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      vertical: 14,
                      horizontal: 16,
                    ),
                    child: Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: Colors.indigo.shade700,
                            shape: BoxShape.circle,
                          ),
                          child: const Icon(
                            Icons.terminal,
                            color: Colors.white,
                            size: 24,
                          ),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text(
                                "Console d'Exécution USSD — En direct",
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 14,
                                  color: Color(0xFF0F172A),
                                ),
                              ),
                              const SizedBox(height: 4),
                              Wrap(
                                spacing: 12,
                                runSpacing: 4,
                                children: [
                                  Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(
                                        _isAccessibilityEnabled
                                            ? Icons.check_circle
                                            : Icons.warning_amber_rounded,
                                        size: 13,
                                        color: _isAccessibilityEnabled
                                            ? Colors.green.shade700
                                            : Colors.amber.shade900,
                                      ),
                                      const SizedBox(width: 4),
                                      Text(
                                        _isAccessibilityEnabled
                                            ? "Accessibilité : Activée"
                                            : "Accessibilité : Requise",
                                        style: TextStyle(
                                          fontSize: 11,
                                          fontWeight: FontWeight.w600,
                                          color: _isAccessibilityEnabled
                                              ? Colors.green.shade800
                                              : Colors.amber.shade900,
                                        ),
                                      ),
                                    ],
                                  ),
                                  Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(
                                        _isOverlayEnabled
                                            ? Icons.check_circle
                                            : Icons.warning_amber_rounded,
                                        size: 13,
                                        color: _isOverlayEnabled
                                            ? Colors.green.shade700
                                            : Colors.amber.shade900,
                                      ),
                                      const SizedBox(width: 4),
                                      Text(
                                        _isOverlayEnabled
                                            ? "Superposition : Activée"
                                            : "Superposition : Requise",
                                        style: TextStyle(
                                          fontSize: 11,
                                          fontWeight: FontWeight.w600,
                                          color: _isOverlayEnabled
                                              ? Colors.green.shade800
                                              : Colors.amber.shade900,
                                        ),
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                        const Icon(
                          Icons.arrow_forward_ios,
                          size: 16,
                          color: Colors.indigo,
                        ),
                      ],
                    ),
                  ),
                ),
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
