"""RetryManager (Phase B) - decides WHETHER a failed TransactionAttempt is
worth retrying, WHEN (backoff delay), and WHY (logged as a TransactionEvent
for every decision, not just the ones that lead to a retry). It never picks
a Gateway/SIM itself: dispatch_due_retries() calls Scheduler.select(), which
already excludes every SIM already tried for that transaction (see
apps.devices.services.scheduler.Scheduler.select). Keeping selection solely
in the Scheduler is deliberate - see the Transaction Engine spec §2.

Not wired to any live view yet - same 'independently testable foundation'
scope as the Scheduler in B4. Nothing currently produces a failed
TransactionAttempt outside of tests (ExecuteTransactionView/
TransactionResultView still use the pre-Scheduler flow), so there is nothing
live for this to react to until that gets connected."""

import logging
from datetime import timedelta

from django.conf import settings as dj_settings
from django.utils import timezone

from apps.core.models import Transaction, TransactionEvent
from apps.devices.services.gateway_manager import GatewayManager
from apps.devices.services.scheduler import Scheduler

logger = logging.getLogger(__name__)

# Mirrors TransactionAttempt.FAILURE_REASON_CHOICES: retrying an invalid
# recipient number can never succeed, so it is excluded regardless of how
# many attempts remain.
NON_RETRYABLE_FAILURE_REASONS = {'invalid_number'}


class RetryManager:

    @staticmethod
    def should_retry(transaction, failure_reason):
        if failure_reason in NON_RETRYABLE_FAILURE_REASONS:
            return False
        max_retry = dj_settings.TRANSACTION_ENGINE['MAX_RETRY']
        return transaction.attempts.count() < max_retry

    @staticmethod
    def next_delay_seconds(transaction):
        """RETRY_BACKOFF is a list of per-attempt delays (e.g. [30, 45, 60]).
        Attempts beyond the list reuse its last value rather than erroring -
        see the Transaction Engine spec §2's note on RETRY_BACKOFF vs
        MAX_RETRY being independent settings."""
        backoff = dj_settings.TRANSACTION_ENGINE['RETRY_BACKOFF']
        index = max(0, transaction.attempts.count() - 1)
        return backoff[index] if index < len(backoff) else backoff[-1]

    @staticmethod
    def handle_failed_attempt(transaction, failed_attempt):
        """Called after a TransactionAttempt has been released as 'failed'
        (see ReservationManager.release). Decides retry eligibility and
        delay, records the decision, and sets transaction.next_retry_at -
        it does not dispatch the retry itself; dispatch_due_retries() (run
        periodically, once wired) does that once the delay has elapsed."""
        if not RetryManager.should_retry(transaction, failed_attempt.failure_reason):
            TransactionEvent.log(
                transaction, 'retry_exhausted',
                failure_reason=failed_attempt.failure_reason, attempt_number=failed_attempt.attempt_number,
                attempts_made=transaction.attempts.count(),
            )
            if transaction.next_retry_at is not None:
                transaction.next_retry_at = None
                transaction.save(update_fields=['next_retry_at'])
            logger.info('%s: retry exhausted after attempt #%s', transaction.reference, failed_attempt.attempt_number)
            return None

        delay = RetryManager.next_delay_seconds(transaction)
        retry_at = timezone.now() + timedelta(seconds=delay)
        transaction.next_retry_at = retry_at
        transaction.save(update_fields=['next_retry_at'])
        TransactionEvent.log(
            transaction, 'retry_scheduled',
            failure_reason=failed_attempt.failure_reason, attempt_number=failed_attempt.attempt_number,
            delay_seconds=delay, retry_at=retry_at.isoformat(),
        )
        logger.info('%s: retry scheduled in %ss (after attempt #%s)', transaction.reference, delay, failed_attempt.attempt_number)
        return retry_at

    @staticmethod
    def due_for_retry():
        return Transaction.objects.filter(next_retry_at__isnull=False, next_retry_at__lte=timezone.now())

    @staticmethod
    def dispatch_due_retries():
        """Would be called by a periodic sweep, same family as
        reconcile_pending_payments/check_gateway_health - not wired to a
        management command yet, kept independently testable per the brief.

        On a successful reservation, tx.gateway is reassigned to the newly
        selected attempt's gateway - the transaction stayed 'pending' the
        whole time (see ExecuteTransactionView/TransactionResultView's
        cutover), so this is what puts it back in front of whichever gateway
        polls PendingTransactionsView next (that endpoint filters strictly
        by gateway__host, so without this reassignment the retry would be
        reserved but never actually surfaced to any phone)."""
        results = {}
        for transaction in RetryManager.due_for_retry():
            transaction.next_retry_at = None
            transaction.save(update_fields=['next_retry_at'])

            # Business-model audit Phase 7.2: `dispatched` is the one name
            # both branches below write to - never reuse a name from the
            # previous loop iteration's branch (a transaction that takes the
            # `else` branch must never inherit a stale TransactionAttempt
            # from an earlier, different transaction that took the `if`
            # branch this same call).
            if dj_settings.USE_NEW_TRANSACTION_ENGINE:
                dispatched = Scheduler.select(transaction, transaction.operator)
                if dispatched is not None:
                    transaction.gateway = dispatched.gateway_sim.gateway
                    transaction.save(update_fields=['gateway', 'updated_at'])
                    TransactionEvent.log(
                        transaction, 'retry_dispatched',
                        attempt_number=dispatched.attempt_number, gateway_sim_id=dispatched.gateway_sim_id,
                    )
                else:
                    # Business-model audit Phase 3 (Blocage 3): still no
                    # eligible Gateway/SIM for this operator - this is an
                    # infrastructure gap, not a business failure of the
                    # transaction, so it is requeued indefinitely (no MAX_RETRY
                    # cap here, unlike a failed dial) rather than left orphaned
                    # with next_retry_at cleared above and never checked again.
                    transaction.next_retry_at = timezone.now() + timedelta(
                        seconds=RetryManager.next_delay_seconds(transaction),
                    )
                    transaction.save(update_fields=['next_retry_at'])
                    TransactionEvent.log(
                        transaction, 'retry_no_gateway_available',
                        next_retry_at=transaction.next_retry_at.isoformat(),
                    )
            else:
                # Business-model audit Phase 7.2: legacy-origin transactions
                # only ever reach here via the "no gateway available" branch
                # ExecuteTransactionView's legacy path now also queues (see
                # that view) - never via a failed dial (legacy dial failures
                # still resolve straight to 'failed', unchanged, see
                # TransactionResultView). No TransactionAttempt/reservation
                # is created here either - GatewayManager.select_operator_
                # gateway() is a pure lookup, same as the legacy path already
                # used at creation time.
                dispatched = GatewayManager.select_operator_gateway(transaction.operator)
                if dispatched is not None:
                    transaction.gateway = dispatched
                    transaction.save(update_fields=['gateway', 'updated_at'])
                    TransactionEvent.log(
                        transaction, 'retry_dispatched',
                        mechanism='legacy_selector', gateway_id=dispatched.id,
                    )
                else:
                    transaction.next_retry_at = timezone.now() + timedelta(
                        seconds=RetryManager.next_delay_seconds(transaction),
                    )
                    transaction.save(update_fields=['next_retry_at'])
                    TransactionEvent.log(
                        transaction, 'retry_no_gateway_available',
                        next_retry_at=transaction.next_retry_at.isoformat(),
                    )
            results[transaction.pk] = dispatched
        return results
