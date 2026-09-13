import 'package:flutter_test/flutter_test.dart';
import 'package:transfer_on_line/models/models.dart';

void main() {
  group('Deep link payment callback parsing', () {
    test('parses valid transfertonline://payment URI with parameters', () {
      final uri = Uri.parse(
          'transfertonline://payment?reference=TOL-20260913-ABC12345&status=accepted');

      expect(uri.scheme, 'transfertonline');
      expect(uri.host, 'payment');
      expect(uri.queryParameters['reference'], 'TOL-20260913-ABC12345');
      expect(uri.queryParameters['status'], 'accepted');
    });

    test(
        'status mapping translates provider status to local transaction status',
        () {
      String mapStatus(String? rawStatus) {
        final status = rawStatus?.toLowerCase();
        return (status == 'accepted' || status == 'success' || status == 'ok')
            ? 'ok'
            : (status == 'cancelled' || status == 'canceled'
                ? 'cancelled'
                : (status == 'pending' ? 'pending' : 'fail'));
      }

      expect(mapStatus('accepted'), 'ok');
      expect(mapStatus('SUCCESS'), 'ok');
      expect(mapStatus('ok'), 'ok');
      expect(mapStatus('pending'), 'pending');
      expect(mapStatus('cancelled'), 'cancelled');
      expect(mapStatus('canceled'), 'cancelled');
      expect(mapStatus('failed'), 'fail');
      expect(mapStatus('error'), 'fail');
      expect(mapStatus(null), 'fail');
    });

    test('reconstructing transaction preserves fields with updated status', () {
      final existing = Transaction(
        id: 'TOL-123',
        operator: 'Orange',
        service: 'Internet',
        operation: 'Souscription',
        phone: '0700000001',
        amount: 1000,
        paymentMethod: 'Wave',
        date: DateTime(2026, 9, 13),
        status: 'pending',
      );

      final updated = Transaction(
        id: existing.id,
        operator: existing.operator,
        service: existing.service,
        operation: existing.operation,
        phone: existing.phone,
        amount: existing.amount,
        paymentMethod: existing.paymentMethod,
        date: existing.date,
        status: 'ok',
      );

      expect(updated.id, 'TOL-123');
      expect(updated.status, 'ok');
      expect(updated.statusLabel, 'Réussie');
    });
  });
}
