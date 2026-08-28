package com.example.gateway_apk

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import io.flutter.FlutterInjector
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.FlutterEngineCache
import io.flutter.embedding.engine.dart.DartExecutor
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugins.GeneratedPluginRegistrant
import android.telephony.TelephonyManager

/**
 * The autonomous Gateway: a thin shell that keeps a headless [FlutterEngine]
 * alive and running [GatewayLoop] (Dart) with the screen off. Deliberately
 * NOT where the polling/heartbeat/queue business logic lives - that stays in
 * Dart (see `lib/background/gateway_loop.dart`'s doc for why) so it is
 * unit-testable and shared with the manual UI path. This class only does
 * what Dart genuinely cannot: start a real Android foreground service,
 * expose the platform calls (`sendUssd`, telemetry, the watchdog's alive
 * timestamp) that only native code can make.
 *
 * Lifecycle notes (see the Phase C plan for the full API-level rationale):
 * - `startForeground()` is called first, synchronously, with a generic
 *   notification, before the (potentially slower) Flutter engine is touched
 *   - Android requires this within a few seconds of the service starting.
 * - The engine is cached in [FlutterEngineCache] so a quick restart (manual
 *   toggle, watchdog-triggered) doesn't pay full Dart-VM cold-start cost
 *   again within the same still-alive process. It is only ever torn down by
 *   the OS killing the whole process - `onDestroy()` deliberately does not
 *   dispose it.
 */
class GatewayForegroundService : Service() {

    private var engine: FlutterEngine? = null
    private var methodChannel: MethodChannel? = null

    override fun onCreate() {
        super.onCreate()
        activeInstance = this
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundCompat(buildNotification("Service actif - en attente"))
        ensureEngineRunning()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        super.onDestroy()
        if (activeInstance === this) activeInstance = null
        // The cached engine itself still outlives this Service instance on
        // purpose (see the class doc) - only the Android Service component
        // stops here. Stabilisation RC1 (priorité critique n°1): the actual
        // Dart Timer.periodic is stopped separately, via the "stop" signal
        // requestStopFromDart() sends *before* this runs (see stop()) -
        // that signal still reaches the isolate because the engine survives
        // this call.
    }

    /** Tells the still-alive headless isolate to cancel its own loop - see
     * `gateway_service_entrypoint.dart`'s `controlChannel` handler. Fire-
     * and-forget: even if this particular message were lost, `stop()`
     * already persisted `desired_state=false`, so the watchdog/BootReceiver
     * will never bring the service back regardless. */
    private fun requestStopFromDart() {
        methodChannel?.invokeMethod("stop", null)
    }

    // API 35's graceful-shutdown hook for time-limited foreground service
    // types (see build.gradle.kts's targetSdk comment). A no-op override now
    // so bumping targetSdk later doesn't silently regress into the default
    // (potentially abrupt) teardown behavior.
    override fun onTimeout(startId: Int, fgsType: Int) {
        stopSelf()
    }

