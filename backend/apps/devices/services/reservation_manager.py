"""ReservationManager (Phase B, B4) - the ONLY service in the project
allowed to call select_for_update() on Gateway/GatewaySim. Locks both
together (not the SIM alone) so two SIMs on the same physical phone can
never jointly exceed that phone's real capacity - see the Transaction
Engine spec §2/§3 for why.

The "reservation" it hands back is a core.models.TransactionAttempt row in
status='assigned' - there is no separate Reservation model. An attempt IS
the reservation for as long as it sits in a non-terminal status; release()
just advances that same row to a terminal one."""

import logging
from datetime import timedelta

from django.conf import settings as dj_settings
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.core.models import Gateway, TransactionAttempt
from apps.devices.models import GatewaySim
from apps.devices.services.gateway_manager import IN_FLIGHT_STATUSES, GatewayManager

logger = logging.getLogger(__name__)


class ReservationManager:

    @staticmethod
    def reserve(transaction, gateway_sim):
        """Locks the GatewaySim and its parent Gateway atomically
        (SELECT ... FOR UPDATE SKIP LOCKED) and, only if both are still free,
        creates the TransactionAttempt that represents the reservation.
        Returns None - never raises - if the lock was lost or capacity was
        exhausted between selection and reservation; the Scheduler is
        expected to move on to the next ranked candidate."""
        with db_transaction.atomic():
            locked_sim = (
                GatewaySim.objects
                .select_for_update(skip_locked=True)
                .filter(pk=gateway_sim.pk, is_active=True)
                .first()
            )
            if locked_sim is None:
                logger.info('Reservation lost: GatewaySim %s no longer available', gateway_sim.pk)
                return None

            # PostgreSQL rejects SELECT ... FOR UPDATE combined with GROUP BY
            # (which an aggregate annotation like Count() forces) - "FOR
            # UPDATE is not allowed with GROUP BY clause". The lock and the
            # capacity count must therefore be two separate queries, not one
            # annotated+locked queryset. This is safe: every attempt is only
            # ever created here, after this same Gateway row is locked, so a
            # concurrent reserve() against the same gateway (via a sibling
            # SIM) is already serialized by this lock before it can count or
            # create anything.
            locked_gateway = (
                Gateway.objects
                .select_for_update(skip_locked=True)
                .filter(pk=locked_sim.gateway_id, is_active=True)
                .first()
            )
            if locked_gateway is None:
                logger.info('Reservation lost: Gateway for sim %s no longer available', gateway_sim.pk)
                return None

            in_flight = TransactionAttempt.objects.filter(
                gateway_sim__gateway=locked_gateway, status__in=IN_FLIGHT_STATUSES,
            ).count()
            # Phase D4: an interactive USSD scenario (UssdCode with UssdStep
            # rows) occupies the phone's single modem for the whole session
            # duration, unlike a quick simple dial - it must never share a
            # Gateway with anything else in flight, regardless of how high
            # max_concurrent_tasks is configured (that setting exists to
            # stack several quick simple dials, not concurrent interactive
            # sessions). A simple transaction's capacity is unchanged.
            is_interactive = bool(transaction.ussd_code_used_id and transaction.ussd_code_used.steps.exists())
            capacity = 1 if is_interactive else locked_gateway.max_concurrent_tasks
            if in_flight >= capacity:
                logger.info(
                    'Reservation refused: gateway %s at capacity (%s/%s, interactive=%s)',
                    locked_gateway.pk, in_flight, capacity, is_interactive,
                )
                return None

            attempt_number = transaction.attempts.count() + 1
            attempt = TransactionAttempt.objects.create(
                transaction=transaction,
                gateway_sim=locked_sim,
                attempt_number=attempt_number,
                status='assigned',
            )
            logger.info(
                '%s: reserved gateway=%s sim=%s (attempt #%s)',
                transaction.reference, locked_gateway.pk, locked_sim.pk, attempt_number,
            )
            return attempt

    @staticmethod
    def release(attempt, outcome):
        """outcome: one of TransactionAttempt.STATUS_CHOICES' terminal
        values ('success', 'failed', 'expired'). Feeds the outcome back to
        GatewayManager so the SIM's score-relevant counters stay current."""
        attempt.status = outcome
        attempt.completed_at = timezone.now()
        attempt.save(update_fields=['status', 'completed_at'])
        if attempt.gateway_sim_id is not None:
            GatewayManager.record_attempt_outcome(attempt.gateway_sim, success=(outcome == 'success'))
        logger.info('%s: attempt #%s released as %s', attempt.transaction.reference, attempt.attempt_number, outcome)
        return attempt

    @staticmethod
    def release_expired():
        """Periodic sweep, same family as reconcile_pending_payments/
        check_gateway_health - reservations that never reached a terminal
        status within TRANSACTION_ENGINE.TIMEOUT_SECONDS are released as
        'expired' so their Gateway/GatewaySim capacity frees up.

        Business-model audit Phase 3 fix (Blocage 1): a timeout is treated
        exactly like any other classified failure - failure_reason='timeout'
        is recorded and RetryManager schedules a retry immediately, rather
        than waiting for a Gateway result report that may never arrive (the
        phone could be dead/offline). If the real result *does* show up
        later, TransactionResultView's handling of an already-'expired'
        attempt (see _handle_late_result_after_expiry) corrects the record
        without ever calling release()/RetryManager a second time for the
        same attempt - no double SIM counting, no double retry."""
        # Local imports: avoids a circular import (retry_manager -> scheduler
        # -> reservation_manager), same defensive pattern already used by
        # Transaction.sync_from_payment() in apps/core/models.py.
        from apps.core.services.retry_manager import RetryManager
        from apps.core.services.transaction_state_machine import TransactionStateMachine

        timeout = dj_settings.TRANSACTION_ENGINE['TIMEOUT_SECONDS']
        cutoff = timezone.now() - timedelta(seconds=timeout)
        stale = TransactionAttempt.objects.select_related('transaction').filter(
            status__in=IN_FLIGHT_STATUSES, created_at__lt=cutoff,
        )
        released = 0
        for attempt in stale:
            attempt.failure_reason = 'timeout'
            attempt.save(update_fields=['failure_reason'])
            ReservationManager.release(attempt, 'expired')
            transaction = attempt.transaction
            if not TransactionStateMachine.is_terminal(transaction.status):
                RetryManager.handle_failed_attempt(transaction, attempt)
            released += 1
        if released:
            logger.warning('Released %s expired reservation(s) (timeout=%ss)', released, timeout)
        return released
