import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:transfer_on_line/models/models.dart';
import 'package:transfer_on_line/services/transaction_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('save then load round-trips a transaction unchanged', () async {
    final tx = Transaction(
      id: 'TOL-1',
      operator: 'Orange',
      service: 'Internet',
      operation: 'Souscription pour moi',
      phone: '0700000001',
      amount: 1000,
      paymentMethod: 'CinetPay',
      date: DateTime(2026, 1, 1, 10, 30),
      status: 'ok',
    );

    await TransactionService.save([tx]);
    final loaded = await TransactionService.load();

    expect(loaded, hasLength(1));
    expect(loaded.single.id, 'TOL-1');
    expect(loaded.single.status, 'ok');
    expect(loaded.single.date, DateTime(2026, 1, 1, 10, 30));
  });

  test('an empty store loads as an empty list, not an error', () async {
    expect(await TransactionService.load(), isEmpty);
  });

  test('addTransaction inserts at the head and persists', () async {
    final first = Transaction(
      id: 'TOL-1', operator: 'Orange', service: 'Internet', operation: 'Souscription pour moi',
      phone: '0700000001', amount: 1000, paymentMethod: 'CinetPay', date: DateTime(2026, 1, 1), status: 'ok',
    );
    final second = Transaction(
      id: 'TOL-2', operator: 'MTN', service: 'Appels', operation: 'Souscription pour moi',
      phone: '0700000002', amount: 500, paymentMethod: 'CinetPay', date: DateTime(2026, 1, 2), status: 'pending',
    );

    var current = await TransactionService.addTransaction([], first);
    current = await TransactionService.addTransaction(current, second);

    expect(current.map((t) => t.id), ['TOL-2', 'TOL-1']);
    final reloaded = await TransactionService.load();
    expect(reloaded.map((t) => t.id), ['TOL-2', 'TOL-1']);
  });

  test('clear removes every stored transaction', () async {
    await TransactionService.save([
      Transaction(
        id: 'TOL-1', operator: 'Orange', service: 'Internet', operation: 'Souscription pour moi',
        phone: '0700000001', amount: 1000, paymentMethod: 'CinetPay', date: DateTime(2026, 1, 1), status: 'ok',
      ),
    ]);

    await TransactionService.clear();

    expect(await TransactionService.load(), isEmpty);
  });

  // Audit frontend D4, §20 : le modèle Transaction n'a pas été modifié pour
  // D4, mais un enregistrement écrit par une version antérieure de l'app
  // (avant les écrans D4) doit continuer à se charger sans erreur - ce test
  // fige le format JSON réellement sur disque comme garde-fou de non-
  // régression.
  test('a JSON blob matching the current on-disk format still loads correctly (backward compatibility)', () async {
    SharedPreferences.setMockInitialValues({
      'transactions': '[{"id":"TOL-OLD","operator":"Orange","service":"Internet",'
          '"operation":"Souscription pour moi","phone":"0700000001","amount":1000,'
          '"paymentMethod":"CinetPay","date":"2026-01-01T10:30:00.000",'
          '"status":"pending"}]',
    });

    final loaded = await TransactionService.load();

    expect(loaded, hasLength(1));
    expect(loaded.single.id, 'TOL-OLD');
    expect(loaded.single.status, 'pending');
    expect(loaded.single.amount, 1000);
  });

  test('a malformed stored blob loads as an empty list rather than throwing', () async {
    SharedPreferences.setMockInitialValues({'transactions': 'not valid json'});

    expect(await TransactionService.load(), isEmpty);
  });
}
