import 'package:flutter_test/flutter_test.dart';
import 'package:transfer_on_line/services/local_device_lock.dart';

void main() {
  group('LocalDeviceLockController', () {
    test('requires unlock when no unlock has happened yet', () {
      final controller = LocalDeviceLockController();
      expect(controller.shouldRequireUnlock(), isTrue);
    });

    test('does not require unlock immediately after a successful local unlock', () {
      final controller = LocalDeviceLockController();
      controller.markUnlocked();
      expect(controller.shouldRequireUnlock(), isFalse);
    });

    test('requires unlock again after 10 seconds', () {
      final controller = LocalDeviceLockController();
      controller.markUnlocked(at: DateTime.now().subtract(const Duration(seconds: 11)));
      expect(controller.shouldRequireUnlock(now: DateTime.now()), isTrue);
    });

    test('keeps the app unlocked inside the 10 second window', () {
      final controller = LocalDeviceLockController();
      final now = DateTime.now();
      controller.markUnlocked(at: now.subtract(const Duration(seconds: 9)));
      expect(controller.shouldRequireUnlock(now: now), isFalse);
    });
  });
}
