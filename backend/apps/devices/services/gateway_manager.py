"""GatewayManager - sole authority on the state of the Gateway/GatewaySim
pool (Phase B, B3). Exposes facts, decides nothing: it never picks a
Gateway for a transaction (that is the Scheduler's job, B4) and never
locks a row for reservation (that is the Reservation Manager's job, B4).

See the Transaction Engine & Gateway Manager specification, §2, for the
architecture this implements."""

import logging
from datetime import timedelta

from django.conf import settings as dj_settings
from django.db.models import Avg, Count, F, Q
from django.utils import timezone

from apps.core.models import Gateway, Operator, TransactionAttempt
from apps.devices.models import GatewaySim
from apps.devices.services.gateway_score import GatewayScoreService

logger = logging.getLogger(__name__)

_MISSING = object()

IN_FLIGHT_STATUSES = ['assigned', 'dispatched', 'executing']

# (payload key, model field, caster). Anything absent from a heartbeat's
# `details` is left untouched on the Gateway row - an older mobile app build
# that never sends these keeps working exactly as it did before B2/B3.
_HEARTBEAT_TELEMETRY_FIELDS = [
    ('battery_level', 'battery_level', int),
    ('temperature', 'temperature', float),
    ('ram_available_mb', 'ram_available_mb', int),
    ('storage_available_mb', 'storage_available_mb', int),
    ('network_type', 'network_type', str),
    ('signal_strength', 'signal_strength', int),
    ('ip_address', 'ip_address', str),
    ('app_version', 'app_version', str),
    ('is_busy', 'is_busy', lambda v: v in [True, 'true', 'True', '1', 1]),
    ('current_task_count', 'reported_task_count', int),
]


def _apply_heartbeat_telemetry(gateway, details):
    touched = []
    for payload_key, field_name, caster in _HEARTBEAT_TELEMETRY_FIELDS:
        value = details.get(payload_key, _MISSING)
        if value is _MISSING or value is None:
            continue
        try:
            setattr(gateway, field_name, caster(value))
            touched.append(field_name)
        except (TypeError, ValueError):
            continue  # malformed value from a misbehaving client - ignore, don't 500
    return touched


def _apply_heartbeat_sims(gateway, sims_payload):
    if not sims_payload:
        return
    for sim_info in sims_payload:
        operator_name = (sim_info.get('operator') or '').strip()
        if not operator_name:
            continue
        slot = int(sim_info.get('slot') or 0)
        operator, _ = Operator.objects.get_or_create(
            name=operator_name.title(),
            defaults={'code': operator_name.lower().replace(' ', '_')},
        )
        GatewaySim.objects.update_or_create(
            gateway=gateway, slot=slot,
            defaults={'operator': operator, 'msisdn': sim_info.get('msisdn') or ''},
        )


