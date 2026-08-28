/// Dart mirror of the Kotlin sealed class `UssdStepEvent`
/// (UssdAccessibilityService.kt, Phase D3) - deserialized from the
/// "ussdStepEvent" MethodChannel call's argument map (see
/// GatewayForegroundService.ussdStepEventToChannelMap). A plain tagged
/// class rather than a Dart 3 sealed hierarchy, kept deliberately simple:
/// this project's mobile/ SDK constraint is not otherwise verified, and a
/// flat class with nullable fields needs no language-version assumption.
class UssdStepEvent {
  const UssdStepEvent._({
    required this.type,
    this.fieldCount,
    this.status,
    this.operatorMessage,
    this.errorCode,
    this.detail,
  });

  final UssdStepEventType type;
  final int? fieldCount;
  final String? status;
  final String? operatorMessage;
  final String? errorCode;
  final String? detail;

  factory UssdStepEvent.fromChannelMap(Map<dynamic, dynamic> map) {
    final type = map['type'] as String? ?? '';
    switch (type) {
      case 'NEW_FIELD':
        return UssdStepEvent._(
          type: UssdStepEventType.newField,
          fieldCount: (map['fieldCount'] as num?)?.toInt() ?? 0,
        );
      case 'FINAL_FIELD':
        return const UssdStepEvent._(type: UssdStepEventType.finalField);
      case 'RESULT':
        return UssdStepEvent._(
          type: UssdStepEventType.result,
          status: map['status'] as String? ?? 'FAILED',
          operatorMessage: map['operatorMessage'] as String? ?? '',
        );
      case 'FAILED':
        return UssdStepEvent._(
          type: UssdStepEventType.failed,
          errorCode: map['errorCode'] as String? ?? 'UNKNOWN',
          detail: map['detail'] as String? ?? '',
        );
      case 'TIMEOUT':
        return const UssdStepEvent._(type: UssdStepEventType.timeout);
      default:
        // Never silently misclassify an unrecognized wire event as
        // something actionable - surfaced as Failed so the runner reports
        // it and releases the Gateway rather than hanging forever.
        return UssdStepEvent._(
          type: UssdStepEventType.failed,
          errorCode: 'UNKNOWN_EVENT_TYPE',
          detail: 'type=$type',
        );
    }
  }
}

enum UssdStepEventType { newField, finalField, result, failed, timeout }
