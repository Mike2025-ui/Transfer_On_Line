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

    await tester.pumpWidget(MaterialApp(
      home: NotificationsScreen(notifications: [notification]),
    ));
    await tester.pump();

    expect(find.text('Transaction réussie'), findsOneWidget);
    await tester.tap(find.text('Tout effacer'));
    await tester.pumpAndSettle();

    expect(find.text('Transaction réussie'), findsNothing);
    final prefs = await SharedPreferences.getInstance();
    expect(
      jsonDecode(
          jsonEncode(prefs.getStringList('locally_hidden_notification_keys'))),
      ['id:42'],
    );
  });
}
