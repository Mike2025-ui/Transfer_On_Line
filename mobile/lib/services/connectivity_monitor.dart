import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';

/// Edge-triggered reconnect detection: [onReconnected] fires only on the
/// transition into "has connectivity", never on every connectivity event
/// (so a flapping connection doesn't trigger a drain per flap, and a
/// connectivity event while already online doesn't trigger anything at
/// all). A stale telemetry snapshot has no value after a reconnect, so
/// callers should react by running a fresh [GatewayLoop] tick, not by
/// replaying anything queued for the heartbeat itself (there is nothing to
/// replay - see GatewayLoop's class doc).
class ConnectivityMonitor {
  ConnectivityMonitor({Connectivity? connectivity})
    : _connectivity = connectivity ?? Connectivity();

  final Connectivity _connectivity;
  StreamSubscription<List<ConnectivityResult>>? _subscription;
  final _controller = StreamController<void>.broadcast();

  // Optimistic default: if the very first event we observe already shows a
  // connection, that must not itself count as a "reconnect" (there was
  // nothing to reconnect from).
  bool _wasConnected = true;

  Stream<void> get onReconnected => _controller.stream;

  void start() {
    _subscription ??= _connectivity.onConnectivityChanged.listen((results) {
      final isConnected = results.any((r) => r != ConnectivityResult.none);
      if (isConnected && !_wasConnected) {
        _controller.add(null);
      }
      _wasConnected = isConnected;
    });
  }

  Future<void> dispose() async {
    await _subscription?.cancel();
    _subscription = null;
    await _controller.close();
  }
}
