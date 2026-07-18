package com.example.gateway_apk

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
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
    private var pendingResult: MethodChannel.Result? = null

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
                    sendUssd(code, result)
                }
                "getDeviceInfo" -> result.success(getDeviceInfo())
                else -> result.notImplemented()
            }
        }
    }

    private fun getDeviceInfo(): Map<String, Any?> {
        val tm = getSystemService(TELEPHONY_SERVICE) as TelephonyManager
        val androidId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
        return mapOf(
            "uuid" to androidId,
            "operatorName" to tm.networkOperatorName,
            "phoneNumber" to tm.line1Number,
            "deviceModel" to Build.MODEL,
            "osVersion" to Build.VERSION.RELEASE,
        )
    }

    private fun hasCallPermission(): Boolean {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED
    }

    private fun sendUssd(code: String, result: MethodChannel.Result) {
        if (!hasCallPermission()) {
            pendingResult = result
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CALL_PHONE), REQUEST_CALL_PERMISSION)
            return
        }

        val tm = getSystemService(TELEPHONY_SERVICE) as TelephonyManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            tm.sendUssdRequest(code, object : TelephonyManager.UssdResponseCallback() {
                override fun onReceiveUssdResponse(
                    telephonyManager: TelephonyManager,
                    request: String,
                    response: CharSequence,
                ) {
                    result.success(response.toString())
                }

                override fun onReceiveUssdResponseFailed(
                    telephonyManager: TelephonyManager,
                    request: String,
                    failureCode: Int,
                ) {
                    result.error("USSD_FAILED", "USSD failed with code $failureCode", null)
                }
            }, Handler(mainLooper))
        } else {
            result.error("UNSUPPORTED", "USSD not supported on Android versions below O", null)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_CALL_PERMISSION) {
            if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                pendingResult?.success("PERMISSION_GRANTED")
            } else {
                pendingResult?.error("PERMISSION_DENIED", "CALL_PHONE permission denied", null)
            }
            pendingResult = null
        }
    }
}
