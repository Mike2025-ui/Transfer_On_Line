"""GatewayScoreService (Phase B, B4) - the only place a ranking formula for
GatewaySim candidates is allowed to live. The Scheduler calls rank(); it
never computes a score itself, so the formula can change without touching
the Scheduler's logic (exclusion, reservation, retry-exclusion).

Every component is normalized to [0, 1] and a missing data point scores
neutral (0.5) rather than 0 or 1 - an older mobile app build that hasn't
reported battery/signal yet must not be unfairly punished (or favored) by
data it simply doesn't send. Weighting constants live here, not in
settings.py: they are algorithm parameters that change with the code, not
operational thresholds an operator would tune at runtime (see the
Transaction Engine spec §2bis for that distinction)."""

from django.conf import settings as dj_settings
from django.utils import timezone

WEIGHTS = {
    'battery': 0.15,
    'signal': 0.10,
    'load': 0.25,
    'success_rate': 0.20,
    'reliability': 0.15,
    'recency': 0.15,
}


def _normalize_battery(level):
    if level is None:
        return 0.5
    return max(0.0, min(1.0, level / 100))


def _normalize_signal(strength):
    if strength is None:
        return 0.5
    # Typical cellular RSSI range: -113 dBm (worst) to -51 dBm (best).
    clamped = max(-113, min(-51, strength))
    return (clamped + 113) / (-51 + 113)


def _normalize_load(gateway_sim):
    """Expects `in_flight` to already be annotated on gateway_sim (see
    GatewayManager.eligible_sims) - gateway-level backlog, not per-SIM."""
    max_tasks = gateway_sim.gateway.max_concurrent_tasks or 1
    in_flight = getattr(gateway_sim, 'in_flight', 0) or 0
    ratio = min(1.0, in_flight / max_tasks)
    return 1.0 - ratio  # lower load -> higher score


def _normalize_success_rate(gateway_sim):
    total = gateway_sim.success_count + gateway_sim.failure_count
    if total == 0:
        return 0.5  # no history yet - neutral, not penalized for being new
    return gateway_sim.success_count / total


def _normalize_reliability(gateway_sim):
    max_failures = dj_settings.GATEWAY_MANAGER['MAX_CONSECUTIVE_FAILURES'] or 1
    ratio = min(1.0, gateway_sim.consecutive_failures / max_failures)
    return 1.0 - ratio


def _normalize_recency(gateway_sim):
    last_heartbeat = gateway_sim.gateway.last_heartbeat
    if last_heartbeat is None:
        return 0.0
    stale_seconds = dj_settings.GATEWAY_MANAGER['HEARTBEAT_STALE_SECONDS'] or 1
    age_seconds = (timezone.now() - last_heartbeat).total_seconds()
    return max(0.0, 1.0 - age_seconds / stale_seconds)


class GatewayScoreService:

    @staticmethod
    def score(gateway_sim):
        """A single candidate's score, higher is better. Callers normally
        want rank() instead - this is exposed separately for debugging/
        dashboard display of why a given SIM was (or wasn't) picked."""
        components = {
            'battery': _normalize_battery(gateway_sim.gateway.battery_level),
            'signal': _normalize_signal(gateway_sim.gateway.signal_strength),
            'load': _normalize_load(gateway_sim),
            'success_rate': _normalize_success_rate(gateway_sim),
            'reliability': _normalize_reliability(gateway_sim),
            'recency': _normalize_recency(gateway_sim),
        }
        return sum(WEIGHTS[key] * value for key, value in components.items())

    @staticmethod
    def rank(queryset):
        """Best-scored first. Materializes the queryset once (candidates are
        already capped upstream by eligible_sims()'s filters, not by size at
        the pool level, so this stays cheap regardless of total pool size)."""
        candidates = list(queryset)
        candidates.sort(key=GatewayScoreService.score, reverse=True)
        return candidates
