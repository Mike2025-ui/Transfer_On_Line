import 'dart:async';
import 'dart:developer' as developer;

import '../services/gateway_api.dart';
import '../services/local_queue_repository.dart';
import 'background_bridge.dart';
import 'ussd_step_event.dart';

/// Phase D4.3: orchestrates one interactive USSD session end to end -
/// NEW_FIELD/FINAL_FIELD/RESULT relayed to the Backend via
/// [GatewayApi.sendTransactionStep], INPUT/DONE relayed back to
/// [UssdAccessibilityService] via [BackgroundBridge]. Deliberately its own
/// independent async chain, never awaited by `gateway_service_entrypoint.dart`'s
/// tick/heartbeat loop (see that file's doc) - a session lasting far longer
/// than one tick interval must never delay the next heartbeat.
///
/// The Backend remains the sole decision-maker: this class never invents a
/// value, never decides SUCCESS/FAILED itself, and never advances past what
/// [UssdAccessibilityService] actually reports.
class InteractiveUssdRunner {
  InteractiveUssdRunner({
    required this.api,
    required this.queue,
    required this.bridge,
    this.maxRetriesPerEvent = 3,
  });

  final GatewayApi api;
  final LocalQueueRepository queue;
  final BackgroundBridge bridge;
  final int maxRetriesPerEvent;

  /// 401 (bad/missing X-Gateway-Secret), 403 (this Gateway does not own the
  /// attempt), 409 (attempt no longer active/conflict) - TransactionStepView's
  /// own error matrix (apps.devices.views). None of these are transient: the
  /// Backend has made a final decision, so retrying only delays freeing the
  /// Gateway. Only left as retryable: network failures/timeouts and 5xx.
  static const _permanentStatusCodes = {401, 403, 409};

  StreamSubscription<UssdStepEvent>? _subscription;
  bool _running = false;

  bool get isRunning => _running;

  Future<void> start({
    required String transactionReference,
    required int attemptId,
    required String ussdCode,
    int? simSlot,
  }) async {
    if (_running) return; // one interactive session at a time on this Gateway
    _running = true;
    try {
      final started = await queue.startInteractiveSession(
        transactionReference: transactionReference,
        attemptId: attemptId,
      );
      if (!started) {
        // The local singleton constraint refused it - should not happen if
        // the Backend's own Gateway-exclusivity holds, but never silently
        // proceed as if a session were armed when it is not.
        developer.log(
          'startInteractiveSession refused - a session row already exists locally',
          name: 'InteractiveUssdRunner',
        );
        _running = false;
        return;
      }

      _subscription = bridge.ussdStepEvents.listen(
        (event) => _handleEvent(transactionReference, attemptId, event),
      );

      final enabled = await bridge.isUssdAccessibilityEnabled();
      if (!enabled) {
        await _reportResultAndFinish(
          transactionReference, attemptId,
          status: 'FAILED', operatorMessage: '', errorCode: 'ACCESSIBILITY_DISABLED',
        );
        return;
      }

      await bridge.startInteractiveUssdSession(code: ussdCode, simSlot: simSlot);
    } catch (error) {
      await _reportResultAndFinish(
        transactionReference, attemptId,
        status: 'FAILED', operatorMessage: '', errorCode: 'ACTION_CALL_FAILED',
      );
    }
  }

  Future<void> _handleEvent(String reference, int attemptId, UssdStepEvent event) async {
    switch (event.type) {
      case UssdStepEventType.newField:
        await _reportStepAndRespond(reference, attemptId, event: 'NEW_FIELD', fieldCount: event.fieldCount);
      case UssdStepEventType.finalField:
        await _reportStepAndRespond(reference, attemptId, event: 'FINAL_FIELD');
      case UssdStepEventType.result:
        await _reportResultAndFinish(
          reference, attemptId, status: event.status ?? 'FAILED', operatorMessage: event.operatorMessage ?? '',
        );
      case UssdStepEventType.failed:
        await _reportResultAndFinish(
          reference, attemptId, status: 'FAILED', operatorMessage: '', errorCode: event.errorCode,
        );
      case UssdStepEventType.timeout:
        await _reportResultAndFinish(
          reference, attemptId, status: 'FAILED', operatorMessage: '', errorCode: 'USSD_TIMEOUT',
        );
    }
  }

