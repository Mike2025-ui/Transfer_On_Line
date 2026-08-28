package com.example.gateway_apk

import android.Manifest
import android.content.Context
import android.os.Build
import android.telephony.SubscriptionManager

/**
 * Bridges the backend's `sim_slot` (`GatewaySim.slot` - the physical slot
 * index the Scheduler reserved for a transaction, see
 * `apps/core/serializers.py::gateway_task_payload`) to the Android
 * `subscriptionId` that `TelephonyManager.createForSubscriptionId()` /
 * `SmsManager.getSmsManagerForSubscriptionId()` actually need to target a
 * specific SIM on a dual-SIM phone.
 *
 * Returns null - "no preference, use the phone's default SIM", exactly
 * today's pre-multi-SIM behavior - whenever the slot is absent, the API
 * level can't resolve it, permission is missing, or no subscription
 * matches. Never throws, never blocks a dial over a resolution failure.
 */
object SimResolver {
    fun resolveSubscriptionId(context: Context, slot: Int?): Int? {
        if (slot == null) return null
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP_MR1) return null
        if (!DeviceTelemetry.hasPermission(context, Manifest.permission.READ_PHONE_STATE)) return null
        return try {
            val sm = context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as SubscriptionManager
            val subscriptions = sm.activeSubscriptionInfoList ?: return null
            subscriptions.firstOrNull { it.simSlotIndex == slot }?.subscriptionId
        } catch (e: SecurityException) {
            null
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Phase D audit (Critique): before this existed, nothing ever confirmed
     * the SIM actually about to be dialed belongs to the operator the
     * transaction requires - `resolveSubscriptionId` only matches on the
     * physical slot INDEX, and silently falls back to the phone's default
     * SIM (ignoring the requested slot entirely) whenever READ_PHONE_STATE
     * is missing or resolution otherwise fails. Two concrete risks that
     * follow from that: (1) a technician swaps the physical SIM in a slot
     * between the backend reserving it and the dial actually happening
     * (heartbeat only refreshes GatewaySim.operator every ~20s); (2) a
     * revoked/missing permission silently dials on whatever SIM happens to
     * be the phone's default, with no error and no signal back to the
     * backend that targeting was never actually verified.
     *
     * Returns true when [expectedOperator] is null/blank - no check was
     * requested, exactly the pre-existing behavior (older Gateway build,
     * or USE_NEW_TRANSACTION_ENGINE off so the backend never sent an
     * operator to verify against) - additive, never a regression for a
     * caller that doesn't opt in. Otherwise returns true only if the
     * carrier name of the subscription that will ACTUALLY be used matches,
     * and false for every other case, INCLUDING when carrier info can't be
     * read at all: unlike [resolveSubscriptionId], this never trades an
     * unverifiable state for a silent "assume it's fine".
     */
    fun matchesExpectedOperator(context: Context, subscriptionId: Int?, expectedOperator: String?): Boolean {
        if (expectedOperator.isNullOrBlank()) return true
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP_MR1) return false
        if (!DeviceTelemetry.hasPermission(context, Manifest.permission.READ_PHONE_STATE)) return false
        return try {
            val sm = context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as SubscriptionManager
            val subscriptions = sm.activeSubscriptionInfoList ?: return false
            // subscriptionId is what will actually be dialed on (see
            // TelephonyGateway.sendUssdChecked). If slot resolution itself
            // came back null, the dial would fall back to the phone's
            // single active subscription when there's exactly one - that IS
            // the SIM that will be used, so that's what must be checked;
            // with more than one active subscription and no resolved id,
            // which one the platform would pick is genuinely ambiguous, so
            // this deliberately falls through to `null` (rejected) below.
            val info = if (subscriptionId != null) {
                subscriptions.firstOrNull { it.subscriptionId == subscriptionId }
            } else {
                subscriptions.singleOrNull()
            }
            val carrierName = info?.carrierName?.toString()
            if (carrierName.isNullOrBlank()) return false
            // Case-insensitive, either-contains-the-other: tolerates naming
            // drift between what the backend's Operator.name holds (e.g.
            // "Orange") and what the platform reports (e.g. "Orange CI" or
            // "orange-CIV") without attempting a full normalization table.
            carrierName.contains(expectedOperator, ignoreCase = true) ||
                expectedOperator.contains(carrierName, ignoreCase = true)
        } catch (e: SecurityException) {
            false
        } catch (e: Exception) {
            false
        }
    }
}
