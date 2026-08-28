package com.example.gateway_apk

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Restarts [GatewayForegroundService] after the phone reboots - this app's
 * whole purpose is to run as an always-on relay, so a reboot (power outage,
 * OS update, manual restart) must never require a human to reopen the app.
 *
 * `BOOT_COMPLETED` receivers are one of the few background-start paths
 * Android's API 31+ restrictions still explicitly exempt - calling
 * `startForegroundService()` from here is documented as safe, unlike most
 * other background-triggered starts.
 *
 * Direct Boot caveat (worth documenting, not fixable in code): on a
 * non-encryption-aware app, this receiver only fires after the user's first
 * unlock following boot - a sideloaded field phone that loses power will
 * not resume until someone enters its lock-screen credential once. This is
 * an onboarding/operational checklist item (disable the lock screen, or
 * ensure the phone is minded after an outage), not something this receiver
 * can work around.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val desired = GatewayForegroundService.watchdogPrefs(context)
            .getBoolean(GatewayForegroundService.KEY_DESIRED_STATE, true)
        if (desired) {
            GatewayForegroundService.start(context)
        }
    }
}
