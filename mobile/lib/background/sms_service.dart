import 'package:flutter/services.dart';

import 'background_bridge.dart' show backgroundServiceChannelName;

/// One outcome drained from the native sent/delivered outbox (see
/// `TelephonyGateway.sendSms`'s doc). `taskId` is the *local*
/// `sms_tasks.id` (not the backend's `SmsTask.id`) - it's what native code
/// was given when [SmsService.dispatch] was called.
class SmsOutcome {
  const SmsOutcome({required this.taskId, this.sent, this.delivered});

  final int taskId;
  final String? sent; // 'sent' | 'failed' | null (not yet known)
  final String? delivered; // 'delivered' | 'not_delivered' | null

  factory SmsOutcome.fromMap(Map<dynamic, dynamic> map) {
    return SmsOutcome(
      taskId: map['taskId'] as int,
      sent: map['sent'] as String?,
      delivered: map['delivered'] as String?,
    );
  }
}

/// SMS half of the headless engine's native bridge - kept as its own class
/// from [BackgroundBridge] (USSD dial + telemetry) for separation of
/// concerns, even though both share the same underlying MethodChannel (see
/// [backgroundServiceChannelName]'s doc): this is the autonomous loop's own
/// bridge, only ever reachable from the background engine
/// [GatewayForegroundService] creates - there is no UI-facing equivalent,
/// unlike USSD's manual test buttons.
class SmsService {
  static const MethodChannel _channel = MethodChannel(
    backgroundServiceChannelName,
  );

  /// Fire-and-forget: only confirms the OS accepted the send request, not
  /// that it was delivered - see [drainOutcomes] for the real outcome,
  /// which arrives asynchronously.
  Future<void> dispatch({
    required int taskId,
    required String phone,
    required String message,
  }) {
    return _channel.invokeMethod<void>('sendSms', {
      'taskId': taskId,
      'phone': phone,
      'message': message,
    });
  }

  Future<List<SmsOutcome>> drainOutcomes() async {
    final result = await _channel.invokeMethod<List<dynamic>>(
      'drainSmsOutcomes',
    );
    if (result == null) return const [];
    return result
        .map((e) => SmsOutcome.fromMap(Map<dynamic, dynamic>.from(e as Map)))
        .toList();
  }
}
