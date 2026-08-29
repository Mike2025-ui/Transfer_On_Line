"""TransactionStateMachine - the single authority for every
Transaction.status change in the project. Nothing else should assign
`transaction.status = ...` directly; every call site that used to (see
Transaction.sync_from_payment, apps.devices.views.ExecuteTransactionView,
apps.devices.views.TransactionResultView) now goes through transition().

Scope note: this governs the CURRENT status vocabulary only
(pending/processing/success/failed/cancelled - the one apps/frontend's
BackendTransactionResult.isPending/isSuccess already know how to read).
The richer vocabulary proposed in the Transaction Engine spec
(queued/assigned/dispatched/executing/...) is intentionally NOT introduced
here - that expansion belongs together with actually wiring the Scheduler
into ExecuteTransactionView, not before, or the Flutter client's status
checks would silently stop matching intermediate states it doesn't expect."""

import logging

from apps.core.models import Notification, Transaction, TransactionEvent

logger = logging.getLogger(__name__)


class InvalidTransitionError(Exception):
    pass


class TransactionStateMachine:
    # {current_status: {allowed destinations}}. Terminal states map to an
    # empty set. Reflexive transitions (status -> itself) are always allowed
    # regardless of this table - see can_transition() - since several
    # existing call sites re-apply the same status idempotently (e.g.
    # sync_from_payment() re-affirming 'pending').
    TRANSITIONS = {
        'pending': {'processing', 'success', 'failed', 'cancelled'},
        'processing': {'success', 'failed', 'cancelled'},
        'success': set(),
        'failed': set(),
        'cancelled': set(),
    }

    @staticmethod
    def can_transition(current_status, new_status):
        if current_status == new_status:
            return True
        return new_status in TransactionStateMachine.TRANSITIONS.get(current_status, set())

    @staticmethod
    def is_terminal(status):
        """True for a status with no outgoing transitions (success/failed/
        cancelled today). Phase D audit (Critique n°3): used by
        TransactionResultView to recognize a duplicate/retried result report
        for an already-resolved transaction and skip re-running its side
        effects, instead of just re-deriving this from TRANSITIONS inline at
        each call site."""
        return not TransactionStateMachine.TRANSITIONS.get(status, set())

    @staticmethod
    def transition(transaction, new_status, *, reason='', **metadata):
        """Raises InvalidTransitionError instead of silently applying an
        illegal change - an invalid transition is a bug to surface loudly
        (logged, visible to Sentry if configured), not something to paper
        over. Always logs a TransactionEvent, including for the reflexive
        (no-op) case, so the audit trail shows every time this was called,
        not just every time something actually changed."""
        previous_status = transaction.status
        if not TransactionStateMachine.can_transition(previous_status, new_status):
            raise InvalidTransitionError(
                f"{transaction.reference}: cannot transition from '{previous_status}' to '{new_status}'"
            )

        if previous_status != new_status:
            transaction.status = new_status
            transaction.save(update_fields=['status', 'updated_at'])
            logger.info('%s: %s -> %s', transaction.reference, previous_status, new_status)
            if TransactionStateMachine.is_terminal(new_status):
                # Business-model audit: the ONLY place a Notification is
                # ever created for a Transaction - genuinely confirmed
                # (this is the single authority for every status change),
                # never optimistic, never duplicated for a reflexive
                # re-apply of the same terminal status. No-op for a
                # Transaction with no authenticated owner (see
                # Notification.create_for_transaction_status's doc).
                Notification.create_for_transaction_status(transaction, new_status)

        TransactionEvent.log(
            transaction, 'status_changed',
            from_status=previous_status, to_status=new_status, reason=reason, **metadata,
        )
        return transaction
