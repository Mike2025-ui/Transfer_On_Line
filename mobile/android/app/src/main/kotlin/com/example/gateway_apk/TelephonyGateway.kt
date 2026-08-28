package com.example.gateway_apk

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.telephony.SmsManager
import android.telephony.SubscriptionManager
import android.telephony.TelephonyManager

/** Thrown when USSD dialing isn't supported on this API level (< O). */
class UssdUnsupportedException(message: String) : Exception(message)

/** Thrown when the platform reported a USSD failure (bad code, network, etc). */
class UssdFailedException(message: String, val failureCode: Int) : Exception(message)

/** Thrown by [TelephonyGateway.sendUssdChecked] (Phase D audit) when the SIM
 * that would actually be dialed does not belong to the expected operator -
 * see [SimResolver.matchesExpectedOperator] for exactly what's compared. */
class OperatorMismatchException(message: String) : Exception(message)

/**
 * The one place that actually calls [TelephonyManager.sendUssdRequest] -
 * shared by [MainActivity]'s manual "Test transfert"/"Test souscription"
 * buttons and [GatewayForegroundService]'s autonomous loop, so the dial
 * logic is written exactly once. Callback-based (not suspend/coroutine) to
 * match [TelephonyManager.UssdResponseCallback]'s own shape without adding
 * a coroutines dependency this project doesn't otherwise need.
 */
object TelephonyGateway {
    /**
     * Phase D audit (Critique): the entry point [MainActivity] and
     * [GatewayForegroundService] should now both call instead of resolving +
     * dialing separately - resolves the SIM for [slot] (same logic that used
     * to live in a separate telephonyManagerFor() helper, now folded in
     * here), but refuses to dial at all
     * ([OperatorMismatchException], never even reaching [sendUssd]) unless
     * [SimResolver.matchesExpectedOperator] positively confirms the SIM that
     * would actually be used belongs to [expectedOperator]. [expectedOperator]
     * null/blank (older Gateway build, or the backend never sent one) skips
     * the check entirely - additive, not a behavior change for that case.
     */
    fun sendUssdChecked(
        context: Context,
        baseTelephonyManager: TelephonyManager,
        code: String,
        slot: Int?,
        expectedOperator: String?,
        onResult: (Result<String>) -> Unit,
    ) {
        val subscriptionId = SimResolver.resolveSubscriptionId(context, slot)
        if (!SimResolver.matchesExpectedOperator(context, subscriptionId, expectedOperator)) {
            onResult(Result.failure(OperatorMismatchException(
                "Resolved SIM (slot=$slot, subscriptionId=$subscriptionId) does not match expected operator '$expectedOperator'"
            )))
            return
        }
        val targetTelephonyManager = if (subscriptionId != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            baseTelephonyManager.createForSubscriptionId(subscriptionId)
        } else {
            baseTelephonyManager
        }
        sendUssd(targetTelephonyManager, code, onResult)
    }

    fun sendUssd(telephonyManager: TelephonyManager, code: String, onResult: (Result<String>) -> Unit) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            onResult(Result.failure(UssdUnsupportedException("USSD not supported on Android versions below O")))
            return
        }
        telephonyManager.sendUssdRequest(
            code,
            object : TelephonyManager.UssdResponseCallback() {
                override fun onReceiveUssdResponse(
                    telephonyManager: TelephonyManager,
                    request: String,
                    response: CharSequence,
                ) {
                    onResult(Result.success(response.toString()))
                }

                override fun onReceiveUssdResponseFailed(
                    telephonyManager: TelephonyManager,
                    request: String,
                    failureCode: Int,
                ) {
                    onResult(Result.failure(UssdFailedException("USSD failed with code $failureCode", failureCode)))
                }
            },
            Handler(Looper.getMainLooper()),
        )
    }

    const val EXTRA_SMS_TASK_ID = "sms_task_id"

    /**
     * Same slot resolution as [sendUssdChecked], for [SmsManager] - the
     * backend does not assign a sim_slot for SMS today (SmsTask has no
     * operator concept, see apps.devices.models.SmsTask), so [slot] is
     * always null in practice for now; this exists so that changes only
     * once, not two.
     */
    fun smsManagerFor(context: Context, slot: Int?): SmsManager {
        // Stabilisation RC1 (priorité faible n°13): when no explicit slot is
        // requested (the common case today - the backend never assigns one
        // for SMS, see this method's doc), fall back to the phone's own
        // default SMS subscription resolved through the non-deprecated
        // SubscriptionManager API rather than jumping straight to
        // SmsManager.getDefault(). Same target SIM either way.
        val subscriptionId = SimResolver.resolveSubscriptionId(context, slot)
            ?: defaultSmsSubscriptionId(context)
        return if (subscriptionId != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP_MR1) {
            SmsManager.getSmsManagerForSubscriptionId(subscriptionId)
        } else {
            @Suppress("DEPRECATION")
            SmsManager.getDefault()
        }
    }

    /**
     * Same defensive posture as [SimResolver.resolveSubscriptionId]: null on
     * anything short of a clean resolution (old API level, missing
     * permission, no default reported), so [smsManagerFor] transparently
     * falls back to today's `getDefault()` behavior exactly as before this
     * existed - this only ever *replaces* that deprecated call on a modern,
     * permitted device, never changes which SIM actually gets used.
     */
    private fun defaultSmsSubscriptionId(context: Context): Int? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return null
        if (!DeviceTelemetry.hasPermission(context, Manifest.permission.READ_PHONE_STATE)) return null
        return try {
            val id = SubscriptionManager.getDefaultSmsSubscriptionId()
            if (id == SubscriptionManager.INVALID_SUBSCRIPTION_ID) null else id
        } catch (e: SecurityException) {
            null
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Fire-and-forget from the caller's point of view: this only confirms
     * the OS *accepted* the send request, not that the SMS was actually
     * delivered - the real outcome arrives later via [SmsOutbox], written by
     * [SmsSentReceiver]/[SmsDeliveredReceiver] once the telephony stack
     * reports back (which can take anywhere from milliseconds to minutes,
     * hence the separate, asynchronous reconciliation path in
     * `LocalQueueRepository.reconcileSmsOutcomes` rather than an awaitable
     * callback here like [sendUssd]'s).
     */
    fun sendSms(context: Context, smsManager: SmsManager, taskId: Int, phone: String, message: String) {
        val sentIntent = Intent(context, SmsSentReceiver::class.java).apply {
            putExtra(EXTRA_SMS_TASK_ID, taskId)
        }
        val sentPendingIntent = PendingIntent.getBroadcast(
            context, taskId, sentIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val deliveredIntent = Intent(context, SmsDeliveredReceiver::class.java).apply {
            putExtra(EXTRA_SMS_TASK_ID, taskId)
        }
        // Offset request code so it never collides with the sent PendingIntent's,
        // which is also keyed by taskId.
        val deliveredPendingIntent = PendingIntent.getBroadcast(
            context, taskId + 1_000_000, deliveredIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        smsManager.sendTextMessage(phone, null, message, sentPendingIntent, deliveredPendingIntent)
    }
}
