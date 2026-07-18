import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/models.dart';

// ─── TransactionService ───────────────────────────────────────────────────────
// Gère la persistance locale des transactions via shared_preferences.
// Les transactions sont sérialisées en JSON et stockées sous la clé 'transactions'.

class TransactionService {
  static const _key = 'transactions';

  /// Sauvegarde la liste de transactions en JSON dans shared_preferences.
  static Future<void> save(List<Transaction> transactions) async {
    final prefs = await SharedPreferences.getInstance();
    final jsonList = transactions.map(_toJson).toList();
    await prefs.setString(_key, jsonEncode(jsonList));
  }

  /// Charge et retourne les transactions sauvegardées.
  /// Retourne une liste vide si aucune donnée n'est trouvée.
  static Future<List<Transaction>> load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key);
    if (raw == null || raw.isEmpty) return [];
    try {
      final jsonList = jsonDecode(raw) as List<dynamic>;
      return jsonList.map((e) => _fromJson(e as Map<String, dynamic>)).toList();
    } catch (_) {
      return [];
    }
  }

  /// Ajoute une transaction en tête de liste et sauvegarde.
  static Future<List<Transaction>> addTransaction(
      List<Transaction> current, Transaction newTxn) async {
    final updated = [newTxn, ...current];
    await save(updated);
    return updated;
  }

  /// Efface toutes les transactions sauvegardées.
  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
  }

  // ── Sérialisation ────────────────────────────────────────────────────────────

  static Map<String, dynamic> _toJson(Transaction t) => {
        'id': t.id,
        'operator': t.operator,
        'service': t.service,
        'operation': t.operation,
        'phone': t.phone,
        'amount': t.amount,
        'paymentMethod': t.paymentMethod,
        'date': t.date.toIso8601String(),
        'status': t.status,
      };

  static Transaction _fromJson(Map<String, dynamic> j) => Transaction(
        id: j['id'] as String,
        operator: j['operator'] as String,
        service: j['service'] as String,
        operation: j['operation'] as String,
        phone: j['phone'] as String,
        amount: j['amount'] as int,
        paymentMethod: j['paymentMethod'] as String,
        date: DateTime.parse(j['date'] as String),
        status: j['status'] as String,
      );
}
