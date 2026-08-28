package com.example.gateway_apk

import android.Manifest
import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.StatFs
import android.provider.Settings
import android.telephony.SubscriptionManager
import android.telephony.TelephonyManager
import androidx.core.content.ContextCompat
import java.net.NetworkInterface
import java.util.Collections

/**
 * All device/telemetry reads the heartbeat needs (battery, temperature,
 * network, signal, IP, RAM, storage, SIM list) - extracted out of
 * MainActivity so [GatewayForegroundService]'s autonomous loop and the UI's
 * manual buttons read the exact same values the exact same way, rather than
 * maintaining two copies that could drift.
 *
 * Every reader here is entirely best-effort: a missing permission or an
 * unsupported API level just drops that one field (returns null / empty),
 * matching the backend's "absent key = leave untouched" heartbeat contract
 * (see GatewayManager._apply_heartbeat_telemetry) - nothing here should ever
 * throw out of [getDeviceInfo].
 */
object DeviceTelemetry {

    fun getDeviceInfo(context: Context): Map<String, Any?> {
        val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
        val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
        return mapOf(
            "uuid" to androidId,
            "operatorName" to tm.networkOperatorName,
            "phoneNumber" to tm.line1Number,
            "deviceModel" to Build.MODEL,
            "osVersion" to Build.VERSION.RELEASE,
            // Informational only (onboarding's OEM autostart checklist,
            // see OnboardingScreen) - never part of the heartbeat contract
            // the backend actually reads, harmless if it rides along.
            "manufacturer" to Build.MANUFACTURER,
            "appVersion" to appVersion(context),
            "batteryLevel" to batteryLevel(context),
            "temperature" to temperature(context),
            "networkType" to networkType(context),
            "ipAddress" to ipAddress(),
            "signalStrength" to signalStrength(context, tm),
            "ramAvailableMb" to ramAvailableMb(context),
            "storageAvailableMb" to storageAvailableMb(),
            "sims" to simList(context),
        )
    }

    fun hasPermission(context: Context, permission: String): Boolean {
        return ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED
    }

    private fun appVersion(context: Context): String? {
        return try {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName
        } catch (e: Exception) {
            null
        }
    }

    private fun batteryLevel(context: Context): Int? {
        return try {
            val bm = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
            val level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
            if (level in 0..100) level else null
        } catch (e: Exception) {
            null
        }
    }

    // Sticky broadcast, not a real registration: passing a null receiver to
    // registerReceiver() for ACTION_BATTERY_CHANGED just reads the last
    // broadcast Android already cached, with no listener to leak/unregister.
    private fun temperature(context: Context): Float? {
        return try {
            val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            val tenthsOfCelsius = intent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1
            if (tenthsOfCelsius >= 0) tenthsOfCelsius / 10f else null
        } catch (e: Exception) {
            null
        }
    }

    private fun networkType(context: Context): String? {
        return try {
            val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val network = cm.activeNetwork ?: return "none"
            val capabilities = cm.getNetworkCapabilities(network) ?: return "none"
            when {
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "mobile"
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
                else -> "other"
            }
        } catch (e: Exception) {
            null
        }
    }

    private fun ipAddress(): String? {
        return try {
            val interfaces = Collections.list(NetworkInterface.getNetworkInterfaces())
            for (iface in interfaces) {
                val addresses = Collections.list(iface.inetAddresses)
                for (addr in addresses) {
                    if (!addr.isLoopbackAddress && addr.hostAddress?.contains(':') == false) {
                        return addr.hostAddress
                    }
                }
            }
            null
        } catch (e: Exception) {
            null
        }
    }

    private fun signalStrength(context: Context, tm: TelephonyManager): Int? {
        if (!hasPermission(context, Manifest.permission.READ_PHONE_STATE)) return null
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) return null
        return try {
            tm.signalStrength?.level
        } catch (e: SecurityException) {
            null
        } catch (e: Exception) {
            null
        }
    }

    private fun ramAvailableMb(context: Context): Int? {
        return try {
            val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            val info = ActivityManager.MemoryInfo()
            am.getMemoryInfo(info)
            (info.availMem / (1024 * 1024)).toInt()
        } catch (e: Exception) {
            null
        }
    }

    private fun storageAvailableMb(): Int? {
        return try {
            val stat = StatFs(Environment.getDataDirectory().path)
            (stat.availableBlocksLong * stat.blockSizeLong / (1024 * 1024)).toInt()
        } catch (e: Exception) {
            null
        }
    }

    // Slot + operator are the fields the backend actually relies on
    // (GatewayManager._apply_heartbeat_sims); msisdn is filled in whenever
    // the platform/permission combination allows it and left blank
    // otherwise - Android increasingly refuses to expose per-SIM numbers,
    // so this must degrade gracefully rather than block the whole payload.
    private fun simList(context: Context): List<Map<String, Any?>> {
        if (!hasPermission(context, Manifest.permission.READ_PHONE_STATE)) return emptyList()
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP_MR1) return emptyList()
        return try {
            val sm = context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as SubscriptionManager
            val subscriptions = sm.activeSubscriptionInfoList ?: return emptyList()
            subscriptions.map { sub ->
                var msisdn: String? = null
                if (hasPermission(context, Manifest.permission.READ_PHONE_NUMBERS)) {
                    msisdn = try {
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) sub.number else null
                    } catch (e: SecurityException) {
                        null
                    }
                }
                mapOf(
                    "slot" to sub.simSlotIndex,
                    "operator" to (sub.carrierName?.toString() ?: ""),
                    "msisdn" to (msisdn ?: ""),
                )
            }
        } catch (e: SecurityException) {
            emptyList()
        } catch (e: Exception) {
            emptyList()
        }
    }
}
