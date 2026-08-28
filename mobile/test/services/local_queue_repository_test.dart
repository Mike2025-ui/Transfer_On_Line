import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:gateway_apk/services/gateway_api.dart'
    show PendingTransaction, SmsPendingTask, generateIdempotencyKey;
import 'package:gateway_apk/services/local_queue_repository.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// Exercises the "dial at most once, retry only the report" invariant this
/// repository exists to protect - see its class doc. Runs against a real
/// SQLite engine on the host (sqflite_common_ffi), a fresh in-memory
/// database per test.
void main() {
  sqfliteFfiInit();

  late LocalQueueRepository repo;

  setUp(() {
    repo = LocalQueueRepository(
      databaseFactory: databaseFactoryFfi,
      path: inMemoryDatabasePath,
    );
  });

  tearDown(() async {
    await repo.close();
  });

  PendingTransaction task({
    String reference = 'TOL-1',
    String? ussdCode = '*456*1000#',
    int? simSlot,
    String? operator,
  }) {
    return PendingTransaction(
      id: 1,
      type: 'subscription',
      recipientPhone: '0700000000',
      amount: 1000,
      serverReference: reference,
      ussdCode: ussdCode,
      simSlot: simSlot,
      operator: operator,
    );
  }

  group('enqueueTransactionTasks', () {
    test('inserts a new task as pending_dial', () async {
      await repo.enqueueTransactionTasks([task()]);
      final next = await repo.nextTaskToDial();
      expect(next, isNotNull);
      expect(next!.reference, 'TOL-1');
      expect(next.state, TaskState.pendingDial);
      expect(next.ussdCode, '*456*1000#');
    });

    test('Phase D audit (Critique): operator round-trips through the local queue', () async {
      await repo.enqueueTransactionTasks([task(operator: 'Orange')]);
      final next = await repo.nextTaskToDial();
      expect(next!.operator, 'Orange');
    });

    test('a task with no operator (older backend/flag off) stores null, never fabricates one', () async {
      await repo.enqueueTransactionTasks([task()]);
      final next = await repo.nextTaskToDial();
      expect(next!.operator, isNull);
    });

    test('leaves an in-progress row untouched on re-poll', () async {
      await repo.enqueueTransactionTasks([task()]);
      final first = await repo.nextTaskToDial();
      await repo.markDialing(first!.id);

      // Server hands back the same reference on the next poll (still the
      // same attempt in flight) - must not reset it back to pending_dial.
      await repo.enqueueTransactionTasks([task(ussdCode: '*456*9999#')]);

      final awaitingDial = await repo.nextTaskToDial();
      expect(awaitingDial, isNull, reason: 'the in-flight row must not be reset to pending_dial');
    });

    test('re-arms a done row when the server reassigns the same reference', () async {
      await repo.enqueueTransactionTasks([task()]);
      final t = (await repo.nextTaskToDial())!;
      await repo.markDialing(t.id);
      await repo.markDialed(t.id, success: false, result: 'timeout');
      await repo.markReported(t.id);

      // RetryManager scheduled a retry on a different SIM - same reference,
      // new ussd_code/sim_slot.
      await repo.enqueueTransactionTasks([task(ussdCode: '*456*2222#', simSlot: 1)]);

      final reArmed = await repo.nextTaskToDial();
      expect(reArmed, isNotNull);
      expect(reArmed!.ussdCode, '*456*2222#');
      expect(reArmed.simSlot, 1);
      expect(reArmed.dialSuccess, isNull, reason: 'a re-armed task has no outcome yet');
    });
  });

  group('dial lifecycle', () {
    test('markDialing only succeeds once per task (no double-claim)', () async {
      await repo.enqueueTransactionTasks([task()]);
      final t = (await repo.nextTaskToDial())!;

      final firstClaim = await repo.markDialing(t.id);
      final secondClaim = await repo.markDialing(t.id);

      expect(firstClaim, isTrue);
      expect(secondClaim, isFalse);
    });

    test('markDialed moves the task into the awaiting-report bucket', () async {
      await repo.enqueueTransactionTasks([task()]);
      final t = (await repo.nextTaskToDial())!;
      await repo.markDialing(t.id);
      await repo.markDialed(t.id, success: true, result: 'OK');

      final awaiting = await repo.tasksAwaitingReport();
      expect(awaiting, hasLength(1));
      expect(awaiting.first.dialSuccess, isTrue);
      expect(awaiting.first.dialResult, 'OK');
    });
  });

  group('recoverInterruptedDials', () {
    test('a dial older than the grace window is marked UNKNOWN_INTERRUPTED, never re-dialed', () async {
      await repo.enqueueTransactionTasks([task()]);
      final t = (await repo.nextTaskToDial())!;
      await repo.markDialing(t.id);

      final recovered = await repo.recoverInterruptedDials(grace: const Duration(seconds: -1));
      expect(recovered, 1);

      // The critical assertion: it must NOT be dial-able again.
      expect(await repo.nextTaskToDial(), isNull);

      final awaiting = await repo.tasksAwaitingReport();
      expect(awaiting, hasLength(1));
      expect(awaiting.first.dialSuccess, isNull);
      expect(awaiting.first.dialResult, 'UNKNOWN_INTERRUPTED');
    });

    test('a dial still within the grace window is left alone', () async {
      await repo.enqueueTransactionTasks([task()]);
      final t = (await repo.nextTaskToDial())!;
      await repo.markDialing(t.id);

      final recovered = await repo.recoverInterruptedDials(grace: const Duration(minutes: 5));
      expect(recovered, 0);
      expect(await repo.tasksAwaitingReport(), isEmpty);
    });
  });

  group('report lifecycle', () {
    test('markReported settles the task as done', () async {
      await repo.enqueueTransactionTasks([task()]);
      final t = (await repo.nextTaskToDial())!;
      await repo.markDialing(t.id);
      await repo.markDialed(t.id, success: true, result: 'OK');
      await repo.markReported(t.id);

      expect(await repo.tasksAwaitingReport(), isEmpty);
      expect(await repo.pendingTaskCount(), 0);
    });

    test('recordReportFailure keeps the task awaiting report and counts attempts', () async {
      await repo.enqueueTransactionTasks([task()]);
      final t = (await repo.nextTaskToDial())!;
      await repo.markDialing(t.id);
      await repo.markDialed(t.id, success: true, result: 'OK');

      await repo.recordReportFailure(t.id, 'offline');
      await repo.recordReportFailure(t.id, 'offline');

      final awaiting = await repo.tasksAwaitingReport();
      expect(awaiting, hasLength(1));
      expect(awaiting.first.reportAttempts, 2);
      expect(awaiting.first.lastReportError, 'offline');
    });
  });

  test('pendingTaskCount excludes only fully-done tasks', () async {
    await repo.enqueueTransactionTasks([task(reference: 'A'), task(reference: 'B')]);
    expect(await repo.pendingTaskCount(), 2);

    final a = await repo.nextTaskToDial();
    await repo.markDialing(a!.id);
    await repo.markDialed(a.id, success: true, result: 'OK');
    await repo.markReported(a.id);

    expect(await repo.pendingTaskCount(), 1);
  });

  group('SMS tasks', () {
    SmsPendingTask smsTask({int id = 1, String phone = '0700000000', String message = 'code: 123456'}) {
      return SmsPendingTask(id: id, phoneNumber: phone, message: message, purpose: 'otp');
    }

    test('enqueueSmsTasks inserts a new task as pending_send', () async {
      await repo.enqueueSmsTasks([smsTask()]);
      final next = await repo.nextSmsToSend();
      expect(next, isNotNull);
      expect(next!.serverId, 1);
      expect(next.state, SmsTaskState.pendingSend);
    });

    test('markSmsSending only succeeds once per task (no double-send)', () async {
      await repo.enqueueSmsTasks([smsTask()]);
      final t = (await repo.nextSmsToSend())!;
      expect(await repo.markSmsSending(t.id), isTrue);
      expect(await repo.markSmsSending(t.id), isFalse);
    });

    test('reconcileSmsOutcomes resolves a sending row into sent_result_known', () async {
      await repo.enqueueSmsTasks([smsTask()]);
      final t = (await repo.nextSmsToSend())!;
      await repo.markSmsSending(t.id);

      await repo.reconcileSmsOutcomes([
        {'taskId': t.id, 'sent': 'sent', 'delivered': 'delivered'},
      ]);

      final awaiting = await repo.smsTasksAwaitingReport();
      expect(awaiting, hasLength(1));
      expect(awaiting.first.sendSuccess, isTrue);
      expect(awaiting.first.sendResult, 'sent/delivered');
    });

    test('reconcileSmsOutcomes ignores outcomes for tasks not currently sending', () async {
      // No enqueue/markSmsSending at all - a stray/duplicate outbox entry
      // must never resurrect or fabricate a task.
      await repo.reconcileSmsOutcomes([
        {'taskId': 999, 'sent': 'sent', 'delivered': null},
      ]);
      expect(await repo.smsTasksAwaitingReport(), isEmpty);
    });

    test('recoverInterruptedSmsSends resolves a stale sending row, never re-sent', () async {
      await repo.enqueueSmsTasks([smsTask()]);
      final t = (await repo.nextSmsToSend())!;
      await repo.markSmsSending(t.id);

      final recovered = await repo.recoverInterruptedSmsSends(grace: const Duration(seconds: -1));
      expect(recovered, 1);
      expect(await repo.nextSmsToSend(), isNull);

      final awaiting = await repo.smsTasksAwaitingReport();
      expect(awaiting, hasLength(1));
      expect(awaiting.first.sendSuccess, isNull);
      expect(awaiting.first.sendResult, 'UNKNOWN_INTERRUPTED');
    });

    test(
      'a native receipt arriving after recoverInterruptedSmsSends already resolved the row is traced, never resurrects it (Stabilisation RC1, priorité moyenne n°11)',
      () async {
        await repo.enqueueSmsTasks([smsTask()]);
        final t = (await repo.nextSmsToSend())!;
        await repo.markSmsSending(t.id);
        await repo.recoverInterruptedSmsSends(grace: const Duration(seconds: -1));

        // The native sent/delivered receipt only shows up now - well after
        // the grace window already moved this row to sent_result_known with
        // an indeterminate outcome. It must be ignored, not overwrite the
        // already-settled result.
        await repo.reconcileSmsOutcomes([
          {'taskId': t.id, 'sent': 'sent', 'delivered': 'delivered'},
        ]);

        final awaiting = await repo.smsTasksAwaitingReport();
        expect(awaiting, hasLength(1));
        expect(
          awaiting.first.sendResult,
          'UNKNOWN_INTERRUPTED',
          reason: 'the late receipt must never overwrite the already-resolved outcome',
        );
      },
    );

    test('markSmsReported settles the task as done and out of pendingTaskCount', () async {
      await repo.enqueueSmsTasks([smsTask()]);
      final t = (await repo.nextSmsToSend())!;
      await repo.markSmsSending(t.id);
      await repo.markSmsResultKnown(t.id, success: true, result: 'sent');
      expect(await repo.pendingTaskCount(), 1);

      await repo.markSmsReported(t.id);
      expect(await repo.smsTasksAwaitingReport(), isEmpty);
      expect(await repo.pendingTaskCount(), 0);
    });

    test('recordSmsReportFailure keeps the task awaiting report and counts attempts', () async {
      await repo.enqueueSmsTasks([smsTask()]);
      final t = (await repo.nextSmsToSend())!;
      await repo.markSmsSending(t.id);
      await repo.markSmsResultKnown(t.id, success: true, result: 'sent');

      await repo.recordSmsReportFailure(t.id, 'offline');

      final awaiting = await repo.smsTasksAwaitingReport();
      expect(awaiting, hasLength(1));
      expect(awaiting.first.reportAttempts, 1);
      expect(awaiting.first.lastReportError, 'offline');
    });
  });

  group('interactive_session (Phase D2)', () {
    test('startInteractiveSession creates the row', () async {
      final created = await repo.startInteractiveSession(transactionReference: 'TOL-1', attemptId: 45);
      expect(created, isTrue);
      final session = await repo.currentInteractiveSession();
      expect(session, isNotNull);
      expect(session!.transactionReference, 'TOL-1');
      expect(session.attemptId, 45);
    });

    test('a second session is refused while one is active (real SQLite constraint)', () async {
      final first = await repo.startInteractiveSession(transactionReference: 'TOL-1', attemptId: 45);
      final second = await repo.startInteractiveSession(transactionReference: 'TOL-2', attemptId: 46);
      expect(first, isTrue);
      expect(second, isFalse);
      final session = await repo.currentInteractiveSession();
      expect(session!.transactionReference, 'TOL-1'); // the first one, untouched
    });

    test('two concurrent attempts to start a session: exactly one succeeds', () async {
      final results = await Future.wait([
        repo.startInteractiveSession(transactionReference: 'TOL-A', attemptId: 1),
        repo.startInteractiveSession(transactionReference: 'TOL-B', attemptId: 2),
      ]);
      expect(results.where((r) => r).length, 1);
      expect(results.where((r) => !r).length, 1);
    });

    test('recordPendingStepEvent persists event/key/payload for a later retry', () async {
      await repo.startInteractiveSession(transactionReference: 'TOL-1', attemptId: 45);
      await repo.recordPendingStepEvent(
        event: 'NEW_FIELD', idempotencyKey: 'KEY-A', payload: '{"field_count":1}',
      );

      final session = await repo.currentInteractiveSession();
      expect(session!.pendingEvent, 'NEW_FIELD');
      expect(session.pendingIdempotencyKey, 'KEY-A');
      expect(session.pendingPayload, '{"field_count":1}');
      expect(session.lastResponse, isNull);
    });

    test('recordStepResponse persists the response without touching the pending event', () async {
      await repo.startInteractiveSession(transactionReference: 'TOL-1', attemptId: 45);
      await repo.recordPendingStepEvent(event: 'NEW_FIELD', idempotencyKey: 'KEY-A', payload: '{}');

      await repo.recordStepResponse('{"action":"INPUT","values":["0700000000"]}');

      final session = await repo.currentInteractiveSession();
      expect(session!.lastResponse, '{"action":"INPUT","values":["0700000000"]}');
      expect(session.pendingIdempotencyKey, 'KEY-A'); // unchanged
    });

    test('closeInteractiveSession removes the row so a new session can start', () async {
      await repo.startInteractiveSession(transactionReference: 'TOL-1', attemptId: 45);
      await repo.closeInteractiveSession();

      expect(await repo.currentInteractiveSession(), isNull);
      final started = await repo.startInteractiveSession(transactionReference: 'TOL-2', attemptId: 46);
      expect(started, isTrue);
    });

    test(
      'idempotence scenario: a network-failed NEW_FIELD retry reuses the same key/payload, '
      'and the next real event (FINAL_FIELD) gets a fresh one',
      () async {
        await repo.startInteractiveSession(transactionReference: 'TOL-1', attemptId: 45);

        final keyA = generateIdempotencyKey();
        await repo.recordPendingStepEvent(
          event: 'NEW_FIELD', idempotencyKey: keyA, payload: '{"field_count":1}',
        );
        // Simulated network failure: recordStepResponse is never called.

        // Retry re-reads the session instead of generating a new key.
        final beforeRetry = await repo.currentInteractiveSession();
        expect(beforeRetry!.pendingIdempotencyKey, keyA);
        expect(beforeRetry.pendingPayload, '{"field_count":1}');
        // The retry "succeeds" this time.
        await repo.recordStepResponse('{"action":"INPUT","values":["0700000000"]}');

        // Next, genuinely new event: a fresh key is generated and stored.
        final keyB = generateIdempotencyKey();
        expect(keyB, isNot(keyA));
        await repo.recordPendingStepEvent(event: 'FINAL_FIELD', idempotencyKey: keyB, payload: '{}');

        final finalState = await repo.currentInteractiveSession();
        expect(finalState!.pendingIdempotencyKey, keyB);
      },
    );
  });

  group('migration v2 -> v3 (Phase D2)', () {
    late String tempPath;

    setUp(() {
      tempPath = p.join(
        Directory.systemTemp.path,
        'gateway_queue_test_${DateTime.now().microsecondsSinceEpoch}.db',
      );
    });

    tearDown(() async {
      final file = File(tempPath);
      if (await file.exists()) await file.delete();
    });

    test('upgrading from v2 preserves existing data and adds interactive_session', () async {
      // Manually recreates the schema exactly as it existed before this
      // phase (v2) - never calls LocalQueueRepository's private _onCreate,
      // since the whole point is to prove a REAL pre-existing v2 database
      // survives the upgrade, not to test the current code against itself.
      final v2Db = await databaseFactoryFfi.openDatabase(
        tempPath,
        options: OpenDatabaseOptions(
          version: 2,
          onCreate: (db, version) async {
            await db.execute('''
              CREATE TABLE transaction_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT NOT NULL UNIQUE,
                transaction_type TEXT, recipient_phone TEXT, amount REAL, ussd_code TEXT NOT NULL,
                sim_slot INTEGER, operator TEXT, state TEXT NOT NULL, dial_success INTEGER,
                dial_result TEXT, report_attempts INTEGER NOT NULL DEFAULT 0, last_report_error TEXT,
                created_at TEXT NOT NULL, dialing_at TEXT, dialed_at TEXT, reported_at TEXT
              )
            ''');
            await db.execute('''
              CREATE TABLE sms_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, server_id INTEGER NOT NULL UNIQUE,
                phone_number TEXT, message TEXT, purpose TEXT, state TEXT NOT NULL,
                send_success INTEGER, send_result TEXT, report_attempts INTEGER NOT NULL DEFAULT 0,
                last_report_error TEXT, created_at TEXT NOT NULL, sending_at TEXT, sent_at TEXT,
                reported_at TEXT
              )
            ''');
          },
        ),
      );
      await v2Db.insert('transaction_tasks', {
        'reference': 'TOL-OLD', 'ussd_code': '*456*1000#', 'state': TaskState.done,
        'created_at': DateTime.now().toIso8601String(),
      });
      await v2Db.close();

      // Reopening the SAME file via the real repository triggers onUpgrade(2, 3).
      final repo = LocalQueueRepository(databaseFactory: databaseFactoryFfi, path: tempPath);
      final started = await repo.startInteractiveSession(transactionReference: 'TOL-NEW', attemptId: 1);
      expect(started, isTrue, reason: 'interactive_session table must exist after upgrade');
      await repo.close();

      final verifyDb = await databaseFactoryFfi.openDatabase(tempPath);
      final oldRows = await verifyDb.query('transaction_tasks', where: 'reference = ?', whereArgs: ['TOL-OLD']);
      expect(oldRows, hasLength(1), reason: 'pre-existing v2 data must survive the upgrade');
      await verifyDb.close();
    });

    test('a fresh v3 install creates interactive_session directly via onCreate', () async {
      final repo = LocalQueueRepository(databaseFactory: databaseFactoryFfi, path: tempPath);
      final started = await repo.startInteractiveSession(transactionReference: 'TOL-1', attemptId: 1);
      expect(started, isTrue);
      await repo.close();
    });
  });
}
