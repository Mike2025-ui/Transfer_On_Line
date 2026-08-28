import '../services/gateway_api.dart';
import '../services/local_queue_repository.dart';
import '../services/ussd_service.dart' show DeviceInfo;
import 'sms_service.dart' show SmsOutcome;

/// A GSM USSD/MMI session string is, by specification, `*` followed by one
/// or more `*`-separated numeric segments and terminated by `#` - never
/// letters, whitespace, or any other character. This is the last line of
/// defense before a fully autonomous dial (Stabilisation RC1, priorité
/// critique n°2): the phone used to have a human reading the screen before
/// every composition; now it composes whatever `ussd_code` the backend
/// returns, unattended. Validating the *shape* here cannot detect a
/// semantically wrong-but-well-formed code (e.g. the right grammar, wrong
/// amount) - that trust boundary is the backend/transport (HTTPS, see
/// `GatewayApi.baseUrl`'s doc) - but it does guarantee that a malformed or
/// injected payload (extra characters, a second `#`, control characters, an
/// empty string) can never reach `TelephonyManager.sendUssdRequest`.
/// 40 characters is a generous bound - the two real formats
/// (`build_ussd_code` in `apps/core/serializers.py`) are `*123*<phone>*<amount>#`
/// and `*456*<amount>#`, comfortably under half of that.
final RegExp _ussdCodePattern = RegExp(r'^\*[0-9*]{1,38}#$');

bool isValidUssdCode(String? code) {
  return code != null && _ussdCodePattern.hasMatch(code);
}

/// Outcome of one [GatewayLoop.runOnce] tick - what the caller (a manual
/// button today, the autonomous Foreground Service loop from Étape 3
/// onward) needs to update its own state/UI with.
class TickResult {
  const TickResult({
    required this.status,
    required this.pendingFetched,
    required this.dialed,
    required this.reported,
    this.smsFetched = 0,
    this.smsDispatched = 0,
    this.smsReported = 0,
  });

  final GatewayStatus status;
  final int pendingFetched;
  final int dialed;
  final int reported;
  final int smsFetched;
  final int smsDispatched;
  final int smsReported;
}

/// The one orchestration path for "heartbeat, then work the queue" - used
/// identically by the manual button (one explicit [runOnce] call) and, from
/// Étape 3 onward, by the autonomous Foreground Service (the same
/// [runOnce] on a timer). Written against injected collaborators
/// ([GatewayApi], [LocalQueueRepository], a `dialUssd` function, a
/// device-info provider) precisely so it never needs a real platform
/// channel or network to unit test - see
/// `test/background/gateway_loop_test.dart`. `dialUssd` is a bare function
/// rather than the whole `UssdService` object on purpose: the loop only
/// ever needs "compose this code, give me the response", and a function is
/// trivial to fake in tests without an interface/mock framework.
///
/// [dispatchSms]/[drainSmsOutcomes] are optional: SMS can only ever be sent
/// from within the headless engine (see `SmsService`'s doc - its
/// MethodChannel is only registered by `GatewayForegroundService`, never by
/// `MainActivity`), so the manual-button `GatewayLoop` instance in
/// `main.dart` simply never passes them and SMS handling is skipped
/// entirely for that instance - it was never a manually-triggered feature
/// to begin with.
///
/// Each tick, in order: recover anything left interrupted by a previous
/// crash/kill (both USSD and SMS), send a heartbeat with fresh telemetry
/// (never a cached snapshot from app launch - see [_snapshotFrom]), fetch
/// and enqueue whatever is pending, reconcile any SMS outcomes that arrived
/// since the last tick, then drain every queued dial/dispatch and every
/// result still awaiting a report. Heartbeats are never queued/replayed - a
/// stale telemetry snapshot has no value after a reconnect, so the next
/// tick's heartbeat simply supersedes it.
class GatewayLoop {
  GatewayLoop({
    required this.api,
    required this.queue,
    required this.dialUssd,
    required this.deviceInfoProvider,
    this.dispatchSms,
    this.drainSmsOutcomes,
  });

  final GatewayApi api;
  final LocalQueueRepository queue;
  // Phase D audit (Critique): `operator` lets the native layer refuse to
  // dial when the resolved SIM doesn't actually belong to it (see
  // SimResolver.matchesExpectedOperator) - null is always safe, it just
  // skips that check exactly like before this parameter existed.
  final Future<String> Function(String code, int? simSlot, String? operator) dialUssd;
  final Future<DeviceInfo> Function() deviceInfoProvider;
  final Future<void> Function({required int taskId, required String phone, required String message})? dispatchSms;
  final Future<List<SmsOutcome>> Function()? drainSmsOutcomes;

  bool get _smsEnabled => dispatchSms != null && drainSmsOutcomes != null;

  Future<TickResult> runOnce({int? gatewayId}) async {
    await queue.recoverInterruptedDials();
    if (_smsEnabled) await queue.recoverInterruptedSmsSends();

    final taskCount = await queue.pendingTaskCount();
    final device = await deviceInfoProvider();
    final snapshot = _snapshotFrom(device, taskCount);
    final status = await api.sendHeartbeat(gatewayId, snapshot);

    final pending = await api.fetchPendingTransactions(status.uuid);
    await queue.enqueueTransactionTasks(pending);

    var smsFetched = 0;
    if (_smsEnabled) {
      final smsPending = await api.fetchSmsPending();
      smsFetched = smsPending.length;
      await queue.enqueueSmsTasks(smsPending);
      await _reconcileSmsOutcomes();
    }

    final dialed = await _drainDial();
    final reported = await _drainReport();
    final smsDispatched = _smsEnabled ? await _drainSmsDispatch() : 0;
    final smsReported = _smsEnabled ? await _drainSmsReport(status.uuid) : 0;

    return TickResult(
      status: status,
      pendingFetched: pending.length,
      dialed: dialed,
      reported: reported,
      smsFetched: smsFetched,
      smsDispatched: smsDispatched,
      smsReported: smsReported,
    );
  }

