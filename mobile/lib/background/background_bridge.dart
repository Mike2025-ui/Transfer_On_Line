import 'dart:async';

import 'package:flutter/services.dart';

import '../services/ussd_service.dart' show DeviceInfo;
import 'ussd_step_event.dart';

/// Shared by every class that bridges the headless engine to native code
/// ([BackgroundBridge], `SmsService`) - both represent facets of the same
/// background engine's connection to [GatewayForegroundService], which
/// registers exactly one `MethodChannel` under this name on that engine.
const backgroundServiceChannelName = 'com.example.gateway_apk/gateway_service';

/// Bridges the headless engine's own native calls - distinct from
/// [UssdService]'s channel (`com.example.gateway_apk/ussd`), which only the
/// UI-attached engine in `MainActivity` exposes. `GatewayForegroundService`
/// registers this channel on the background engine it creates; the two
/// never share a MethodChannel because they run on two different
/// `FlutterEngine` instances (see GatewayForegroundService's class doc).
class BackgroundBridge {
  static const MethodChannel _channel = MethodChannel(
    backgroundServiceChannelName,
  );

  /// [simSlot]/[operator]: see UssdService.sendUssdCode's doc - same
  /// contract, this is just the headless engine's own copy of the same call.
  Future<String> dialUssd(String code, int? simSlot, String? operator) async {
    final result = await _channel.invokeMethod<String>('sendUssd', {
      'code': code,
      'simSlot': ?simSlot,
      'operator': ?operator,
    });
    if (result == null) {
      throw PlatformException(
        code: 'USSD_FAILED',
        message: 'USSD response unavailable',
      );
    }
    return result;
  }

  Future<DeviceInfo> getTelemetry() async {
    final result = await _channel.invokeMethod<Map<dynamic, dynamic>>(
      'getTelemetry',
    );
    if (result == null) {
      throw PlatformException(
        code: 'NO_TELEMETRY',
        message: 'Telemetry unavailable',
      );
    }
    return DeviceInfo.fromJson(Map<String, dynamic>.from(result));
  }

  /// Writes the watchdog's "last alive" timestamp natively (plain
  /// SharedPreferences, no Flutter engine dependency on the reading side -
  /// see GatewayWatchdogWorker). Called every tick regardless of whether the
  /// tick itself succeeded: a network hiccup is not the same thing as a dead
  /// loop, and only the latter should trigger a service restart.
  Future<void> reportAlive() => _channel.invokeMethod<void>('reportAlive');

  Future<void> updateNotification(String text) =>
      _channel.invokeMethod<void>('updateNotification', {'text': text});

  // --- Phase D4: interactive USSD session bridge ---------------------------
  // Outgoing (Dart -> Kotlin) calls only live here, on their own MethodChannel
  // object. Incoming (Kotlin -> Dart) "ussdStepEvent" calls are NOT handled
  // here: gateway_service_entrypoint.dart's `controlChannel` is the one and
  // only setMethodCallHandler() already registered for this exact channel
  // name (for the "stop" signal) - calling setMethodCallHandler() again on a
  // second MethodChannel object with the same name would silently replace
  // that handler instead of adding to it. See _ussdStepEvents below, fed by
  // gateway_service_entrypoint.dart forwarding into [emitUssdStepEvent].

  final StreamController<UssdStepEvent> _ussdStepEvents = StreamController<UssdStepEvent>.broadcast();

  /// Fed by gateway_service_entrypoint.dart's controlChannel handler - never
  /// called directly from native code.
  void emitUssdStepEvent(UssdStepEvent event) => _ussdStepEvents.add(event);

  Stream<UssdStepEvent> get ussdStepEvents => _ussdStepEvents.stream;

  Future<bool> isUssdAccessibilityEnabled() async {
    final result = await _channel.invokeMethod<bool>('isUssdAccessibilityEnabled');
    return result ?? false;
  }

  Future<void> startInteractiveUssdSession({required String code, int? simSlot}) =>
      _channel.invokeMethod<void>('startInteractiveUssdSession', {
        'code': code,
        'simSlot': ?simSlot,
      });

  Future<void> sendUssdBackendInput(List<String> values) =>
      _channel.invokeMethod<void>('ussdOnBackendInput', {'values': values});

  Future<void> sendUssdBackendDone() => _channel.invokeMethod<void>('ussdOnBackendDone');

  Future<void> cancelInteractiveUssdSession() =>
      _channel.invokeMethod<void>('cancelInteractiveUssdSession');
}
