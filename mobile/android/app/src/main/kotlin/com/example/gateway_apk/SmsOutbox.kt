package com.example.gateway_apk

import android.content.Context
import android.content.SharedPreferences

/**
 * Where [SmsSentReceiver]/[SmsDeliveredReceiver] record an outcome, and
 * where [GatewayForegroundService]'s `drainSmsOutcomes` reads it from.
 * Plain SharedPreferences on purpose: a sent/delivered broadcast can arrive
 * in a short-lived process where neither the Foreground Service nor any
 * Dart engine is currently alive, so recording the outcome must not depend
 * on either - see the Phase C plan's note on why this can't be a live
 * EventChannel push.
 */
object SmsOutbox {
    private const val PREFS_NAME = "gateway_sms_outbox"
    private const val PREFIX_SENT = "sent_"
    private const val PREFIX_DELIVERED = "delivered_"

    private fun prefs(context: Context): SharedPreferences {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    }

    fun recordSent(context: Context, taskId: Int, outcome: String) {
        prefs(context).edit().putString("$PREFIX_SENT$taskId", outcome).apply()
    }

    fun recordDelivered(context: Context, taskId: Int, outcome: String) {
        prefs(context).edit().putString("$PREFIX_DELIVERED$taskId", outcome).apply()
    }

    /** Reads and clears every recorded outcome - called once per Dart tick. */
    fun drainAll(context: Context): List<Map<String, Any?>> {
        val p = prefs(context)
        val all = p.all
        val taskIds = mutableSetOf<Int>()
        for (key in all.keys) {
            val id = key.substringAfterLast('_').toIntOrNull()
            if (id != null) taskIds.add(id)
        }
        val results = taskIds.map { id ->
            mapOf(
                "taskId" to id,
                "sent" to p.getString("$PREFIX_SENT$id", null),
                "delivered" to p.getString("$PREFIX_DELIVERED$id", null),
            )
        }
        if (taskIds.isNotEmpty()) {
            p.edit().clear().apply()
        }
        return results
    }
}
