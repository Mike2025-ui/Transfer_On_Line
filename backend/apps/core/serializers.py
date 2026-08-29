from django.conf import settings as dj_settings

from apps.core.models import UssdCode, UssdCodeNotConfigured


def resolve_ussd_code(operator, service, amount=None):
    """Looks up the UssdCode to use for (operator, service[, amount]) - never
    raises, returns None if nothing is configured. Used for preflight checks
    before any side effect (see ExecuteTransactionView), where a clean 400
    response is preferable to an exception raised after a payment has
    already been initiated with the provider.

    3-level cascade (business-model audit, Operator -> Service -> Amount):
    1. exact (operator, service, amount) match - an operator/service whose
       real dial code differs per bundle price.
    2. (operator, service, amount=NULL) - the generic row that works for any
       montant via the {montant} template variable; this is the only tier
       that has ever existed before `amount` was added, so passing
       amount=None (the default) reproduces the exact pre-existing behavior.
    3. (operator, service=None) - the operator-wide fallback, unchanged,
       never amount-filtered."""
    code = None
    if amount is not None:
        code = UssdCode.objects.filter(operator=operator, service=service, amount=amount, is_active=True).first()
    if code is None:
        code = UssdCode.objects.filter(operator=operator, service=service, amount__isnull=True, is_active=True).first()
    if code is None:
        code = UssdCode.objects.filter(operator=operator, service=None, is_active=True).first()
    return code


def build_ussd_code(tx):
    # Business-model audit: once a UssdCode has been picked for this
    # transaction (see ExecuteTransactionView), it must stay the one used
    # for its entire lifetime, even if an admin later deactivates/replaces
    # it - tx.ussd_code_used is that frozen choice. Only falls back to a
    # fresh resolution for a transaction created before this field existed
    # (nullable, added after Transaction itself).
    code = tx.ussd_code_used or resolve_ussd_code(tx.operator, tx.service, tx.amount)
    if code is None:
        raise UssdCodeNotConfigured(
            f'No active UssdCode for operator="{tx.operator.name}" (id={tx.operator_id}), '
            f'service="{tx.service.name}" (id={tx.service_id}), amount={tx.amount}, '
            f'and no active default for this operator.'
        )
    return code.render({
        'numero': tx.phone_number,
        'montant': int(tx.amount),
        'forfait': tx.service.name,
    })


def transaction_payload(tx, ussd_code=None):
    """Full detail, for Flutter-facing responses - the client needs
    payment_method/checkout_url to redirect the user to pay."""
    return {
        'id': tx.id,
        'reference': tx.reference,
        'transaction_type': tx.service.code or tx.service.name,
        'operator': tx.operator.name,
        'service': tx.service.name,
        'operation': tx.service.code or tx.service.name,
        'recipient_phone': tx.phone_number,
        'amount': float(tx.amount),
        'commission': float(tx.commission),
        'status': tx.status,
        'payment_method': tx.payment_method,
        'payment_reference': tx.payment_reference,
        'payment_status': tx.payment.status if tx.payment else None,
        'checkout_url': tx.payment.checkout_url if tx.payment else None,
        'ussd_code': ussd_code or build_ussd_code(tx),
        'created_at': tx.created_at.isoformat() if tx.created_at else None,
        'updated_at': tx.updated_at.isoformat() if tx.updated_at else None,
    }


def notification_payload(notification):
    """Flutter-facing shape for one Notification - deliberately excludes
    `user` (the endpoint that returns this already filtered by
    request.user, no need to echo the identity back)."""
    return {
        'id': notification.id,
        'title': notification.title,
        'message': notification.message,
        'type': notification.type,
        'is_read': notification.is_read,
        'created_at': notification.created_at.isoformat() if notification.created_at else None,
        'transaction_reference': notification.transaction.reference if notification.transaction_id else None,
    }


def gateway_task_payload(tx, ussd_code=None):
    """What the Android Gateway is allowed to see: a validated task to
    execute over USSD. Deliberately excludes payment_method, payment_reference,
    payment_status and checkout_url - the Gateway has no business knowing
    which payment provider was used, its API details, or its checkout link;
    by the time it sees a transaction, payment has already been confirmed
    'accepted' upstream (see PendingTransactionsView's queryset filter)."""
    payload = {
        'id': tx.id,
        'reference': tx.reference,
        'transaction_type': tx.service.code or tx.service.name,
        'operator': tx.operator.name,
        'service': tx.service.name,
        'operation': tx.service.code or tx.service.name,
        'recipient_phone': tx.phone_number,
        'amount': float(tx.amount),
        'commission': float(tx.commission),
        'status': tx.status,
        'ussd_code': ussd_code or build_ussd_code(tx),
        'created_at': tx.created_at.isoformat() if tx.created_at else None,
        'updated_at': tx.updated_at.isoformat() if tx.updated_at else None,
        # Phase D4.1: always present (unlike sim_slot/attempt_id below,
        # which stay conditional) so the Gateway reads a reliable boolean
        # rather than an absent-key case to handle - an older Gateway build
        # simply never reads this key, exactly like it already ignores
        # sim_slot today.
        'is_interactive': False,
    }
    # Additive, backward-compatible: an older Gateway app build simply never
    # reads this key and keeps dialing on its default/no-preference SIM,
    # exactly as before this field existed. Only meaningful once the
    # Scheduler has actually reserved a specific GatewaySim for this
    # transaction (USE_NEW_TRANSACTION_ENGINE=true) - the flag-off path never
    # gets this key at all: GatewayManager.select_operator_gateway() (business
    # -model audit Phase 7.2) picks the Gateway but never creates a
    # TransactionAttempt/reservation, so there is no specific SIM to report.
    if dj_settings.USE_NEW_TRANSACTION_ENGINE:
        # Stabilisation RC1 (priorité haute n°6): PendingTransactionsView
        # prefetches this exact filtered/ordered queryset once for the whole
        # page (see its `sim_attempts` Prefetch) to avoid one `attempts`
        # query per transaction. Callers that pass a single, non-prefetched
        # `tx` (ExecuteTransactionView, TransactionResultView) never set
        # this attribute, so the live query below still runs for them - same
        # result either way, just without the N+1 cost when it matters.
        sim_attempts = getattr(tx, 'sim_attempts', None)
        if sim_attempts is not None:
            attempt = sim_attempts[0] if sim_attempts else None
        else:
            attempt = tx.attempts.exclude(gateway_sim=None).order_by('-attempt_number').first()
        if attempt is not None:
            payload['sim_slot'] = attempt.gateway_sim.slot
            # Phase D4.1: the same identifier TransactionStepView verifies
            # (transaction_reference + attempt_id + authenticated Gateway
            # must all match one TransactionAttempt) - never Transaction.id,
            # never generated here, never `reference`.
            payload['attempt_id'] = attempt.id
            # is_interactive is never true without attempt_id also present:
            # under the legacy engine, or with no reserved attempt, no
            # step/NEW_FIELD session is executable anyway (see Phase D4
            # design notes).
            payload['is_interactive'] = bool(tx.ussd_code_used_id and tx.ussd_code_used.steps.exists())
    return payload
