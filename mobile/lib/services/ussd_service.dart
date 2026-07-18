import 'package:flutter/services.dart';

class DeviceInfo {
  DeviceInfo({
    required this.uuid,
    required this.operatorName,
    required this.phoneNumber,
    required this.deviceModel,
    required this.osVersion,
  });

  final String uuid;
  final String operatorName;
  final String phoneNumber;
  final String deviceModel;
  final String osVersion;

  factory DeviceInfo.fromJson(Map<String, dynamic> json) {
    return DeviceInfo(
      uuid: json['uuid'] as String? ?? 'unknown',
      operatorName: json['operatorName'] as String? ?? 'unknown',
      phoneNumber: json['phoneNumber'] as String? ?? 'unknown',
      deviceModel: json['deviceModel'] as String? ?? 'unknown',
      osVersion: json['osVersion'] as String? ?? 'unknown',
    );
  }
}

class UssdService {
  static const MethodChannel _channel = MethodChannel(
    'com.example.gateway_apk/ussd',
  );

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

  Future<String> sendUssdCode(String code) async {
    final result = await _channel.invokeMethod<String>('sendUssd', {
      'code': code,
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
