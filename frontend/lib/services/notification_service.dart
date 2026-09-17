import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/models.dart';

class NotificationService {
  static const _key = 'notifications';
  static const hiddenKey = 'locally_hidden_notification_keys';

  static String notificationKey(AppNotification notification) {
    if (notification.id != null) return 'id:${notification.id}';
    return 'local:${notification.title}|${notification.time}|${notification.message}';
  }

  static Future<Set<String>> getHiddenKeys() async {
    final prefs = await SharedPreferences.getInstance();
    final list = prefs.getStringList(hiddenKey) ?? const [];
    return list.toSet();
  }

  static Future<void> hideNotification(AppNotification notification) async {
    final key = notificationKey(notification);
    final prefs = await SharedPreferences.getInstance();
    final current = (prefs.getStringList(hiddenKey) ?? const []).toSet();
    current.add(key);
    await prefs.setStringList(hiddenKey, current.toList());
  }

  static Future<void> hideNotifications(
      Iterable<AppNotification> notifications) async {
    final keys = notifications.map(notificationKey).toSet();
    final prefs = await SharedPreferences.getInstance();
    final current = (prefs.getStringList(hiddenKey) ?? const []).toSet();
    current.addAll(keys);
    await prefs.setStringList(hiddenKey, current.toList());
  }

  static Future<List<AppNotification>> load(
      {bool includeHidden = false}) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key);
    if (raw == null || raw.isEmpty) return [];
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      final all =
          list.map((item) => _fromJson(item as Map<String, dynamic>)).toList();
      if (includeHidden) return all;
      final hidden = (prefs.getStringList(hiddenKey) ?? const []).toSet();
      return all.where((n) => !hidden.contains(notificationKey(n))).toList();
    } catch (_) {
      return [];
    }
  }

  static Future<void> save(List<AppNotification> notifications) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _key,
      jsonEncode(notifications.map(_toJson).toList()),
    );
  }

  static Future<List<AppNotification>> add(
    List<AppNotification> current,
    AppNotification notification,
  ) async {
    final updated = [notification, ...current];
    await save(updated);
    return updated;
  }

  static Future<void> remove(AppNotification notification) async {
    await hideNotification(notification);
    final current = await load(includeHidden: false);
    final updated = current
        .where((n) => notificationKey(n) != notificationKey(notification))
        .toList();
    await save(updated);
  }

  static Future<void> clearAll(Iterable<AppNotification> notifications) async {
    await hideNotifications(notifications);
    await clear();
  }

  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
  }

  static Map<String, dynamic> _toJson(AppNotification notification) => {
        'title': notification.title,
        'message': notification.message,
        'time': notification.time,
        'read': notification.read,
        'icon': notification.icon,
        'type': notification.type,
        'reference': notification.reference,
        'operator': notification.operator,
        'service': notification.service,
        'operation': notification.operation,
        'phone': notification.phone,
        'amount': notification.amount,
        'fee': notification.fee,
        'total': notification.total,
        'paymentMethod': notification.paymentMethod,
        'date': notification.date,
        'heure': notification.heure,
        'id': notification.id,
      };

  static AppNotification _fromJson(Map<String, dynamic> json) {
    return AppNotification(
      title: json['title'] as String? ?? '',
      message: json['message'] as String? ?? '',
      time: json['time'] as String? ?? '',
      read: json['read'] as bool? ?? false,
      icon: json['icon'] as String? ?? 'info',
      type: json['type'] as String? ?? 'info',
      reference: json['reference'] as String?,
      operator: json['operator'] as String?,
      service: json['service'] as String?,
      operation: json['operation'] as String?,
      phone: json['phone'] as String?,
      amount: json['amount'] as String?,
      fee: json['fee'] as String?,
      total: json['total'] as String?,
      paymentMethod: json['paymentMethod'] as String?,
      date: json['date'] as String?,
      heure: json['heure'] as String?,
      id: (json['id'] as num?)?.toInt(),
    );
  }
}
