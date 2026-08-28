"""Scheduler (Phase B, B4) - decides which GatewaySim serves a given
Transaction. Owns no data of its own and posts no database lock itself:
GatewayManager supplies the facts, GatewayScoreService ranks them,
ReservationManager locks and commits the winner. See the Transaction
Engine & Gateway Manager specification, §2/§3, for the full picture.

Not wired into ExecuteTransactionView yet - see the B4 implementation
report for why that is a deliberately separate decision, not an oversight."""

import logging

from apps.core.models import TransactionAttempt
from apps.devices.services.gateway_manager import GatewayManager
from apps.devices.services.gateway_score import GatewayScoreService
from apps.devices.services.reservation_manager import ReservationManager

logger = logging.getLogger(__name__)


class Scheduler:

    @staticmethod
    def select(transaction, operator):
        """Picks the best-scored eligible GatewaySim for `operator` and
        reserves it for `transaction`. Returns the TransactionAttempt
        (the reservation) on success, or None if no candidate could be
        reserved - the transaction should stay 'queued' for a later retry
        of this same call (see run_queue_sweep's docstring below), not be
        treated as a hard failure.

        SIMs already tried for this exact transaction are excluded
        automatically - retrying the same SIM that just failed almost never
        helps (see the Transaction Engine spec §5)."""
        exclude_sim_ids = list(
            TransactionAttempt.objects
            .filter(transaction=transaction)
            .exclude(gateway_sim=None)
            .values_list('gateway_sim_id', flat=True)
        )
        candidates = GatewayManager.eligible_sims(operator, exclude_sim_ids=exclude_sim_ids)
        ranked = GatewayScoreService.rank(candidates)

        for gateway_sim in ranked:
            attempt = ReservationManager.reserve(transaction, gateway_sim)
            if attempt is not None:
                return attempt
            # lock lost or capacity exhausted between ranking and reserving -
            # try the next-best candidate rather than giving up immediately.

        logger.info('%s: no gateway/sim available for operator=%s', transaction.reference, operator)
        return None

    @staticmethod
    def run_queue_sweep(transactions):
        """Not wired to anything yet (no caller creates 'queued' Transactions
        outside of tests until the Transaction Engine's dispatch()/retry()
        exist, later in Phase B) - provided now so B4 is independently
        testable per the brief, and so the Transaction Engine has a stable
        method to call against once it lands. Retries select() for each
        transaction passed in; the caller decides what "queued" means and
        which transactions qualify."""
        results = {}
        for transaction in transactions:
            results[transaction.pk] = Scheduler.select(transaction, transaction.operator)
        return results
