import 'dart:async';

/// Local-only lock policy: the app re-checks the device lock after a short idle
/// window, and we never rely on a server session for user authentication.
class LocalDeviceLockController {
  LocalDeviceLockController({Duration? window})
      : _lockWindow = window ?? const Duration(seconds: 10);

  final Duration _lockWindow;
  DateTime? _lastUnlockedAt;
  Timer? _debounceTimer;

  void markUnlocked({DateTime? at}) {
    _lastUnlockedAt = at ?? DateTime.now();
    _debounceTimer?.cancel();
  }

  bool shouldRequireUnlock({DateTime? now}) {
    final reference = now ?? DateTime.now();
    if (_lastUnlockedAt == null) return true;
    return reference.difference(_lastUnlockedAt!) > _lockWindow;
  }

  void dispose() {
    _debounceTimer?.cancel();
  }
}

class LocalDeviceLockService {
  LocalDeviceLockService({Duration? window})
      : _controller = LocalDeviceLockController(window: window ?? const Duration(seconds: 10));

  final LocalDeviceLockController _controller;

  Future<bool> shouldRequireUnlock() async {
    return _controller.shouldRequireUnlock();
  }

  void markUnlocked() {
    _controller.markUnlocked();
  }

  void dispose() {
    _controller.dispose();
  }
}
