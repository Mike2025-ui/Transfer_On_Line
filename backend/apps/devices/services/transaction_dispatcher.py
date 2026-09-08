import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.core.models import Transaction, TransactionEvent
from apps.devices.services.scheduler import Scheduler

logger = logging.getLogger(__name__)


class ScenarioConfigurationError(ValueError):
    """Raised before payment when the configured USSD scenario is incomplete."""


def validate_scenario_code(code):
    if code is None:
        raise ScenarioConfigurationError('Aucun code USSD configure.')

    steps = list(code.steps.prefetch_related('fields').order_by('order'))
    if not steps:
        return

    expected_order = list(range(1, len(steps) + 1))
    actual_order = [step.order for step in steps]
    if actual_order != expected_order:
        raise ScenarioConfigurationError('La sequence USSD contient une etape manquante.')

    for index, step in enumerate(steps):
        if step.step_type == 'INPUT' and not step.fields.exists():
            raise ScenarioConfigurationError(f"L'etape {step.order} ne contient aucun champ.")
        if step.step_type == 'FINAL_FIELD' and step.fields.exists():
            raise ScenarioConfigurationError(
                f"L'etape finale {step.order} ne doit pas contenir de champ."
            )
        if step.step_type == 'FINAL_FIELD' and index != len(steps) - 1:
            raise ScenarioConfigurationError("L'etape finale doit etre la derniere.")


def validate_transaction_scenario(transaction):
    validate_scenario_code(transaction.ussd_code_used)


def dispatch_paid_transaction(transaction):
    """Assign exactly one compatible Gateway/SIM after payment acceptance."""
    transaction = Transaction.objects.select_related(
        'operator', 'ussd_code_used', 'payment',
    ).get(pk=transaction.pk)
    if transaction.payment_id is None or transaction.payment.status != 'accepted':
        return None
    if transaction.status in ('success', 'failed', 'cancelled'):
        return None
    if transaction.gateway_id is not None and transaction.attempts.filter(
        status__in=('assigned', 'dispatched', 'executing'),
    ).exists():
        return transaction.attempts.filter(
            status__in=('assigned', 'dispatched', 'executing'),
        ).order_by('-attempt_number').first()

    attempt = Scheduler.select(transaction, transaction.operator)
    if attempt is None:
        transaction.next_retry_at = timezone.now() + timedelta(
            seconds=settings.TRANSACTION_ENGINE['RETRY_BACKOFF'][0],
        )
        transaction.save(update_fields=['next_retry_at', 'updated_at'])
        TransactionEvent.log(
            transaction,
            'gateway_waiting_after_payment',
            payment_status=transaction.payment.status,
            next_retry_at=transaction.next_retry_at.isoformat(),
        )
        return None

    transaction.gateway = attempt.gateway_sim.gateway
    transaction.next_retry_at = None
    transaction.save(update_fields=['gateway', 'next_retry_at', 'updated_at'])
    TransactionEvent.log(
        transaction,
        'gateway_assigned_after_payment',
        gateway_id=transaction.gateway_id,
        gateway_sim_id=attempt.gateway_sim_id,
        attempt_number=attempt.attempt_number,
    )
    return attempt


def fail_interactive_attempt(attempt, error_code, response_body):
    """Close a broken interactive step and schedule the single retry."""
    from apps.core.models import TransactionAttempt
    from apps.core.services.retry_manager import RetryManager
    from apps.core.services.transaction_state_machine import TransactionStateMachine
    from apps.devices.services.reservation_manager import ReservationManager

    if error_code not in dict(TransactionAttempt.FAILURE_REASON_CHOICES):
        error_code = 'unknown'
    attempt.failure_reason = error_code
    attempt.raw_response = str(response_body)
    attempt.save(update_fields=['failure_reason', 'raw_response'])
    ReservationManager.release(attempt, 'failed')
    retry_at = RetryManager.handle_failed_attempt(attempt.transaction, attempt)
    if retry_at is not None:
        return 'RETRY_SCHEDULED'
    TransactionStateMachine.transition(
        attempt.transaction,
        'failed',
        reason='ussd_step_failed',
        error_code=error_code,
    )
    return 'FAILED'
