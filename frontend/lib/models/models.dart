class Transaction {
  final String id;
  final String operator;
  final String service;
  final String operation;
  final String phone;
  final int amount;
  final String paymentMethod;
  final DateTime date;
  final String status; // 'ok' | 'fail' | 'pending' | 'cancelled'

  Transaction({
    required this.id,
    required this.operator,
    required this.service,
    required this.operation,
    required this.phone,
    required this.amount,
    required this.paymentMethod,
    required this.date,
    required this.status,
  });

  String get statusLabel {
    switch (status) {
      case 'ok':
        return 'Réussie';
      case 'fail':
        return 'Échouée';
      case 'cancelled':
        return 'Annulée';
      default:
        return 'En attente';
    }
  }

  String get serviceIcon {
    switch (service) {
      case 'Internet':
        return '🌐';
      case 'Appels':
        return '📞';
      case 'SMS':
        return '💬';
      default:
        return '📋';
    }
  }

  int get fee => (amount * 0.01).round();
  int get total => amount + fee;
}

class AppNotification {
  final String title;
  final String message;
  final String time;
  bool read;
  final String icon;
  final String type; // 'success' | 'error' | 'warning' | 'info'
  final String? reference;
  final String? operator;
  final String? service;
  final String? operation;
  final String? phone;
  final String? amount;
  final String? fee;
  final String? total;
  final String? paymentMethod;
  final String? date;
  final String? heure;

  AppNotification({
    required this.title,
    required this.message,
    required this.time,
    required this.read,
    required this.icon,
    required this.type,
    this.reference,
    this.operator,
    this.service,
    this.operation,
    this.phone,
    this.amount,
    this.fee,
    this.total,
    this.paymentMethod,
    this.date,
    this.heure,
  });
}

class OperatorItem {
  final int id;
  final String name;
  final String code;

  const OperatorItem({required this.id, required this.name, required this.code});

  factory OperatorItem.fromJson(Map<String, dynamic> json) {
    return OperatorItem(
      id: json['id'] as int,
      name: json['name'] as String,
      code: json['code'] as String? ?? '',
    );
  }
}

class ServiceItem {
  final int id;
  final String name;
  final String code;

  const ServiceItem({required this.id, required this.name, required this.code});

  factory ServiceItem.fromJson(Map<String, dynamic> json) {
    return ServiceItem(
      id: json['id'] as int,
      name: json['name'] as String,
      code: json['code'] as String? ?? '',
    );
  }
}

class AmountItem {
  final double amount;

  const AmountItem({required this.amount});

  factory AmountItem.fromJson(Map<String, dynamic> json) {
    return AmountItem(amount: (json['amount'] as num).toDouble());
  }
}

class OperationConfig {
  final String name;
  final String subtitle;
  final String icon;
  final int colorValue;

  const OperationConfig({
    required this.name,
    required this.subtitle,
    required this.icon,
    required this.colorValue,
  });
}

// Sample data
List<Transaction> sampleTransactions = [
  Transaction(
      id: 'TRX-2025-000125',
      operator: 'Orange',
      service: 'Internet',
      operation: 'Souscription pour moi',
      phone: '0701234567',
      amount: 1000,
      paymentMethod: 'CinetPay',
      date: DateTime.now().subtract(const Duration(hours: 2)),
      status: 'ok'),
  Transaction(
      id: 'TRX-2025-000124',
      operator: 'MTN',
      service: 'Appels',
      operation: 'Souscription pour moi',
      phone: '0701234567',
      amount: 2000,
      paymentMethod: 'CinetPay',
      date: DateTime.now().subtract(const Duration(days: 1)),
      status: 'ok'),
  Transaction(
      id: 'TRX-2025-000123',
      operator: 'Orange',
      service: 'SMS',
      operation: 'Transfert pour moi',
      phone: '0705678901',
      amount: 500,
      paymentMethod: 'CinetPay',
      date: DateTime.now().subtract(const Duration(days: 2)),
      status: 'ok'),
  Transaction(
      id: 'TRX-2025-000122',
      operator: 'Moov',
      service: 'Internet',
      operation: 'Souscription pour moi',
      phone: '0701234567',
      amount: 5000,
      paymentMethod: 'CinetPay',
      date: DateTime.now().subtract(const Duration(days: 3)),
      status: 'fail'),
  Transaction(
      id: 'TRX-2025-000121',
      operator: 'MTN',
      service: 'Appels',
      operation: 'Transfert pour un tiers',
      phone: '0709876543',
      amount: 1000,
      paymentMethod: 'CinetPay',
      date: DateTime.now().subtract(const Duration(days: 4)),
      status: 'ok'),
  Transaction(
      id: 'TRX-2025-000120',
      operator: 'Orange',
      service: 'Internet',
      operation: 'Souscription pour un tiers',
      phone: '0701234567',
      amount: 2000,
      paymentMethod: 'CinetPay',
      date: DateTime.now().subtract(const Duration(days: 5)),
      status: 'ok'),
];

List<AppNotification> sampleNotifications = [
  AppNotification(
      title: 'Souscription Internet Orange réussie',
      message:
          'Numéro : 0701234567\nMontant forfait : 1000 FCFA\nFrais de service (1%) : 10 FCFA\nTotal débité : 1010 FCFA',
      time: "Aujourd'hui · 10:45",
      read: false,
      icon: 'success',
      type: 'success'),
  AppNotification(
      title: 'Échec de transfert MTN',
      message:
          'Numéro : 0501234567\nMontant demandé : 500 FCFA\nSolde insuffisant',
      time: "Aujourd'hui · 09:22",
      read: false,
      icon: 'error',
      type: 'error'),
  AppNotification(
      title: 'Nouveau forfait disponible',
      message: 'Profitez de nos nouveaux forfaits Internet\nà prix avantageux.',
      time: "Aujourd'hui · 08:10",
      read: false,
      icon: 'info',
      type: 'info'),
  AppNotification(
      title: 'Transfert SMS Moov réussi',
      message:
          'Numéro : 0101234567\nMontant forfait : 200 FCFA\nFrais de service (1%) : 2 FCFA\nTotal débité : 202 FCFA',
      time: "Hier · 18:15",
      read: true,
      icon: 'success',
      type: 'success'),
  AppNotification(
      title: 'Information importante',
      message: 'Maintenance programmée ce soir\nde 23h à 01h.',
      time: "Hier · 17:00",
      read: true,
      icon: 'info',
      type: 'info'),
  AppNotification(
      title: 'Souscription Appels Orange réussie',
      message:
          'Numéro : 0709876543\nMontant forfait : 500 FCFA\nFrais de service (1%) : 5 FCFA\nTotal débité : 505 FCFA',
      time: "Avant-hier · 21:30",
      read: true,
      icon: 'success',
      type: 'success'),
  AppNotification(
      title: 'Transfert pour un tiers échoué',
      message:
          'Numéro : 0555567890\nMontant demandé : 1000 FCFA\nSolde insuffisant',
      time: "Avant-hier · 20:05",
      read: true,
      icon: 'error',
      type: 'error'),
];