  /// NEW_FIELD/FINAL_FIELD: report to the Backend, then relay its decision
  /// back to AccessibilityService. The Idempotency-Key is generated once
  /// and persisted BEFORE the HTTP call, then reused verbatim across every
  /// retry of this exact event - never regenerated (Phase C/D2 invariant).
  Future<void> _reportStepAndRespond(
    String reference, int attemptId, {required String event, int? fieldCount,
  }) async {
    final key = generateIdempotencyKey();
    await queue.recordPendingStepEvent(
      event: event,
      idempotencyKey: key,
      payload: '{"event":"$event"${fieldCount != null ? ',"field_count":$fieldCount' : ''}}',
    );

    TransactionStepResponse? response;
    for (var attempt = 1; attempt <= maxRetriesPerEvent; attempt++) {
      try {
        response = await api.sendTransactionStep(
          transactionReference: reference,
          attemptId: attemptId,
          event: event,
          idempotencyKey: key,
          fieldCount: fieldCount,
        );
        break;
      } on TransactionStepException catch (error) {
        if (_permanentStatusCodes.contains(error.statusCode)) {
          // 401/403/409: the Backend has definitively rejected this
          // Gateway/attempt pairing (bad auth, wrong Gateway, or the
          // attempt already moved on) - retrying can never succeed, and
          // there is no RESULT worth reporting for an attempt the Backend
          // itself says is not ours/not active. Free the Gateway now
          // rather than burn the retry budget on a permanent error.
          developer.log('sendTransactionStep($event) permanently rejected ($error) - abandoning', name: 'InteractiveUssdRunner');
          await bridge.cancelInteractiveUssdSession();
          await _finish();
          return;
        }
        if (attempt == maxRetriesPerEvent) {
          developer.log('sendTransactionStep($event) failed after $maxRetriesPerEvent attempts: $error', name: 'InteractiveUssdRunner');
          return;
        }
        await Future<void>.delayed(Duration(seconds: attempt));
      } catch (error) {
        if (attempt == maxRetriesPerEvent) {
          // Network exhausted - the session-level timeouts already running
          // on the native side (UssdTimeouts) remain the backstop; nothing
          // more to do locally than give up this event.
          developer.log('sendTransactionStep($event) failed after $maxRetriesPerEvent attempts: $error', name: 'InteractiveUssdRunner');
          return;
        }
        await Future<void>.delayed(Duration(seconds: attempt));
      }
    }
    if (response == null) return;

    await queue.recordStepResponse(
      '{"action":"${response.action}"${response.status != null ? ',"status":"${response.status}"' : ''}}',
    );

    switch (response.action) {
      case 'INPUT':
        await bridge.sendUssdBackendInput(response.values ?? const []);
      case 'DONE':
        await bridge.sendUssdBackendDone();
      case 'FAILED':
        await bridge.cancelInteractiveUssdSession();
        await _reportResultAndFinish(
          reference, attemptId, status: 'FAILED', operatorMessage: '', errorCode: response.errorCode ?? 'BACKEND_FAILED',
        );
      default:
        developer.log('Unrecognized step action "${response.action}"', name: 'InteractiveUssdRunner');
    }
  }

  Future<void> _reportResultAndFinish(
    String reference, int attemptId, {
    required String status,
    required String operatorMessage,
    String? errorCode,
  }) async {
    final key = generateIdempotencyKey();
    await queue.recordPendingStepEvent(
      event: 'RESULT',
      idempotencyKey: key,
      payload: '{"status":"$status"}',
    );
    for (var attempt = 1; attempt <= maxRetriesPerEvent; attempt++) {
      try {
        final response = await api.sendTransactionStep(
          transactionReference: reference,
          attemptId: attemptId,
          event: 'RESULT',
          idempotencyKey: key,
          status: status,
          operatorMessage: operatorMessage,
          errorCode: errorCode,
        );
        await queue.recordStepResponse('{"action":"${response.action}"}');
        break;
      } on TransactionStepException catch (error) {
        if (_permanentStatusCodes.contains(error.statusCode)) {
          developer.log('sendTransactionStep(RESULT) permanently rejected ($error) - abandoning', name: 'InteractiveUssdRunner');
          break;
        }
        if (attempt == maxRetriesPerEvent) {
          developer.log('sendTransactionStep(RESULT) failed after $maxRetriesPerEvent attempts: $error', name: 'InteractiveUssdRunner');
          break;
        }
        await Future<void>.delayed(Duration(seconds: attempt));
      } catch (error) {
        if (attempt == maxRetriesPerEvent) {
          developer.log('sendTransactionStep(RESULT) failed after $maxRetriesPerEvent attempts: $error', name: 'InteractiveUssdRunner');
          break;
        }
        await Future<void>.delayed(Duration(seconds: attempt));
      }
    }
    // A RESULT event always terminates the session locally, regardless of
    // whether the Backend could be told - see [_finish]'s doc: the Gateway
    // must never stay stuck BUSY over a reporting failure.
    await _finish();
  }

  /// Guaranteed cleanup regardless of outcome - the Gateway must return to
  /// AVAILABLE (via the next heartbeat's pendingTaskCount(), see
  /// LocalQueueRepository's doc) even if reporting the result itself failed.
  Future<void> _finish() async {
    try {
      await _subscription?.cancel();
    } finally {
      _subscription = null;
      await queue.closeInteractiveSession();
      _running = false;
    }
  }
}
