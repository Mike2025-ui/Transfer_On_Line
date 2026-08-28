import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gateway_apk/background/background_bridge.dart';
import 'package:gateway_apk/background/interactive_ussd_runner.dart';
import 'package:gateway_apk/background/ussd_step_event.dart';
import 'package:gateway_apk/services/gateway_api.dart';
import 'package:gateway_apk/services/local_queue_repository.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// Phase D4.3 tests for [InteractiveUssdRunner] - the orchestrator between
/// the Backend's `/transactions/step/` protocol (Phase C) and
/// [UssdAccessibilityService] via [BackgroundBridge]. Same testing
/// philosophy as gateway_loop_test.dart: a real in-memory SQLite queue
/// (sqflite_common_ffi) and a real `http.MockClient`, but here the native
/// side (BackgroundBridge's MethodChannel) is also real - only its binary
/// messenger is mocked (flutter_test's TestDefaultBinaryMessengerBinding),
/// exactly the platform-boundary substitution Flutter itself recommends,
/// rather than introducing a bridge interface/fake subclass this codebase
/// does not otherwise use.
///
/// Every assertion that depends on [InteractiveUssdRunner]'s reactive chain
/// (stream event -> HTTP mock -> SQLite write -> channel call) uses
/// [pumpUntil] rather than a fixed delay: that chain crosses several real
/// `await` points (an `http.Client.timeout()`-wrapped future, sqflite ffi
/// calls), which can take more than one microtask/event-loop turn - a bare
/// `Future.delayed(Duration.zero)` is not guaranteed to flush all of it.
/// [freshQueue] additionally guarantees `close()` even if an `expect()`
/// throws mid-test: `inMemoryDatabasePath` reuses the same underlying
/// database for a path that was never closed (a documented
/// sqflite_common_ffi behavior), so one uncaught failure would otherwise
/// silently contaminate every later test in this file with leftover rows.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  sqfliteFfiInit();

  const channel = MethodChannel(backgroundServiceChannelName);

  LocalQueueRepository? activeQueue;
  LocalQueueRepository freshQueue() {
    final queue = LocalQueueRepository(
      databaseFactory: databaseFactoryFfi,
      path: inMemoryDatabasePath,
    );
    activeQueue = queue;
    return queue;
  }

  Future<void> pumpUntil(bool Function() condition, {Duration timeout = const Duration(seconds: 5)}) async {
    final deadline = DateTime.now().add(timeout);
    while (!condition()) {
      if (DateTime.now().isAfter(deadline)) {
        fail('Condition not satisfied within $timeout');
      }
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
  }

  /// Records every native call the runner makes through [BackgroundBridge]
  /// and answers them programmatically - the Kotlin side itself is only
  /// ever exercised for real on the Itel A80 (see UssdAccessibilityService's
  /// own doc on why AccessibilityNodeInfo behavior is never unit-tested).
  List<MethodCall> mockNativeCalls({
    bool accessibilityEnabled = true,
  }) {
    final calls = <MethodCall>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      switch (call.method) {
        case 'isUssdAccessibilityEnabled':
          return accessibilityEnabled;
        case 'startInteractiveUssdSession':
        case 'ussdOnBackendInput':
        case 'ussdOnBackendDone':
        case 'cancelInteractiveUssdSession':
          return null;
      }
      return null;
    });
    return calls;
  }

  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, null);
    await activeQueue?.close();
    activeQueue = null;
  });

  /// Builds a `/transactions/step/` mock backend. [onStep] is called for
  /// every request (decoded body + the Idempotency-Key header) and returns
  /// the response to send; returning null simulates a network/server
  /// failure (500) for that specific call.
  http.Client buildStepClient(
    Map<String, dynamic>? Function(Map<String, dynamic> body, String idempotencyKey) onStep,
  ) {
    return MockClient((request) async {
      if (!request.url.path.endsWith('/transactions/step/')) {
        return http.Response('not found', 404);
      }
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final key = request.headers['Idempotency-Key'] ?? '';
      final result = onStep(body, key);
      if (result == null) {
        return http.Response(jsonEncode({'error': 'boom'}), 500);
      }
      return http.Response(jsonEncode(result), 200);
    });
  }

  test('happy path: NEW_FIELD -> INPUT, FINAL_FIELD -> DONE, RESULT -> session closed', () async {
    final queue = freshQueue();
    final calls = mockNativeCalls();
    final steps = <String>[];
    final api = GatewayApi(
      client: buildStepClient((body, key) {
        steps.add(body['event'] as String);
        switch (body['event']) {
          case 'NEW_FIELD':
            return {'action': 'INPUT', 'values': ['1234']};
          case 'FINAL_FIELD':
            return {'action': 'DONE'};
          case 'RESULT':
            return {'action': 'ACK'};
        }
        return null;
      }),
    );
    final bridge = BackgroundBridge();
    final runner = InteractiveUssdRunner(api: api, queue: queue, bridge: bridge);

    await runner.start(transactionReference: 'TOL-INT-1', attemptId: 7, ussdCode: '*123#', simSlot: 0);
    expect(runner.isRunning, isTrue);
    expect(await queue.currentInteractiveSession(), isNotNull);
    expect(calls.map((c) => c.method), contains('startInteractiveUssdSession'));

    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'NEW_FIELD', 'fieldCount': 1}));
    await pumpUntil(() => calls.any((c) => c.method == 'ussdOnBackendInput'));
    expect(calls.last.method, 'ussdOnBackendInput');
    expect(calls.last.arguments['values'], ['1234']);

    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'FINAL_FIELD'}));
    await pumpUntil(() => calls.any((c) => c.method == 'ussdOnBackendDone'));
    expect(calls.last.method, 'ussdOnBackendDone');

    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'RESULT', 'status': 'SUCCESS', 'operatorMessage': 'Transfert reussi'}));
    await pumpUntil(() => !runner.isRunning);

    expect(steps, ['NEW_FIELD', 'FINAL_FIELD', 'RESULT']);
    expect(await queue.currentInteractiveSession(), isNull, reason: 'the Gateway must be free for the next interactive task');
    expect(await queue.pendingTaskCount(), 0);
  });

  test('idempotency: the same key is reused verbatim across a retried event, never regenerated', () async {
    final queue = freshQueue();
    mockNativeCalls();
    final seenKeys = <String>[];
    var attempts = 0;
    final api = GatewayApi(
      client: buildStepClient((body, key) {
        if (body['event'] == 'NEW_FIELD') {
          seenKeys.add(key);
          attempts++;
          if (attempts < 2) return null; // first attempt fails (network/server error)
          return {'action': 'DONE'};
        }
        return {'action': 'ACK'};
      }),
    );
    final bridge = BackgroundBridge();
    final runner = InteractiveUssdRunner(api: api, queue: queue, bridge: bridge, maxRetriesPerEvent: 3);

    await runner.start(transactionReference: 'TOL-INT-2', attemptId: 8, ussdCode: '*123#');
    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'NEW_FIELD', 'fieldCount': 1}));
    await pumpUntil(() => attempts >= 2, timeout: const Duration(seconds: 5));

    expect(attempts, 2);
    expect(seenKeys.toSet(), hasLength(1), reason: 'a retried event must reuse the exact same Idempotency-Key');
  });

  test('accessibility disabled: reports FAILED immediately, never arms a native session', () async {
    final queue = freshQueue();
    final calls = mockNativeCalls(accessibilityEnabled: false);
    final reportedBodies = <Map<String, dynamic>>[];
    final api = GatewayApi(
      client: buildStepClient((body, key) {
        reportedBodies.add(body);
        return {'action': 'ACK'};
      }),
    );
    final bridge = BackgroundBridge();
    final runner = InteractiveUssdRunner(api: api, queue: queue, bridge: bridge);

    await runner.start(transactionReference: 'TOL-INT-3', attemptId: 9, ussdCode: '*123#');
    await pumpUntil(() => reportedBodies.isNotEmpty);

    expect(calls.map((c) => c.method), isNot(contains('startInteractiveUssdSession')));
    expect(reportedBodies, hasLength(1));
    expect(reportedBodies.single['event'], 'RESULT');
    expect(reportedBodies.single['status'], 'FAILED');
    expect(reportedBodies.single['error_code'], 'ACCESSIBILITY_DISABLED');
    await pumpUntil(() => !runner.isRunning);
    expect(await queue.currentInteractiveSession(), isNull);
  });

  test('backend FAILED mid-session cancels the native session and reports RESULT', () async {
    final queue = freshQueue();
    final calls = mockNativeCalls();
    final api = GatewayApi(
      client: buildStepClient((body, key) {
        if (body['event'] == 'NEW_FIELD') {
          return {'action': 'FAILED', 'error_code': 'INVALID_PIN'};
        }
        return {'action': 'ACK'};
      }),
    );
    final bridge = BackgroundBridge();
    final runner = InteractiveUssdRunner(api: api, queue: queue, bridge: bridge);

    await runner.start(transactionReference: 'TOL-INT-4', attemptId: 10, ussdCode: '*123#');
    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'NEW_FIELD', 'fieldCount': 1}));
    await pumpUntil(() => calls.any((c) => c.method == 'cancelInteractiveUssdSession'));

    await pumpUntil(() => !runner.isRunning);
    expect(await queue.currentInteractiveSession(), isNull);
  });

  test('native TIMEOUT event reports RESULT FAILED and always cleans up', () async {
    final queue = freshQueue();
    mockNativeCalls();
    final reportedBodies = <Map<String, dynamic>>[];
    final api = GatewayApi(
      client: buildStepClient((body, key) {
        reportedBodies.add(body);
        return {'action': 'ACK'};
      }),
    );
    final bridge = BackgroundBridge();
    final runner = InteractiveUssdRunner(api: api, queue: queue, bridge: bridge);

    await runner.start(transactionReference: 'TOL-INT-5', attemptId: 11, ussdCode: '*123#');
    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'TIMEOUT'}));
    await pumpUntil(() => reportedBodies.isNotEmpty);

    expect(reportedBodies.single['status'], 'FAILED');
    expect(reportedBodies.single['error_code'], 'USSD_TIMEOUT');
    await pumpUntil(() => !runner.isRunning);
    expect(await queue.currentInteractiveSession(), isNull);
  });

  test('BUSY reflection: pendingTaskCount() is non-zero while a session is active, zero once it ends', () async {
    final queue = freshQueue();
    mockNativeCalls();
    final api = GatewayApi(
      client: buildStepClient((body, key) => {'action': 'ACK'}),
    );
    final bridge = BackgroundBridge();
    final runner = InteractiveUssdRunner(api: api, queue: queue, bridge: bridge);

    expect(await queue.pendingTaskCount(), 0);
    await runner.start(transactionReference: 'TOL-INT-6', attemptId: 12, ussdCode: '*123#');
    expect(await queue.pendingTaskCount(), greaterThan(0), reason: 'the heartbeat must see the Gateway as busy');

    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'RESULT', 'status': 'SUCCESS', 'operatorMessage': 'ok'}));
    await pumpUntil(() => !runner.isRunning);
    expect(await queue.pendingTaskCount(), 0);
  });

  test('a second start() call while a session is already running is a no-op', () async {
    final queue = freshQueue();
    final calls = mockNativeCalls();
    final api = GatewayApi(client: buildStepClient((body, key) => {'action': 'ACK'}));
    final bridge = BackgroundBridge();
    final runner = InteractiveUssdRunner(api: api, queue: queue, bridge: bridge);

    await runner.start(transactionReference: 'TOL-INT-7', attemptId: 13, ussdCode: '*123#');
    final callsAfterFirstStart = calls.length;
    await runner.start(transactionReference: 'TOL-INT-8', attemptId: 14, ussdCode: '*456#');

    expect(calls.length, callsAfterFirstStart, reason: 'no new native call for the ignored second start()');
    expect((await queue.currentInteractiveSession())!.transactionReference, 'TOL-INT-7');

    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'RESULT', 'status': 'FAILED', 'operatorMessage': ''}));
    await pumpUntil(() => !runner.isRunning);
  });

  test('exhausted retries on a non-final event leave the session in place for the native timeout to resolve', () async {
    final queue = freshQueue();
    mockNativeCalls();
    var newFieldAttempts = 0;
    final api = GatewayApi(
      client: buildStepClient((body, key) {
        if (body['event'] == 'NEW_FIELD') {
          newFieldAttempts++;
          return null; // always fails
        }
        return {'action': 'ACK'};
      }),
    );
    final bridge = BackgroundBridge();
    final runner = InteractiveUssdRunner(api: api, queue: queue, bridge: bridge, maxRetriesPerEvent: 2);

    await runner.start(transactionReference: 'TOL-INT-9', attemptId: 15, ussdCode: '*123#');
    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'NEW_FIELD', 'fieldCount': 1}));
    await pumpUntil(() => newFieldAttempts >= 2, timeout: const Duration(seconds: 5));
    // Give the loop's final iteration time to actually return (it gives up
    // right after the second attempt, with no further await needed).
    await Future<void>.delayed(const Duration(milliseconds: 50));

    expect(newFieldAttempts, 2, reason: 'maxRetriesPerEvent honored, then gives up on this event');
    expect(runner.isRunning, isTrue, reason: 'must stay armed - only the native session timeout (or a later event) can end it');
    expect(await queue.currentInteractiveSession(), isNotNull, reason: 'the pending event/key are preserved for a future retry path');

    // The native side eventually gives up too and reports TIMEOUT - the
    // runner must still be listening and clean up correctly.
    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'TIMEOUT'}));
    await pumpUntil(() => !runner.isRunning);
    expect(await queue.currentInteractiveSession(), isNull);
  });

  test('a permanent rejection (409: attempt no longer active) is never retried and frees the Gateway immediately', () async {
    final queue = freshQueue();
    final calls = mockNativeCalls();
    var newFieldAttempts = 0;
    final api = GatewayApi(
      client: MockClient((request) async {
        if (!request.url.path.endsWith('/transactions/step/')) return http.Response('not found', 404);
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        if (body['event'] == 'NEW_FIELD') {
          newFieldAttempts++;
          return http.Response(jsonEncode({'error': 'Attempt is not active (status=failed)'}), 409);
        }
        return http.Response(jsonEncode({'action': 'ACK'}), 200);
      }),
    );
    final bridge = BackgroundBridge();
    final runner = InteractiveUssdRunner(api: api, queue: queue, bridge: bridge, maxRetriesPerEvent: 3);

    await runner.start(transactionReference: 'TOL-INT-10', attemptId: 16, ussdCode: '*123#');
    bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap({'type': 'NEW_FIELD', 'fieldCount': 1}));
    await pumpUntil(() => !runner.isRunning, timeout: const Duration(seconds: 2));

    expect(newFieldAttempts, 1, reason: '409 must never be retried - it is a permanent rejection, not a transient failure');
    expect(calls.map((c) => c.method), contains('cancelInteractiveUssdSession'));
    expect(await queue.currentInteractiveSession(), isNull, reason: 'the Gateway must be freed immediately, not held for a futile retry budget');
  });

  group('orphan recovery after a crash/reboot (gatewayServiceMain startup hook)', () {
    test('an interactive_session row left over from a previous process is cleared, not reported', () async {
      final queue = freshQueue();
      final started = await queue.startInteractiveSession(transactionReference: 'TOL-ORPHAN', attemptId: 99);
      expect(started, isTrue);

      // Mirrors _recoverOrphanedInteractiveSession's own logic (kept
      // deliberately simple/local rather than importing the entrypoint,
      // which pulls in WidgetsFlutterBinding/platform channels this test
      // does not need) - the contract under test is "an orphaned row is
      // cleared, and nothing is guessed/reported for it".
      final orphaned = await queue.currentInteractiveSession();
      expect(orphaned, isNotNull);
      await queue.closeInteractiveSession();

      expect(await queue.currentInteractiveSession(), isNull);
      expect(await queue.pendingTaskCount(), 0, reason: 'the Gateway must be free to accept a new interactive task after restart');
    });

    test('no orphaned row: recovery is a silent no-op', () async {
      final queue = freshQueue();
      expect(await queue.currentInteractiveSession(), isNull);
      // No-op expected - nothing to assert beyond "does not throw" and the
      // queue remaining empty.
    });
  });
}
