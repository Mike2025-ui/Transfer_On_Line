import 'package:flutter/material.dart';

import 'services/gateway_api.dart';
import 'services/ussd_service.dart';

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
  bool _isLoading = false;
  String _message = 'Bienvenue sur le Gateway Android';
  GatewayStatus? _status;
  DeviceInfo? _deviceInfo;

  @override
  void initState() {
    super.initState();
    _loadDeviceInfo();
    _refreshStatus();
  }

  Future<void> _loadDeviceInfo() async {
    try {
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
    final device = _deviceSnapshot();
    if (device == null) {
      _showSnack('Impossible: informations appareil indisponibles');
      return;
    }
    setState(() {
      _isLoading = true;
      _message = 'Recherche des transactions en attente...';
    });
    try {
      final status = await _api.sendHeartbeat(_status?.id, device);
      final transactions = await _api.fetchPendingTransactions(status.uuid);
      if (transactions.isEmpty) {
        setState(() {
          _status = status;
          _message = 'Aucune transaction en attente.';
        });
        return;
      }

      var successCount = 0;
      for (final transaction in transactions) {
        final request = transaction.toTransactionRequest(
          gatewayUuid: status.uuid,
        );
        final code = transaction.ussdCode ?? _buildUssdCode(request);
        try {
          final ussdResult = await _ussdService.sendUssdCode(code);
          await _api.reportTransactionResult(
            reference: transaction.serverReference,
            success: true,
            result: ussdResult,
          );
          successCount++;
        } catch (error) {
          await _api.reportTransactionResult(
            reference: transaction.serverReference,
            success: false,
            result: error.toString(),
          );
        }
      }
      setState(() {
        _status = status;
        _message =
            '$successCount/${transactions.length} transaction(s) traitée(s).';
      });
      _showSnack('Traitement terminé');
    } catch (error) {
      _showSnack('Erreur traitement: $error');
    } finally {
      setState(() => _isLoading = false);
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
      final ussdResult = await _ussdService.sendUssdCode(code);
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
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _statusCard(),
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
