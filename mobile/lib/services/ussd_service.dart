import 'package:flutter/services.dart';

class SimInfo {
  const SimInfo({required this.slot, required this.operator, this.msisdn});

  final int slot;
  final String operator;
  final String? msisdn;

  factory SimInfo.fromJson(Map<String, dynamic> json) {
    return SimInfo(
      slot: (json['slot'] as num?)?.toInt() ?? 0,
      operator: json['operator'] as String? ?? '',
      msisdn: json['msisdn'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
    'slot': slot,
    'operator': operator,
    if (msisdn != null && msisdn!.isNotEmpty) 'msisdn': msisdn,
  };
}

class DeviceInfo {
  DeviceInfo({
    required this.uuid,
    required this.operatorName,
    required this.phoneNumber,
    required this.deviceModel,
    required this.osVersion,
    this.appVersion,
    this.batteryLevel,
    this.temperature,
    this.networkType,
    this.signalStrength,
    this.ipAddress,
    this.ramAvailableMb,
    this.storageAvailableMb,
    this.isBusy,
    this.currentTaskCount,
    this.manufacturer,
    this.sims = const [],
  });

  final String uuid;
  final String operatorName;
  final String phoneNumber;
  final String deviceModel;
  final String osVersion;
  // Informational only - drives the onboarding screen's OEM-specific
  // autostart checklist (Xiaomi/Oppo/Vivo/Huawei aggressively kill
  // background apps regardless of the battery-optimization exemption).
  final String? manufacturer;

  // Telemetry added for the Gateway/GatewaySim heartbeat (Phase B, mobile
  // chantier). All optional: an older backend or a permission-denied device
  // simply never populates these, matching the server's "absent key = leave
  // untouched" heartbeat contract.
  final String? appVersion;
  final int? batteryLevel;
  final double? temperature;
  final String? networkType;
  final int? signalStrength;
  final String? ipAddress;
  final int? ramAvailableMb;
  final int? storageAvailableMb;
  // Live operational state (Phase C, autonomous loop) - unlike the fields
  // above, these two are meaningless as a one-time snapshot: is_busy/
  // current_task_count only mean something when read fresh at the moment a
  // heartbeat is actually sent (see GatewayLoop), never cached from launch.
  final bool? isBusy;
  final int? currentTaskCount;
  final List<SimInfo> sims;

  factory DeviceInfo.fromJson(Map<String, dynamic> json) {
    final rawSims = json['sims'] as List<dynamic>?;
    return DeviceInfo(
      uuid: json['uuid'] as String? ?? 'unknown',
      operatorName: json['operatorName'] as String? ?? 'unknown',
      phoneNumber: json['phoneNumber'] as String? ?? 'unknown',
      deviceModel: json['deviceModel'] as String? ?? 'unknown',
      osVersion: json['osVersion'] as String? ?? 'unknown',
      appVersion: json['appVersion'] as String?,
      batteryLevel: (json['batteryLevel'] as num?)?.toInt(),
      temperature: (json['temperature'] as num?)?.toDouble(),
      networkType: json['networkType'] as String?,
      signalStrength: (json['signalStrength'] as num?)?.toInt(),
      ipAddress: json['ipAddress'] as String?,
      ramAvailableMb: (json['ramAvailableMb'] as num?)?.toInt(),
      storageAvailableMb: (json['storageAvailableMb'] as num?)?.toInt(),
      manufacturer: json['manufacturer'] as String?,
      sims:
          rawSims
              ?.map((e) => SimInfo.fromJson(Map<String, dynamic>.from(e)))
              .toList() ??
          const [],
    );
  }

  /// Returns a copy with live operational state filled in - used right
  /// before sending a heartbeat, never persisted back onto the cached
  /// instance used by the UI.
  DeviceInfo withLiveState({bool? isBusy, int? currentTaskCount}) {
    return DeviceInfo(
      uuid: uuid,
      operatorName: operatorName,
      phoneNumber: phoneNumber,
      deviceModel: deviceModel,
      osVersion: osVersion,
      appVersion: appVersion,
      batteryLevel: batteryLevel,
      temperature: temperature,
      networkType: networkType,
      signalStrength: signalStrength,
      ipAddress: ipAddress,
      ramAvailableMb: ramAvailableMb,
      storageAvailableMb: storageAvailableMb,
      manufacturer: manufacturer,
      isBusy: isBusy ?? this.isBusy,
      currentTaskCount: currentTaskCount ?? this.currentTaskCount,
      sims: sims,
    );
  }
}

class UssdService {
  static const MethodChannel _channel = MethodChannel(
    'com.example.gateway_apk/ussd',
  );

  /// Best-effort: requests READ_PHONE_STATE/READ_PHONE_NUMBERS so the
  /// heartbeat can carry signal strength and the SIM list. Denial is not an
  /// error - it just means those fields stay absent, same as on a build
  /// that predates this permission entirely.
  Future<bool> requestTelemetryPermissions() async {
    try {
      final granted = await _channel.invokeMethod<bool>(
        'requestTelemetryPermissions',
      );
      return granted ?? false;
    } catch (_) {
      return false;
    }
  }

  /// Stabilisation RC1 (priorité haute n°3): requests POST_NOTIFICATIONS on
  /// Android 13+ so GatewayForegroundService's persistent notification can
  /// actually appear. No-op success on older Android versions (handled
  /// natively) - denial is a normal onboarding outcome, not an error.
  Future<bool> requestNotificationPermission() async {
    try {
      final granted = await _channel.invokeMethod<bool>(
        'requestNotificationPermission',
      );
      return granted ?? false;
    } catch (_) {
      return false;
    }
  }

  Future<DeviceInfo> getDeviceInfo() async {
    final result = await _channel.invokeMethod<Map<dynamic, dynamic>>(
      'getDeviceInfo',
    );
    if (result == null) {
      throw PlatformException(
        code: 'NO_DEVICE_INFO',
        message: 'Device info unavailable',
      );
    }
    return DeviceInfo.fromJson(Map<String, dynamic>.from(result));
  }

  /// Starts [GatewayForegroundService] (idempotent - starting an already
  /// running service just delivers a new onStartCommand, no duplicate).
  Future<void> startGatewayService() =>
      _channel.invokeMethod<void>('startGatewayService');

  Future<void> stopGatewayService() =>
      _channel.invokeMethod<void>('stopGatewayService');

  Future<bool> isIgnoringBatteryOptimizations() async {
    final result = await _channel.invokeMethod<bool>(
      'isIgnoringBatteryOptimizations',
    );
    return result ?? false;
  }

  /// Opens the system dialog for the battery-optimization exemption -
  /// see MainActivity.requestBatteryOptimizationExemption's doc: sideloaded
  /// phones have no MDM to grant this silently.
  Future<void> requestBatteryOptimizationExemption() =>
      _channel.invokeMethod<void>('requestBatteryOptimizationExemption');

  /// Asks for CALL_PHONE upfront (onboarding) rather than waiting for the
  /// first real dial to trigger it implicitly - see
  /// MainActivity.requestCallPermissionExplicit's doc: the autonomous loop
  /// runs inside a Service, which cannot itself show this dialog.
  Future<bool> requestCallPermission() async {
    final granted = await _channel.invokeMethod<bool>('requestCallPermission');
    return granted ?? false;
  }

  /// Ouvre UssdTestActivity (Phase 8.2, validation sur device réel) - action
  /// strictement manuelle déclenchée par un bouton, jamais automatique.
  /// N'active rien : UssdAccessibilityService reste activé/désactivé
  /// uniquement depuis Réglages > Accessibilité par l'utilisateur.
  Future<void> openUssdTestActivity() =>
      _channel.invokeMethod<void>('openUssdTestActivity');

  /// [simSlot]: the physical SIM slot (0/1) the Scheduler reserved for this
  /// task (see `PendingTransaction.simSlot`) - null dials on the phone's
  /// default SIM, exactly as before multi-SIM targeting existed.
  /// [operator]: the operator this task requires (Phase D audit, Critique) -
  /// null skips the native SIM/operator cross-check entirely.
  Future<String> sendUssdCode(String code, int? simSlot, String? operator) async {
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
}
