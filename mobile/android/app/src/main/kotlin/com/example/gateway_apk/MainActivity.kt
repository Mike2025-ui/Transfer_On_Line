package com.example.gateway_apk

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.telephony.TelephonyManager
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val CHANNEL = "com.example.gateway_apk/ussd"
    private val REQUEST_CALL_PERMISSION = 1001
    private val REQUEST_TELEMETRY_PERMISSIONS = 1002
    private val REQUEST_CALL_PERMISSION_EXPLICIT = 1003
    private val REQUEST_NOTIFICATION_PERMISSION = 1004
    private var pendingResult: MethodChannel.Result? = null
    private var pendingTelemetryResult: MethodChannel.Result? = null
    private var pendingCallPermissionResult: MethodChannel.Result? = null
    private var pendingNotificationPermissionResult: MethodChannel.Result? = null

    override fun onCreate(savedInstanceState: android.os.Bundle?) {
        super.onCreate(savedInstanceState)
        // Idempotent (ExistingPeriodicWorkPolicy.KEEP) - safe to call on
        // every launch rather than needing a "first run" guard.
        GatewayWatchdogWorker.enqueue(applicationContext)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "sendUssd" -> {
                    val code = call.argument<String>("code") ?: ""
                    if (code.isBlank()) {
                        result.error("INVALID_CODE", "USSD code missing", null)
                        return@setMethodCallHandler
                    }
                    sendUssd(code, call.argument<Int>("simSlot"), call.argument<String>("operator"), result)
                }
                "getDeviceInfo" -> result.success(DeviceTelemetry.getDeviceInfo(this))
                "requestTelemetryPermissions" -> requestTelemetryPermissions(result)
                "requestCallPermission" -> requestCallPermissionExplicit(result)
                "requestNotificationPermission" -> requestNotificationPermission(result)
                "startGatewayService" -> {
                    GatewayForegroundService.start(this)
                    result.success(null)
                }
                "stopGatewayService" -> {
                    GatewayForegroundService.stop(this)
                    result.success(null)
                }
                "isIgnoringBatteryOptimizations" -> result.success(isIgnoringBatteryOptimizations())
                "requestBatteryOptimizationExemption" -> {
                    requestBatteryOptimizationExemption()
                    result.success(null)
                }
                "openUssdTestActivity" -> {
                    startActivity(Intent(this, UssdTestActivity::class.java))
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun hasPermission(permission: String): Boolean = DeviceTelemetry.hasPermission(this, permission)

    private fun hasCallPermission(): Boolean {
        return hasPermission(Manifest.permission.CALL_PHONE)
    }

    // Requested once from Dart at startup, ahead of the first getDeviceInfo()
    // call, so the very first heartbeat can already carry signal/SIM data
    // when the user grants it. Denial is not an error: getDeviceInfo() just
    // keeps returning null/empty for those fields, same as before this
    // permission existed.
    private fun requestTelemetryPermissions(result: MethodChannel.Result) {
        val needed = listOf(Manifest.permission.READ_PHONE_STATE, Manifest.permission.READ_PHONE_NUMBERS)
            .filter { !hasPermission(it) }
        if (needed.isEmpty()) {
            result.success(true)
            return
        }
        pendingTelemetryResult = result
        ActivityCompat.requestPermissions(this, needed.toTypedArray(), REQUEST_TELEMETRY_PERMISSIONS)
    }

    // Onboarding-triggered: unlike sendUssd's implicit request (which only
    // ever fires the moment a real dial is attempted), this lets the
    // onboarding screen ask for CALL_PHONE upfront - without it granted
    // ahead of time, the autonomous loop (running in
    // GatewayForegroundService, which cannot itself show a permission
    // dialog) would have no way to obtain it before its first dial attempt.
    // Returns a plain bool (granted or not) rather than success/error: a
    // denial here is a normal onboarding outcome, not a failure to report
    // as an exception the way sendUssd's caller expects.
    private fun requestCallPermissionExplicit(result: MethodChannel.Result) {
        if (hasCallPermission()) {
            result.success(true)
            return
        }
        pendingCallPermissionResult = result
        ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CALL_PHONE), REQUEST_CALL_PERMISSION_EXPLICIT)
    }

    // Stabilisation RC1 (priorité haute n°3): declaring POST_NOTIFICATIONS
    // in the manifest is not enough on API 33+ - without this explicit
    // runtime request, GatewayForegroundService's persistent notification
    // can silently never appear even though the service itself keeps
    // running fine, leaving a technician on-site with no visual
    // confirmation the Gateway is alive. No-op (auto-granted) below API 33.
    private fun requestNotificationPermission(result: MethodChannel.Result) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            result.success(true)
            return
        }
        if (hasPermission(Manifest.permission.POST_NOTIFICATIONS)) {
            result.success(true)
            return
        }
        pendingNotificationPermissionResult = result
        ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATION_PERMISSION)
    }

    private fun isIgnoringBatteryOptimizations(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        return pm.isIgnoringBatteryOptimizations(packageName)
    }

    // Sideloaded phones have no MDM to grant this silently (see the Phase C
    // plan) - this opens the system dialog a human on-site taps through
    // once per phone. Safe to call repeatedly: a no-op if already exempted.
    private fun requestBatteryOptimizationExemption() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M || isIgnoringBatteryOptimizations()) return
        val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
            data = Uri.parse("package:$packageName")
        }
        startActivity(intent)
    }

    private fun sendUssd(code: String, simSlot: Int?, operator: String?, result: MethodChannel.Result) {
        if (!hasCallPermission()) {
            pendingResult = result
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CALL_PHONE), REQUEST_CALL_PERMISSION)
            return
        }

        val tm = getSystemService(TELEPHONY_SERVICE) as TelephonyManager
        TelephonyGateway.sendUssdChecked(this, tm, code, simSlot, operator) { outcome ->
            outcome.fold(
                onSuccess = { response -> result.success(response) },
                onFailure = { error ->
                    when (error) {
                        is UssdUnsupportedException -> result.error("UNSUPPORTED", error.message, null)
                        is OperatorMismatchException -> result.error("OPERATOR_MISMATCH", error.message, null)
                        else -> result.error("USSD_FAILED", error.message, null)
                    }
                },
            )
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        when (requestCode) {
            REQUEST_CALL_PERMISSION -> {
                if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                    pendingResult?.success("PERMISSION_GRANTED")
                } else {
                    pendingResult?.error("PERMISSION_DENIED", "CALL_PHONE permission denied", null)
                }
                pendingResult = null
            }
            REQUEST_TELEMETRY_PERMISSIONS -> {
                val granted = grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }
                pendingTelemetryResult?.success(granted)
                pendingTelemetryResult = null
            }
            REQUEST_CALL_PERMISSION_EXPLICIT -> {
                val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
                pendingCallPermissionResult?.success(granted)
                pendingCallPermissionResult = null
            }
            REQUEST_NOTIFICATION_PERMISSION -> {
                val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
                pendingNotificationPermissionResult?.success(granted)
                pendingNotificationPermissionResult = null
            }
        }
    }
}