  DeviceSnapshot _snapshotFrom(DeviceInfo device, int taskCount) {
    return DeviceSnapshot(
      uuid: device.uuid,
      operatorName: device.operatorName,
      phoneNumber: device.phoneNumber,
      deviceModel: device.deviceModel,
      osVersion: device.osVersion,
      appVersion: device.appVersion,
      batteryLevel: device.batteryLevel,
      temperature: device.temperature,
      networkType: device.networkType,
      signalStrength: device.signalStrength,
      ipAddress: device.ipAddress,
      ramAvailableMb: device.ramAvailableMb,
      storageAvailableMb: device.storageAvailableMb,
      // Live operational state - meaningless as a cached value, so it's
      // computed fresh here from the queue's current size, never read off
      // the (possibly stale) DeviceInfo passed in.
      isBusy: taskCount > 0,
      currentTaskCount: taskCount,
      sims: device.sims,
    );
  }

  /// Dials every task still `pending_dial`, one at a time. Commits the
  /// `dialing` transition before the platform call (see
  /// [LocalQueueRepository.markDialing]'s doc) so an interruption mid-dial
  /// is recoverable without ever composing the same code twice.
  ///
  /// A task whose `ussd_code` fails [isValidUssdCode] is rejected outright
  /// - never claimed via `markDialing`, never handed to the native dial
  /// primitive at all. It is recorded as a failed outcome (not silently
  /// dropped) so `_drainReport` still tells the backend and RetryManager
  /// can react, exactly as it would for any other dial failure.
  Future<int> _drainDial() async {
    var count = 0;
    while (true) {
      final task = await queue.nextTaskToDial();
      if (task == null) break;
      if (!isValidUssdCode(task.ussdCode)) {
        await queue.markDialed(task.id, success: false, result: 'REJECTED_INVALID_USSD_FORMAT');
        count++;
        continue;
      }
      final claimed = await queue.markDialing(task.id);
      if (!claimed) continue; // a concurrent drain already took it
      try {
        final result = await dialUssd(task.ussdCode, task.simSlot, task.operator);
        await queue.markDialed(task.id, success: true, result: result);
      } catch (error) {
        await queue.markDialed(task.id, success: false, result: error.toString());
      }
      count++;
    }
    return count;
  }

  /// Reports every task whose outcome is known but not yet acknowledged by
  /// the backend. Freely retryable - posting an already-known outcome is
  /// idempotent from the app's point of view - so a failure here (e.g.
  /// offline) just leaves the row for the next tick, never touches the dial
  /// outcome itself.
  Future<int> _drainReport() async {
    final tasks = await queue.tasksAwaitingReport();
    var count = 0;
    for (final task in tasks) {
      try {
        await api.reportTransactionResult(
          reference: task.reference,
          success: task.dialSuccess ?? false,
          result: task.dialResult ?? '',
        );
        await queue.markReported(task.id);
        count++;
      } catch (error) {
        await queue.recordReportFailure(task.id, error.toString());
      }
    }
    return count;
  }

  /// Folds a drain of the native sent/delivered outbox into the local
  /// queue - see `LocalQueueRepository.reconcileSmsOutcomes`'s doc for why
  /// this only ever resolves rows still `sending`.
  Future<void> _reconcileSmsOutcomes() async {
    final outcomes = await drainSmsOutcomes!();
    if (outcomes.isEmpty) return;
    await queue.reconcileSmsOutcomes(
      outcomes
          .map((o) => {'taskId': o.taskId, 'sent': o.sent, 'delivered': o.delivered})
          .toList(),
    );
  }

  /// Dispatches every SMS still `pending_send`. Unlike USSD, a successful
  /// call here does not settle the outcome - that arrives later via
  /// [_reconcileSmsOutcomes]. An exception here means the OS rejected the
  /// send outright (e.g. malformed number) and no sent/delivered receipt
  /// will ever follow, so the outcome is recorded directly instead of
  /// leaving the row stuck in `sending` forever.
  Future<int> _drainSmsDispatch() async {
    var count = 0;
    while (true) {
      final task = await queue.nextSmsToSend();
      if (task == null) break;
      final claimed = await queue.markSmsSending(task.id);
      if (!claimed) continue;
      try {
        await dispatchSms!(taskId: task.id, phone: task.phoneNumber, message: task.message);
      } catch (error) {
        await queue.markSmsResultKnown(task.id, success: false, result: error.toString());
      }
      count++;
    }
    return count;
  }

  Future<int> _drainSmsReport(String gatewayUuid) async {
    final tasks = await queue.smsTasksAwaitingReport();
    var count = 0;
    for (final task in tasks) {
      try {
        await api.reportSmsResult(
          id: task.serverId,
          success: task.sendSuccess ?? false,
          gatewayUuid: gatewayUuid,
        );
        await queue.markSmsReported(task.id);
        count++;
      } catch (error) {
        await queue.recordSmsReportFailure(task.id, error.toString());
      }
    }
    return count;
  }
}
