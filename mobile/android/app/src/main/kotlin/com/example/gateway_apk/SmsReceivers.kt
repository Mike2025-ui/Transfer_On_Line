package com.example.gateway_apk

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Fired by the `sentIntent` [android.app.PendingIntent] passed to
 * [android.telephony.SmsManager.sendTextMessage] - the telephony stack sets
 * this receiver's result code to [Activity.RESULT_OK] or one of
 * `SmsManager.RESULT_ERROR_*` once it knows whether the SMS left the
 * device. Records into [SmsOutbox] rather than acting directly: this
 * receiver's process may not have any Dart engine (or even
 * [GatewayForegroundService]) alive at the moment it fires.
 */
class SmsSentReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val taskId = intent.getIntExtra(TelephonyGateway.EXTRA_SMS_TASK_ID, -1)
        if (taskId < 0) return
        val outcome = if (resultCode == Activity.RESULT_OK) "sent" else "failed"
        SmsOutbox.recordSent(context, taskId, outcome)
    }
}

/**
 * Fired by the `deliveryIntent` once the carrier confirms (or fails to
 * confirm) delivery to the handset - a separate, later signal from "sent".
 * See [SmsSentReceiver]'s doc for why this only ever writes to [SmsOutbox].
 */
class SmsDeliveredReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val taskId = intent.getIntExtra(TelephonyGateway.EXTRA_SMS_TASK_ID, -1)
        if (taskId < 0) return
        val outcome = if (resultCode == Activity.RESULT_OK) "delivered" else "not_delivered"
        SmsOutbox.recordDelivered(context, taskId, outcome)
    }
}