class GatewayManager:

    @staticmethod
    def register_heartbeat(*, gateway, payload):
        """Writes telemetry onto an already-authenticated Gateway row - the
        caller (GatewayHeartbeatView) resolves `gateway` from the request's
        secret before this ever runs (business-model audit Phase 7). This
        function no longer chooses OR creates a row from anything in
        `payload` - `gateway_uuid`/`gateway_id` are self-declared, unverified
        strings, and trusting them for row selection is exactly the
        impersonation/auto-provisioning vector Phase 7 closes. `details.uuid`
        may still update `gateway.host` below - purely informational
        telemetry once identity itself is no longer in question."""
        details = payload.get('details') or {}
        gateway_uuid = details.get('uuid') or payload.get('gateway_uuid')
        phone_number = details.get('phone_number') or payload.get('phone_number') or 'Gateway Android'
        operator_name = details.get('operator') or payload.get('operator') or 'Gateway'

        gateway.name = f'{operator_name} - {phone_number}'
        if gateway_uuid:
            gateway.host = gateway_uuid
        gateway.status = payload.get('status') or 'online'
        gateway.last_heartbeat = timezone.now()
        touched_fields = _apply_heartbeat_telemetry(gateway, details)
        gateway.save(update_fields=[
            'name', 'host', 'status', 'last_heartbeat', *touched_fields,
        ] if touched_fields else None)
        _apply_heartbeat_sims(gateway, details.get('sims'))
        return gateway

    @staticmethod
    def _stale_cutoff():
        seconds = dj_settings.GATEWAY_MANAGER['HEARTBEAT_STALE_SECONDS']
        return timezone.now() - timedelta(seconds=seconds)

    @staticmethod
    def available_gateways():
        """Online, active gateways with a fresh heartbeat - pure inventory,
        no operator/SIM/capacity filtering."""
        return Gateway.objects.filter(
            is_active=True, status='online', last_heartbeat__gte=GatewayManager._stale_cutoff(),
        )

    @staticmethod
    def eligible_sims(operator, exclude_sim_ids=()):
        """Facts only, NOT ranked, NOT locked: operator match, gateway online
        with a fresh heartbeat, SIM active, battery above LOW_BATTERY_THRESHOLD
        (or unknown - an older app build that hasn't reported battery yet
        must not be excluded from the pool entirely), backlog below
        MAX_QUEUE. This is what the Scheduler (B4) will rank and the
        Reservation Manager (B4) will lock - GatewayManager does neither."""
        cfg = dj_settings.GATEWAY_MANAGER
        qs = GatewaySim.objects.filter(
            operator=operator,
            is_active=True,
            gateway__is_active=True,
            gateway__status='online',
            gateway__last_heartbeat__gte=GatewayManager._stale_cutoff(),
        ).exclude(id__in=exclude_sim_ids).filter(
            Q(gateway__battery_level__isnull=True) | Q(gateway__battery_level__gte=cfg['LOW_BATTERY_THRESHOLD'])
        ).annotate(
            # Gateway-level backlog, not per-SIM: a phone with two SIMs still
            # only dials one USSD session at a time, so a task queued on
            # either SIM counts against the same phone's capacity. Traverses
            # GatewaySim -> gateway -> sims (all siblings, incl. self) ->
            # attempts; distinct=True because that join can produce duplicate
            # rows across sibling SIMs.
            in_flight=Count(
                'gateway__sims__attempts',
                filter=Q(gateway__sims__attempts__status__in=IN_FLIGHT_STATUSES),
                distinct=True,
            ),
        ).filter(
            in_flight__lt=cfg['MAX_QUEUE'],
        ).select_related('gateway', 'operator').order_by(
            F('last_used_at').asc(nulls_first=True), 'pk',
        )
        # Deterministic base ordering matters even though GatewayScoreService
        # does the real ranking: Python's sort is stable, so when two
        # candidates score exactly equal (e.g. neither has reported battery/
        # signal yet), whichever comes first here wins - without this,
        # that tiebreak would depend on unspecified database row order and
        # be irreproducible from one call to the next. nulls_first=True is
        # explicit rather than relying on each backend's default NULL
        # ordering (SQLite and PostgreSQL disagree on it), so dev (SQLite)
        # and production (PostgreSQL) resolve ties identically. A never-used
        # SIM is naturally preferred over one just used a second ago,
        # spreading load instead of hammering whichever row the DB happens
        # to return first.
        return qs

    @staticmethod
    def select_operator_gateway(operator):
        """Business-model audit Phase 7.2: the legacy-path (USE_NEW_TRANSACTION_
        ENGINE=false) equivalent of Scheduler.select() - same trusted chain
        (eligible_sims() -> GatewayScoreService.rank()), so both engines share
        one source of truth for "which Gateways may serve this operator"
        instead of two divergent implementations. Deliberately creates no
        TransactionAttempt/reservation - the legacy path never did either -
        this only ever answers the question, it never locks anything.
        Returns None if no SIM is eligible for this operator; callers must
        never fall back to a Gateway of a different operator on that."""
        ranked = GatewayScoreService.rank(GatewayManager.eligible_sims(operator))
        return ranked[0].gateway if ranked else None

    @staticmethod
    def gateway_state(gateway):
        """One gateway's current state - status, telemetry, capacity, load,
        SIM. Read-only projection, not a queryset - meant for the dashboard
        and for debugging, not for the Scheduler's hot path (which should
        call eligible_sims() directly)."""
        in_flight = TransactionAttempt.objects.filter(
            gateway_sim__gateway=gateway, status__in=IN_FLIGHT_STATUSES,
        ).count()
        return {
            'id': gateway.id,
            'name': gateway.name,
            'status': gateway.status,
            'is_active': gateway.is_active,
            'is_online': gateway in GatewayManager.available_gateways(),
            'last_heartbeat': gateway.last_heartbeat,
            'battery_level': gateway.battery_level,
            'temperature': gateway.temperature,
            'ram_available_mb': gateway.ram_available_mb,
            'storage_available_mb': gateway.storage_available_mb,
            'ip_address': gateway.ip_address,
            'network_type': gateway.network_type,
            'signal_strength': gateway.signal_strength,
            'app_version': gateway.app_version,
            'max_concurrent_tasks': gateway.max_concurrent_tasks,
            'in_flight': in_flight,
            'sims': [
                {
                    'id': sim.id, 'slot': sim.slot, 'operator': sim.operator.name,
                    'msisdn': sim.msisdn, 'is_active': sim.is_active,
                    'success_count': sim.success_count, 'failure_count': sim.failure_count,
                    'consecutive_failures': sim.consecutive_failures,
                }
                for sim in gateway.sims.select_related('operator')
            ],
        }

    @staticmethod
    def pool_stats():
        """Aggregate counts for the dashboard/observability - not consumed
        by the Scheduler."""
        total = Gateway.objects.filter(is_active=True).count()
        online = GatewayManager.available_gateways().count()
        by_operator = list(
            GatewaySim.objects.filter(is_active=True)
            .values('operator__name')
            .annotate(count=Count('id'))
            .order_by('operator__name')
        )
        avg_battery = Gateway.objects.filter(
            is_active=True, battery_level__isnull=False,
        ).aggregate(avg=Avg('battery_level'))['avg']
        return {
            'total_gateways': total,
            'online_gateways': online,
            'offline_gateways': total - online,
            'sims_by_operator': by_operator,
            'average_battery_level': round(avg_battery, 1) if avg_battery is not None else None,
        }

    @staticmethod
    def record_attempt_outcome(gateway_sim, success):
        """Not called by anything yet - no Scheduler/TransactionAttempt flow
        is wired up until B4 - but the contract must exist now per the
        validated architecture. F() expressions: safe under concurrent
        updates from multiple gateways finishing attempts at once."""
        if success:
            gateway_sim.success_count = F('success_count') + 1
            gateway_sim.consecutive_failures = 0
        else:
            gateway_sim.failure_count = F('failure_count') + 1
            gateway_sim.consecutive_failures = F('consecutive_failures') + 1
        gateway_sim.last_used_at = timezone.now()
        gateway_sim.save(update_fields=['success_count', 'failure_count', 'consecutive_failures', 'last_used_at'])
        gateway_sim.refresh_from_db(fields=['success_count', 'failure_count', 'consecutive_failures'])
