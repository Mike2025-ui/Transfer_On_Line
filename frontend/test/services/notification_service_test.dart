import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:transfer_on_line/models/models.dart';
import 'package:transfer_on_line/services/notification_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('load() returns empty list when no notifications saved', () async {
    final list = await NotificationService.load();
    expect(list, isEmpty);
  });

  test('save() and load() roundtrips notifications accurately', () async {
    final notif = AppNotification(
      id: 1,
      title: 'Transfert réussi',
      message: 'Montant : 500 FCFA',
      time: "Aujourd'hui · 12:00",
      read: false,
      icon: 'success',
      type: 'success',
      reference: 'TOL-REF-1',
    );

    await NotificationService.save([notif]);
    final loaded = await NotificationService.load();

    expect(loaded.length, 1);
    expect(loaded.first.id, 1);
    expect(loaded.first.title, 'Transfert réussi');
    expect(loaded.first.read, false);
  });

  test('load() excludes locally hidden notifications by default', () async {
    final notif1 = AppNotification(
      id: 1,
      title: 'Transfert 1',
      message: 'Message 1',
      time: "Aujourd'hui · 12:00",
      read: false,
      icon: 'success',
      type: 'success',
    );
    final notif2 = AppNotification(
      id: 2,
      title: 'Transfert 2',
      message: 'Message 2',
      time: "Aujourd'hui · 12:05",
      read: true,
      icon: 'info',
      type: 'info',
    );

    await NotificationService.save([notif1, notif2]);
    await NotificationService.hideNotification(notif1);

    final visible = await NotificationService.load();
    expect(visible.length, 1);
    expect(visible.first.id, 2);

    final all = await NotificationService.load(includeHidden: true);
    expect(all.length, 2);
  });

  test('remove() hides and removes the notification from storage', () async {
    final notif = AppNotification(
      id: 5,
      title: 'Test',
      message: 'Test message',
      time: '12:00',
      read: false,
      icon: 'info',
      type: 'info',
    );

    await NotificationService.save([notif]);
    await NotificationService.remove(notif);

    final visible = await NotificationService.load();
    expect(visible, isEmpty);

    final hiddenKeys = await NotificationService.getHiddenKeys();
    expect(hiddenKeys, contains('id:5'));
  });

  test('clearAll() hides all notifications and clears storage', () async {
    final notif1 = AppNotification(
      id: 10,
      title: 'A',
      message: 'Msg A',
      time: '10:00',
      read: false,
      icon: 'info',
      type: 'info',
    );
    final notif2 = AppNotification(
      id: 11,
      title: 'B',
      message: 'Msg B',
      time: '11:00',
      read: false,
      icon: 'info',
      type: 'info',
    );

    await NotificationService.save([notif1, notif2]);
    await NotificationService.clearAll([notif1, notif2]);

    final visible = await NotificationService.load();
    expect(visible, isEmpty);

    final hiddenKeys = await NotificationService.getHiddenKeys();
    expect(hiddenKeys, containsAll(['id:10', 'id:11']));
  });
}
