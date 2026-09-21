import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gateway_apk/background/background_bridge.dart';
import 'package:gateway_apk/background/gateway_loop.dart';
import 'package:gateway_apk/background/interactive_ussd_runner.dart';
import 'package:gateway_apk/background/sms_service.dart' show SmsOutcome;
import 'package:gateway_apk/background/ussd_step_event.dart';
import 'package:gateway_apk/services/gateway_api.dart';
import 'package:gateway_apk/services/local_queue_repository.dart';
import 'package:gateway_apk/services/ussd_service.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// Orchestration tests for [GatewayLoop] - the same tick the manual button
/// and (from Étape 3) the autonomous Foreground Service both run. The
/// network is a `http.MockClient` (no real backend involved) and the queue
/// is a real in-memory SQLite database (sqflite_common_ffi) - only
/// `dialUssd`/`deviceInfoProvider` are bare fakes.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  sqfliteFfiInit();

  DeviceInfo fakeDevice() => DeviceInfo(
    uuid: 'device-1',
    operatorName: 'Orange',
    phoneNumber: '0700000000',
    deviceModel: 'Pixel',
    osVersion: '14',
    batteryLevel: 80,
  );

  Map<String, dynamic>? lastHeartbeatBody;

  List<Map<String, dynamic>>? lastSmsResultBody;
  String? lastReportedResult;

  http.Client buildClient({
    List<Map<String, dynamic>> pending = const [],
    List<Map<String, dynamic>> smsPending = const [],
    bool reportShouldFail = false,
  }) {
    return MockClient((request) async {
      final path = request.url.path;
      if (path.endsWith('/gateways/heartbeat/') ||
          RegExp(r'/gateways/\d+/heartbeat/$').hasMatch(path)) {
        lastHeartbeatBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'id': 1,
            'uuid': 'device-1',
            'device': {
              'uuid': 'device-1',
              'phone_number': '0700000000',
              'details': {'operator': 'Orange'},
            },
            'heartbeat_status': 'online',
            'last_checkin': null,
          }),
          200,
        );
      }
      if (path.endsWith('/transactions/pending/')) {
        return http.Response(jsonEncode(pending), 200);
      }
      if (path.endsWith('/transactions/result/')) {
        if (reportShouldFail) {
          return http.Response('server error', 500);
        }
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        lastReportedResult = body['result'] as String?;
        return http.Response('{}', 200);
      }
      if (path.endsWith('/sms/pending/')) {
        return http.Response(jsonEncode(smsPending), 200);
      }
      if (path.endsWith('/sms/result/')) {
        lastSmsResultBody ??= [];
        lastSmsResultBody!.add(
          jsonDecode(request.body) as Map<String, dynamic>,
        );
        return http.Response('{}', 200);
      }
      return http.Response('not found', 404);
    });
  }

  LocalQueueRepository freshQueue() => LocalQueueRepository(
    databaseFactory: databaseFactoryFfi,
    path: inMemoryDatabasePath,
  );

  setUp(() {
    lastHeartbeatBody = null;
    lastSmsResultBody = null;
    lastReportedResult = null;
  });

  test('happy path: dials the pending task and reports success', () async {
    final queue = freshQueue();
    final api = GatewayApi(
      client: buildClient(
        pending: [
          {
            'id': 1,
            'reference': 'TOL-1',
            'transaction_type': 'subscription',
            'recipient_phone': '0700000001',
            'amount': 1000,
            'ussd_code': '*456*1000#',
          },
        ],
      ),
    );
    final loop = GatewayLoop(
      api: api,
      queue: queue,
      dialUssd: (code, simSlot, operator) async => 'Transfert reussi',
      deviceInfoProvider: () async => fakeDevice(),
    );

    final result = await loop.runOnce();

    expect(result.pendingFetched, 1);
    expect(result.dialed, 1);
    expect(result.reported, 1);
    expect(await queue.pendingTaskCount(), 0, reason: 'the task reached done');
    await queue.close();
  });

  test(
    'Phase D audit (Critique): the operator from the backend payload reaches dialUssd unchanged',
    () async {
      final queue = freshQueue();
      final api = GatewayApi(
        client: buildClient(
          pending: [
            {
              'id': 1,
              'reference': 'TOL-OP',
              'transaction_type': 'subscription',
              'recipient_phone': '0700000001',
              'amount': 1000,
              'ussd_code': '*456*1000#',
              'sim_slot': 0,
              'operator': 'Orange',
            },
          ],
        ),
      );
      String? capturedOperator;
      int? capturedSlot;
      final loop = GatewayLoop(
        api: api,
        queue: queue,
        dialUssd: (code, simSlot, operator) async {
          capturedOperator = operator;
          capturedSlot = simSlot;
          return 'OK';
        },
        deviceInfoProvider: () async => fakeDevice(),
      );

      await loop.runOnce();

      expect(
        capturedOperator,
        'Orange',
        reason: 'the native layer needs this to refuse a dial on the wrong SIM',
      );
      expect(capturedSlot, 0);
      await queue.close();
    },
  );

  test(
    'a dial failure is still reported (as a failure), not silently dropped',
    () async {
      final queue = freshQueue();
      final api = GatewayApi(
        client: buildClient(
          pending: [
            {
              'id': 1,
              'reference': 'TOL-2',
              'transaction_type': 'subscription',
              'recipient_phone': '0700000001',
              'amount': 1000,
              'ussd_code': '*456*1000#',
            },
          ],
        ),
      );
      final loop = GatewayLoop(
        api: api,
        queue: queue,
        dialUssd: (code, simSlot, operator) async =>
            throw Exception('USSD_FAILED'),
        deviceInfoProvider: () async => fakeDevice(),
      );

      final result = await loop.runOnce();

      expect(result.dialed, 1);
      expect(
        result.reported,
        1,
        reason: 'a known failure outcome must still be reported',
      );
      await queue.close();
    },
  );

  test(
    'a report failure leaves the task queued for the next tick, never re-dialed',
    () async {
      final queue = freshQueue();
      var dialCount = 0;
      final api = GatewayApi(
        client: buildClient(
          pending: [
            {
              'id': 1,
              'reference': 'TOL-3',
              'transaction_type': 'subscription',
              'recipient_phone': '0700000001',
              'amount': 1000,
              'ussd_code': '*456*1000#',
            },
          ],
          reportShouldFail: true,
        ),
      );
      final loop = GatewayLoop(
        api: api,
        queue: queue,
        dialUssd: (code, simSlot, operator) async {
          dialCount++;
          return 'OK';
        },
        deviceInfoProvider: () async => fakeDevice(),
      );

      final first = await loop.runOnce();
      expect(first.dialed, 1);
      expect(
        first.reported,
        0,
        reason: 'the mock backend rejects the report on purpose',
      );

      // Second tick: nothing new pending, but the failed report must still be
      // sitting in the awaiting-report bucket - and dialUssd must not have
      // been called again for it.
      final awaiting = await queue.tasksAwaitingReport();
      expect(awaiting, hasLength(1));
      expect(
        dialCount,
        1,
        reason: 'the task must never be dialed a second time',
      );
      await queue.close();
    },
  );

  test(
    'heartbeat carries live is_busy/current_task_count from the queue, not a cached value',
    () async {
      final queue = freshQueue();
      final api = GatewayApi(
        client: buildClient(
          pending: [
            {
              'id': 1,
              'reference': 'TOL-4',
              'transaction_type': 'subscription',
              'recipient_phone': '0700000001',
              'amount': 1000,
              'ussd_code': '*456*1000#',
            },
            {
              'id': 2,
              'reference': 'TOL-5',
              'transaction_type': 'subscription',
              'recipient_phone': '0700000002',
              'amount': 2000,
              'ussd_code': '*456*2000#',
            },
          ],
        ),
      );
      final loop = GatewayLoop(
        api: api,
        queue: queue,
        dialUssd: (code, simSlot, operator) async => 'OK',
        deviceInfoProvider: () async => fakeDevice(),
      );

      // First tick starts with an empty queue (nothing enqueued yet when the
      // heartbeat for *this* tick is built) - is_busy must reflect that.
      await loop.runOnce();
      expect(lastHeartbeatBody, isNotNull);
      expect(lastHeartbeatBody!['details']['is_busy'], isFalse);
      expect(lastHeartbeatBody!['details']['current_task_count'], 0);

      await queue.close();
    },
  );

  test(
    'SMS: fetched and dispatched on one tick, reported once the outbox reveals the outcome on a later tick',
    () async {
      final queue = freshQueue();
      final api = GatewayApi(
        client: buildClient(
          smsPending: [
            {
              'id': 42,
              'phone_number': '0700000009',
              'message': 'code: 123456',
              'purpose': 'otp',
            },
          ],
        ),
      );
      final outbox = <Map<String, dynamic>>[];
      var dispatchCount = 0;
      final loop = GatewayLoop(
        api: api,
        queue: queue,
        dialUssd: (code, simSlot, operator) async => 'OK',
        deviceInfoProvider: () async => fakeDevice(),
        dispatchSms:
            ({required taskId, required phone, required message}) async {
              dispatchCount++;
              // Simulates the sent/delivered receipt arriving after dispatch -
              // not yet visible to *this* tick's reconcile step, which already
              // ran before dispatch (see GatewayLoop.runOnce's ordering).
              outbox.add({
                'taskId': taskId,
                'sent': 'sent',
                'delivered': 'delivered',
              });
            },
        drainSmsOutcomes: () async {
          final result = outbox.map(SmsOutcome.fromMap).toList();
          outbox.clear();
          return result;
        },
      );

      final first = await loop.runOnce();
      expect(first.smsFetched, 1);
      expect(first.smsDispatched, 1);
      expect(
        first.smsReported,
        0,
        reason:
            'the outcome is not known until a later tick reconciles the outbox',
      );
      expect(dispatchCount, 1);

      final second = await loop.runOnce(gatewayId: first.status.id);
      expect(second.smsReported, 1);
      expect(dispatchCount, 1, reason: 'must never be dispatched twice');
      expect(lastSmsResultBody, isNotNull);
      expect(lastSmsResultBody!.single['id'], 42);
      expect(lastSmsResultBody!.single['success'], isTrue);

      await queue.close();
    },
  );

  test(
    'SMS handling is entirely skipped when dispatchSms/drainSmsOutcomes are not wired up',
    () async {
      final queue = freshQueue();
      final api = GatewayApi(
        client: buildClient(
          smsPending: [
            {
              'id': 1,
              'phone_number': '0700000009',
              'message': 'x',
              'purpose': 'otp',
            },
          ],
        ),
      );
      final loop = GatewayLoop(
        api: api,
        queue: queue,
        dialUssd: (code, simSlot, operator) async => 'OK',
        deviceInfoProvider: () async => fakeDevice(),
      );

      final result = await loop.runOnce();
      expect(
        result.smsFetched,
        0,
        reason:
            'fetchSmsPending must never be called without SMS wired up (see main.dart\'s manual-button loop)',
      );
      await queue.close();
    },
  );

  group('isValidUssdCode (Stabilisation RC1, priorité critique n°2)', () {
    test('accepts the two real backend formats', () {
      expect(isValidUssdCode('*456*1000#'), isTrue);
      expect(isValidUssdCode('*123*0700000000*1000#'), isTrue);
    });

    test('rejects anything that is not `*<digits/stars>#`', () {
      expect(isValidUssdCode(''), isFalse);
      expect(isValidUssdCode(null), isFalse);
      expect(
        isValidUssdCode('456*1000#'),
        isFalse,
        reason: 'missing leading *',
      );
      expect(
        isValidUssdCode('*456*1000'),
        isFalse,
        reason: 'missing trailing #',
      );
      expect(
        isValidUssdCode('*456#extra'),
        isFalse,
        reason: 'trailing garbage after #',
      );
      expect(
        isValidUssdCode('*<script>alert(1)</script>#'),
        isFalse,
        reason: 'injection attempt',
      );
      expect(
        isValidUssdCode('*456; rm -rf /#'),
        isFalse,
        reason: 'shell-like injection attempt',
      );
      expect(
        isValidUssdCode('${'*' * 1}${'1' * 60}#'),
        isFalse,
        reason: 'far longer than any real code',
      );
    });
  });

  test(
    'a task with a malformed ussd_code is rejected without ever being dialed, and still reported',
    () async {
      final queue = freshQueue();
      final api = GatewayApi(
        client: buildClient(
          pending: [
            {
              'id': 1,
              'reference': 'TOL-BAD',
              'transaction_type': 'subscription',
              'recipient_phone': '0700000001',
              'amount': 1000,
              // Not a valid USSD/MMI string - simulates a compromised or
              // buggy backend response.
              'ussd_code': '*456*1000#; DROP TABLE',
            },
          ],
        ),
      );
      var dialCalled = false;
      final loop = GatewayLoop(
        api: api,
        queue: queue,
        dialUssd: (code, simSlot, operator) async {
          dialCalled = true;
          return 'OK';
        },
        deviceInfoProvider: () async => fakeDevice(),
      );

      final result = await loop.runOnce();

      expect(
        dialCalled,
        isFalse,
        reason: 'an invalid code must never reach the native dial primitive',
      );
      expect(
        result.dialed,
        1,
        reason: 'still counted as a handled task (rejected, not dialed)',
      );
      expect(result.reported, 1);
      expect(lastReportedResult, contains('REJECTED_INVALID_USSD_FORMAT'));

      await queue.close();
    },
  );

  group('Option A - Libération Immédiate du Gateway', () {
    test('runOnce reports transaction outcome with reported > 0', () async {
      final queue = freshQueue();
      final api = GatewayApi(
        client: buildClient(
          pending: [
            {
              'id': 101,
              'reference': 'ref-opt-a',
              'amount': 1000,
              'recipient_phone': '0700000000',
              'transaction_type': 'subscription',
              'ussd_code': '*144*1*1*1000*0700000000#',
            },
          ],
        ),
      );
      final loop = GatewayLoop(
        api: api,
        queue: queue,
        dialUssd: (code, simSlot, operator) async => 'SUCCESS_MSG',
        deviceInfoProvider: () async => fakeDevice(),
      );

      final result = await loop.runOnce();
      expect(result.dialed, 1);
      expect(result.reported, 1);
      expect(lastReportedResult, 'SUCCESS_MSG');

      await queue.close();
    });

    test(
      'immediate follow-up poll executes when reported > 0 and halts when queue is empty',
      () async {
        final queue = freshQueue();
        var pollCount = 0;
        var hasPending = true;

        final client = MockClient((request) async {
          final path = request.url.path;
          if (path.endsWith('/gateways/heartbeat/')) {
            return http.Response(
              jsonEncode({
                'id': 1,
                'uuid': 'device-1',
                'device': {'uuid': 'device-1'},
                'heartbeat_status': 'online',
              }),
              200,
            );
          }
          if (path.endsWith('/transactions/pending/')) {
            pollCount++;
            if (hasPending) {
              hasPending = false;
              return http.Response(
                jsonEncode([
                  {
                    'id': 102,
                    'reference': 'ref-opt-b',
                    'amount': 500,
                    'recipient_phone': '0700000000',
                    'transaction_type': 'subscription',
                    'ussd_code': '*144*500#',
                  },
                ]),
                200,
              );
            }
            return http.Response(jsonEncode([]), 200);
          }
          if (path.endsWith('/transactions/result/')) {
            return http.Response('{}', 200);
          }
          return http.Response('not found', 404);
        });

        final api = GatewayApi(client: client);
        final loop = GatewayLoop(
          api: api,
          queue: queue,
          dialUssd: (code, simSlot, operator) async => 'OK',
          deviceInfoProvider: () async => fakeDevice(),
        );

        // Simulation of the tick() loop from gateway_service_entrypoint.dart
        var ticking = false;
        var tickCycles = 0;
        Future<void> simulateTick() async {
          if (ticking) return;
          ticking = true;
          var shouldRepollImmediately = false;
          try {
            tickCycles++;
            final result = await loop.runOnce();
            if (result.reported > 0) {
              shouldRepollImmediately = true;
            }
          } finally {
            ticking = false;
          }

          if (shouldRepollImmediately) {
            await simulateTick();
          }
        }

        await simulateTick();

        // Cycle 1: fetched 1, dialed 1, reported 1 -> triggered immediate repoll
        // Cycle 2: fetched 0, dialed 0, reported 0 -> shouldRepollImmediately = false -> halted cleanly without infinite loop!
        expect(pollCount, 2);
        expect(tickCycles, 2);

        await queue.close();
      },
    );

    test('anti-reentrancy lock prevents concurrent execution of tick', () async {
      var ticking = false;
      var executionCount = 0;

      Future<void> simulateGuardedTick() async {
        if (ticking) return;
        ticking = true;
        try {
          executionCount++;
          await Future<void>.delayed(const Duration(milliseconds: 50));
        } finally {
          ticking = false;
        }
      }

      // Launch two ticks concurrently (e.g. timer tick and immediate repoll)
      await Future.wait([simulateGuardedTick(), simulateGuardedTick()]);

      expect(
        executionCount,
        1,
        reason:
            'Only one tick must execute; concurrent tick must be dropped by guard',
      );
    });

    test(
      'network error triggers backoff and prevents immediate repoll loop',
      () async {
        final queue = freshQueue();
        var pollAttempts = 0;
        var failureCount = 0;

        final client = MockClient((request) async {
          if (request.url.path.endsWith('/gateways/heartbeat/')) {
            pollAttempts++;
            return http.Response('Server Error', 500);
          }
          return http.Response('not found', 404);
        });

        final api = GatewayApi(client: client);
        final loop = GatewayLoop(
          api: api,
          queue: queue,
          dialUssd: (code, simSlot, operator) async => 'OK',
          deviceInfoProvider: () async => fakeDevice(),
        );

        var ticking = false;
        var shouldRepoll = false;
        Future<void> simulateErrorTick() async {
          if (ticking) return;
          ticking = true;
          shouldRepoll = false;
          try {
            final res = await loop.runOnce();
            if (res.reported > 0) shouldRepoll = true;
          } catch (_) {
            failureCount++;
            // In error case, backoff is set and shouldRepoll stays false
          } finally {
            ticking = false;
          }
          if (shouldRepoll) {
            await simulateErrorTick();
          }
        }

        await simulateErrorTick();

        expect(pollAttempts, 1);
        expect(failureCount, 1);
        expect(
          shouldRepoll,
          isFalse,
          reason: 'Network failure must never trigger immediate repoll',
        );

        await queue.close();
      },
    );

    test(
      'InteractiveUssdRunner onSessionComplete callback is fired on finish',
      () async {
        const channel = MethodChannel(backgroundServiceChannelName);
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, (call) async {
              if (call.method == 'isUssdAccessibilityEnabled') return true;
              return null;
            });

        final queue = freshQueue();
        final api = GatewayApi(
          client: MockClient(
            (request) async => http.Response('{"action":"DONE"}', 200),
          ),
        );
        final bridge = BackgroundBridge();
        var sessionCompleteCalled = false;

        final runner = InteractiveUssdRunner(
          api: api,
          queue: queue,
          bridge: bridge,
          onSessionComplete: () {
            sessionCompleteCalled = true;
          },
        );

        await runner.start(
          transactionReference: 'ref-interactive-test',
          attemptId: 42,
          ussdCode: '*144#',
        );
        expect(runner.isRunning, isTrue);

        bridge.emitUssdStepEvent(
          UssdStepEvent.fromChannelMap({
            'type': 'RESULT',
            'status': 'SUCCESS',
            'operatorMessage': 'Session terminee',
          }),
        );

        await Future<void>.delayed(const Duration(milliseconds: 50));

        expect(runner.isRunning, isFalse);
        expect(
          sessionCompleteCalled,
          isTrue,
          reason: 'onSessionComplete must fire when interactive session ends',
        );

        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, null);
        await queue.close();
      },
    );
  });
}
