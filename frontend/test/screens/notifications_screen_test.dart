import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:transfer_on_line/models/models.dart';
import 'package:transfer_on_line/screens/notifications_screen.dart';

void main() {
  testWidgets('Tout effacer masque les notifications uniquement en local',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final notification = AppNotification(
      id: 42,
      title: 'Transaction réussie',
      message: 'Montant forfait : 1000 FCFA',
      time: "Aujourd'hui · 10:45",
      read: false,
      icon: 'success',
      type: 'success',
    );

    List<AppNotification>? changedNotifications;
    await tester.pumpWidget(MaterialApp(
      home: NotificationsScreen(
        notifications: [notification],
        onNotificationsChanged: (updated) => changedNotifications = updated,
      ),
    ));
    await tester.pump();

    expect(find.text('Transaction réussie'), findsOneWidget);
    // Le badge sur la cloche affiche "1"
    expect(find.text('1'), findsWidgets);

    await tester.tap(find.text('Tout effacer'));
    await tester.pumpAndSettle();

    expect(find.text('Transaction réussie'), findsNothing);
    // Le badge sur la cloche a disparu
    expect(find.text('1'), findsNothing);
    expect(changedNotifications, isEmpty);

    final prefs = await SharedPreferences.getInstance();
    expect(
      jsonDecode(
          jsonEncode(prefs.getStringList('locally_hidden_notification_keys'))),
      ['id:42'],
    );
  });

  testWidgets(
      'Glisser pour supprimer une notification la masque et réinitialise le badge',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final notification = AppNotification(
      id: 99,
      title: 'Alerte importante',
      message: 'Maintenance réseau',
      time: "Aujourd'hui · 11:00",
      read: false,
      icon: 'info',
      type: 'info',
    );

    List<AppNotification>? changedNotifications;
    await tester.pumpWidget(MaterialApp(
      home: NotificationsScreen(
        notifications: [notification],
        onNotificationsChanged: (updated) => changedNotifications = updated,
      ),
    ));
    await tester.pump();

    expect(find.text('Alerte importante'), findsOneWidget);
    expect(find.text('1'), findsWidgets);

    // Glisser de droite à gauche pour supprimer
    await tester.drag(find.text('Alerte importante'), const Offset(-500, 0));
    await tester.pumpAndSettle();

    expect(find.text('Alerte importante'), findsNothing);
    expect(find.text('1'), findsNothing);
    expect(changedNotifications, isEmpty);

    final prefs = await SharedPreferences.getInstance();
    expect(
      jsonDecode(
          jsonEncode(prefs.getStringList('locally_hidden_notification_keys'))),
      ['id:99'],
    );
  });
}