    private fun ensureEngineRunning() {
        if (engine != null) return
        val cached = FlutterEngineCache.getInstance().get(CACHED_ENGINE_ID)
        val flutterEngine = if (cached != null) {
            cached
        } else {
            // The UI engine (MainActivity) usually already initialized the
            // loader, but a boot-triggered start may be the very first
            // engine in the whole process - both branches must be handled.
            val loader = FlutterInjector.instance().flutterLoader()
            if (!loader.initialized()) {
                loader.startInitialization(applicationContext)
            }
            loader.ensureInitializationComplete(applicationContext, null)

            val newEngine = FlutterEngine(applicationContext)
            GeneratedPluginRegistrant.registerWith(newEngine)
            val entrypoint = DartExecutor.DartEntrypoint(
                loader.findAppBundlePath(),
                "gatewayServiceMain",
            )
            newEngine.dartExecutor.executeDartEntrypoint(entrypoint)
            FlutterEngineCache.getInstance().put(CACHED_ENGINE_ID, newEngine)
            newEngine
        }
        engine = flutterEngine
        val channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, SERVICE_CHANNEL)
        channel.setMethodCallHandler { call, result ->
            when (call.method) {
                "sendUssd" -> {
                    val code = call.argument<String>("code") ?: ""
                    if (code.isBlank()) {
                        result.error("INVALID_CODE", "USSD code missing", null)
                        return@setMethodCallHandler
                    }
                    // Unlike MainActivity.sendUssd, a Service cannot itself
                    // show a runtime permission dialog - CALL_PHONE must
                    // already have been granted (see the onboarding screen,
                    // Étape 9) or every autonomous dial attempt fails here
                    // cleanly instead of throwing an uncaught
                    // SecurityException out of the telephony API.
                    if (!DeviceTelemetry.hasPermission(applicationContext, android.Manifest.permission.CALL_PHONE)) {
                        result.error("PERMISSION_DENIED", "CALL_PHONE permission not granted", null)
                        return@setMethodCallHandler
                    }
                    val tm = getSystemService(TELEPHONY_SERVICE) as TelephonyManager
                    TelephonyGateway.sendUssdChecked(
                        applicationContext, tm, code, call.argument<Int>("simSlot"), call.argument<String>("operator"),
                    ) { outcome ->
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
                "sendSms" -> {
                    val taskId = call.argument<Int>("taskId")
                    val phone = call.argument<String>("phone") ?: ""
                    val message = call.argument<String>("message") ?: ""
                    if (taskId == null || phone.isBlank() || message.isBlank()) {
                        result.error("INVALID_ARGS", "taskId/phone/message required", null)
                        return@setMethodCallHandler
                    }
                    try {
                        val smsManager = TelephonyGateway.smsManagerFor(applicationContext, call.argument<Int>("simSlot"))
                        TelephonyGateway.sendSms(applicationContext, smsManager, taskId, phone, message)
                        result.success(null)
                    } catch (e: Exception) {
                        result.error("SMS_FAILED", e.message, null)
                    }
                }
                "drainSmsOutcomes" -> result.success(SmsOutbox.drainAll(applicationContext))
                "getTelemetry" -> result.success(DeviceTelemetry.getDeviceInfo(applicationContext))
                "reportAlive" -> {
                    writeAliveTimestamp()
                    result.success(null)
                }
                "updateNotification" -> {
                    val text = call.argument<String>("text") ?: ""
                    updateNotification(text)
                    result.success(null)
                }
                // Phase D4: bridge between the headless Dart engine and
                // UssdAccessibilityService. This Service (not an Activity)
                // must add FLAG_ACTIVITY_NEW_TASK to start ACTION_CALL - the
                // same requirement UssdAccessibilityService.openAccessibilitySettings
                // already has, for the identical reason (non-Activity context).
                "isUssdAccessibilityEnabled" ->
                    result.success(UssdAccessibilityService.isAccessibilityServiceEnabled(applicationContext))
                "startInteractiveUssdSession" -> {
                    val code = call.argument<String>("code") ?: ""
                    if (code.isBlank()) {
                        result.error("INVALID_CODE", "USSD code missing", null)
                        return@setMethodCallHandler
                    }
                    if (!DeviceTelemetry.hasPermission(applicationContext, android.Manifest.permission.CALL_PHONE)) {
                        result.error("PERMISSION_DENIED", "CALL_PHONE permission not granted", null)
                        return@setMethodCallHandler
                    }
                    val armed = UssdAccessibilityService.armSession(
                        UssdSessionConfig(simSlot = call.argument<Int>("simSlot")),
                    )
                    if (!armed) {
                        result.error("ACCESSIBILITY_NOT_ACTIVE", "UssdAccessibilityService is not bound", null)
                        return@setMethodCallHandler
                    }
                    try {
                        val intent = Intent(Intent.ACTION_CALL, Uri.parse("tel:" + Uri.encode(code))).apply {
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        startActivity(intent)
                        result.success(null)
                    } catch (e: Exception) {
                        UssdAccessibilityService.cancelActiveSession()
                        result.error("ACTION_CALL_FAILED", e.message, null)
                    }
                }
                "ussdOnBackendInput" -> {
                    @Suppress("UNCHECKED_CAST")
                    val values = (call.argument<List<Any?>>("values") ?: emptyList<Any?>()).map { it.toString() }
                    UssdAccessibilityService.onBackendInput(values)
                    result.success(null)
                }
                "ussdOnBackendDone" -> {
                    UssdAccessibilityService.onBackendDone()
                    result.success(null)
                }
                "cancelInteractiveUssdSession" -> {
                    UssdAccessibilityService.cancelActiveSession()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
        methodChannel = channel
        // Phase D4: this Service is the sole production consumer of
        // AccessibilityService step events - separate listener slot from
        // UssdTestActivity's (see UssdAccessibilityService.emit's doc), so
        // opening the debug UI can never silently cut off this bridge.
        UssdAccessibilityService.setProductionStepEventListener { event ->
            channel.invokeMethod("ussdStepEvent", ussdStepEventToChannelMap(event))
        }
    }

    private fun writeAliveTimestamp() {
        val prefs = watchdogPrefs(applicationContext)
        prefs.edit().putLong(KEY_LAST_ALIVE_AT, System.currentTimeMillis()).apply()
    }

    private fun updateNotification(text: String) {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIFICATION_ID, buildNotification(text))
    }

    private fun startForegroundCompat(notification: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                NOTIFICATION_CHANNEL_ID,
                "Service Gateway",
                NotificationManager.IMPORTANCE_LOW,
            )
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        return NotificationCompat.Builder(this, NOTIFICATION_CHANNEL_ID)
            .setContentTitle("Transfer On Line Gateway")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    companion object {
        private const val CACHED_ENGINE_ID = "gateway_bg_engine"
        const val SERVICE_CHANNEL = "com.example.gateway_apk/gateway_service"
        private const val NOTIFICATION_ID = 42
        private const val NOTIFICATION_CHANNEL_ID = "gateway_service_channel"
        private const val WATCHDOG_PREFS_NAME = "gateway_watchdog"
        const val KEY_LAST_ALIVE_AT = "last_alive_at"
        // Distinguishes "died unexpectedly, please restart" from "the user
        // deliberately stopped it" - both BootReceiver and
        // GatewayWatchdogWorker must never override an explicit stop.
        // Defaults to true (absent = "should be running") so a fresh
        // install / first boot behaves like the always-on relay this app is
        // for, without requiring an explicit first start to survive a boot.
        const val KEY_DESIRED_STATE = "desired_state"

        // Plain SharedPreferences, read directly by GatewayWatchdogWorker
        // (no Flutter engine involved there) - see that class's doc for why.
        fun watchdogPrefs(context: Context): SharedPreferences {
            return context.getSharedPreferences(WATCHDOG_PREFS_NAME, Context.MODE_PRIVATE)
        }

        fun start(context: Context) {
            watchdogPrefs(context).edit().putBoolean(KEY_DESIRED_STATE, true).apply()
            val intent = Intent(context, GatewayForegroundService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            watchdogPrefs(context).edit().putBoolean(KEY_DESIRED_STATE, false).apply()
            // Stabilisation RC1 (priorité critique n°1): tell the running
            // isolate to cancel its Timer.periodic *before* tearing down the
            // Service - see requestStopFromDart()'s doc for why this still
            // reaches Dart even though the engine is cached past this call.
            activeInstance?.requestStopFromDart()
            context.stopService(Intent(context, GatewayForegroundService::class.java))
        }

        // Deliberately a plain nullable reference, not a WeakReference: this
        // service is designed to live for the app process's lifetime (see
        // the class doc on the cached FlutterEngine), so the same lifetime
        // assumption already applies here - cleared explicitly in
        // onDestroy() so it never outlives the instance it points to.
        @Volatile
        private var activeInstance: GatewayForegroundService? = null
    }
}

/** Wire format for the native->Dart "ussdStepEvent" call - MethodChannel only
 * carries primitives/collections, never the Kotlin sealed class itself.
 * Top-level (not a method on [GatewayForegroundService]) purely so it is
 * unit-testable without instantiating a real Android [android.app.Service] -
 * same rationale as `decideScreenEvent`/`isScreenStable` in
 * UssdAccessibilityService.kt. Pure data mapping only: the actual channel
 * round-trip (native -> Dart -> UssdStepEvent.fromChannelMap) is exercised
 * for real only on the Itel A80, never claimed proven by this function alone. */
fun ussdStepEventToChannelMap(event: UssdStepEvent): Map<String, Any?> = when (event) {
    is UssdStepEvent.NewField -> mapOf("type" to "NEW_FIELD", "fieldCount" to event.fieldCount)
    UssdStepEvent.FinalField -> mapOf("type" to "FINAL_FIELD")
    is UssdStepEvent.Result -> mapOf(
        "type" to "RESULT", "status" to event.status, "operatorMessage" to event.operatorMessage,
    )
    is UssdStepEvent.Failed -> mapOf("type" to "FAILED", "errorCode" to event.errorCode, "detail" to event.detail)
    UssdStepEvent.Timeout -> mapOf("type" to "TIMEOUT")
}
