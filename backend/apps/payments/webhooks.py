import hashlib
import hmac
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.correlation import set_correlation_id
from apps.core.models import Payment, UssdCodeNotConfigured, UssdCodeRenderError
from apps.core.serializers import transaction_payload
from apps.core.services.transaction_state_machine import InvalidTransitionError
from apps.payments.models import WebhookEvent
from apps.payments.providers.geniuspay import status_to_local, verify_webhook_signature
from apps.payments.providers.jeko import status_to_local as jeko_status_to_local
from apps.payments.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


def _safe_transaction_payload(tx):
    """Gestion des opérateurs: by the time this is called here, apply_status()
    has already committed inside the enclosing `with db_transaction.atomic()`
    block (this call happens after it exits) - only the webhook's response
    body is at risk if the transaction's USSD config is broken, so degrade to
    ussd_code=None rather than 500ing a webhook the provider might retry
    indefinitely."""
    try:
        return transaction_payload(tx)
    except (UssdCodeNotConfigured, UssdCodeRenderError) as exc:
        logger.error('transaction_payload failed for transaction %s: %s', tx.reference, exc)
        payload = transaction_payload(tx, ussd_code='__unavailable__')
        payload['ussd_code'] = None
        return payload

def _apply_status_safely(payment, new_status, *, raw_payload, event_id):
    """Phase D audit (Critique n°2): PaymentService.apply_status() can raise
    InvalidTransitionError (via Transaction.sync_from_payment() ->
    TransactionStateMachine.transition()) when the linked Transaction is
    already in a different terminal status than what this event implies -
    e.g. a provider retrying a webhook after the transaction was already
    resolved some other way. Left uncaught, that exception used to escape
    the view's `with db_transaction.atomic()` block entirely, rolling back
    everything including the WebhookEvent row just inserted for dedup - so a
    replay of the exact same event would redo all this work and hit the
    exact same error again, forever, as an unhandled 500.

    Catching it here lets the surrounding atomic block commit normally
    (the WebhookEvent dedup row survives), while this call's own Payment
    status write is cleanly rolled back to its savepoint by apply_status()'s
    own nested atomic block - never a partial update. Returns True if the
    status was actually applied, False if it was safely rejected."""
    try:
        PaymentService.apply_status(payment, new_status, raw_payload=raw_payload)
    except InvalidTransitionError as exc:
        logger.warning(
            'Webhook event %s: payment %s status sync rejected (transaction already resolved differently): %s',
            event_id, payment.reference, exc,
        )
        return False
    return True


_KNOWN_GENIUSPAY_STATUSES = {'pending', 'processing', 'completed', 'failed', 'cancelled', 'expired'}


def _validate_geniuspay_event(payment, payload):
    """Returns an error string if the webhook payload is inconsistent with
    what we know about this payment, or None if it looks trustworthy enough
    to apply. Called only AFTER signature verification has already succeeded
    (or been explicitly bypassed in DEBUG) - this is a sanity/integrity check
    on top of authentication, not a substitute for it."""
    amount = payload.get('amount')
    if amount is not None:
        try:
            if Decimal(str(amount)) != payment.amount:
                return f'amount mismatch: payment has {payment.amount}, webhook reports {amount}'
        except InvalidOperation:
            return f'amount is not a valid number: {amount!r}'

    currency = payload.get('currency')
    if currency and currency != settings.GENIUSPAY_CURRENCY:
        return f'currency mismatch: expected {settings.GENIUSPAY_CURRENCY}, got {currency}'

    raw_status = payload.get('status')
    if raw_status is not None and str(raw_status).lower() not in _KNOWN_GENIUSPAY_STATUSES:
        logger.warning('GeniusPay webhook: unrecognized status "%s" for %s (defaulting to failed)', raw_status, payment.reference)

    return None


class GeniusPayWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        secret = settings.GENIUSPAY_WEBHOOK_SECRET
        signature = request.headers.get('X-Webhook-Signature', '')
        timestamp = request.headers.get('X-Webhook-Timestamp', '')

        if not secret:
            if getattr(settings, 'GENIUSPAY_ALLOW_MOCK', False):
                # GENIUSPAY_ALLOW_MOCK is the same explicit dev/sandbox opt-in
                # used by the provider client's own mock mode - unlike DEBUG
                # (which Django forces off in tests and which governs a lot of
                # unrelated behavior), this flag specifically means "we are
                # not really talking to production GeniusPay".
                logger.warning('GENIUSPAY_WEBHOOK_SECRET is not set - accepting UNVERIFIED webhook (mock mode only)')
            else:
                logger.error('GENIUSPAY_WEBHOOK_SECRET is not set; refusing webhook in production')
                return Response({'error': 'Webhook not configured'}, status=503)
        elif not verify_webhook_signature(raw_body=request.body, timestamp=timestamp, signature=signature, secret=secret):
            logger.warning('GeniusPay webhook signature invalid (event=%s)', request.data.get('event'))
            return Response({'error': 'Invalid webhook signature'}, status=401)

        payload = request.data.get('data')
        if not isinstance(payload, dict):
            return Response({'error': 'data payload required'}, status=400)

        # GeniusPay's own `data.reference` is THEIR id (stored as our
        # Payment.provider_transaction_id), never our own Payment.reference.
        # Our reference travels back to us inside `data.metadata`, set when we
        # called create_payment() - that is the primary lookup key; the
        # provider's own reference is only a fallback.
        provider_reference = payload.get('reference')
        our_reference = (payload.get('metadata') or {}).get('transaction_reference')
        event_id = (
            request.data.get('id')
            or request.headers.get('X-Webhook-Delivery')
            or f'no-id:{our_reference or provider_reference}:{payload.get("status")}'
        )

        with db_transaction.atomic():
            event, created = WebhookEvent.objects.get_or_create(
                provider='geniuspay',
                event_id=str(event_id),
                defaults={
                    'event_type': request.data.get('event') or '',
                    'signature': signature,
                    'headers': {k: v for k, v in request.headers.items() if k.lower().startswith('x-webhook')},
                    'payload': request.data,
                    'payment_reference': our_reference or provider_reference,
                },
            )
            if not created:
                logger.info('GeniusPay webhook %s already received, ignoring duplicate delivery', event_id)
                return Response({'status': 'duplicate-ignored'})

            payment = None
            if our_reference:
                payment = Payment.objects.filter(reference=our_reference).first()
            if payment is None and provider_reference:
                payment = Payment.objects.filter(provider_transaction_id=provider_reference, method='geniuspay').first()

            if payment is None:
                logger.warning(
                    'GeniusPay webhook %s: no matching payment (our_ref=%s, provider_ref=%s)',
                    event_id, our_reference, provider_reference,
                )
                return Response({'error': 'Payment not found'}, status=404)

            tx = payment.transactions.select_related('service', 'operator', 'gateway').first()
            if tx:
                set_correlation_id(str(tx.reference))

            validation_error = _validate_geniuspay_event(payment, payload)
            if validation_error:
                logger.warning('GeniusPay webhook %s rejected for payment %s: %s', event_id, payment.reference, validation_error)
                return Response({'error': validation_error}, status=400)

            _apply_status_safely(
                payment,
                status_to_local(payload.get('status')),
                raw_payload={'event': event.event_type, 'notification': request.data},
                event_id=event_id,
            )
            event.processed = True
            event.processed_at = timezone.now()
            event.save(update_fields=['processed', 'processed_at'])

            if tx:
                tx.refresh_from_db()

        return Response({
            'payment_reference': payment.reference,
            'payment_status': payment.status,
            'transaction': _safe_transaction_payload(tx) if tx else None,
        })


class JekoWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        secret = settings.JEKO_WEBHOOK_SECRET
        signature = request.headers.get('Jeko-Signature', '')
        if not secret or not signature:
            return Response({'error': 'Webhook not configured'}, status=503)

        expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return Response({'error': 'Invalid signature'}, status=401)

        body = request.data
        if body.get('event') == 'SERVICE_PROVIDER_LINK_REQUEST':
            payload = body.get('payload') or {}
            event_id = str(payload.get('id') or body.get('event'))
            event_type = 'SERVICE_PROVIDER_LINK_REQUEST'
            payment_reference = None
        else:
            details = body.get('transactionDetails') or {}
            payment_reference = details.get('reference') or body.get('reference') or body.get('id')
            event_id = str(body.get('id') or payment_reference or 'unknown')
            event_type = 'TRANSACTION_COMPLETED'

        event, created = WebhookEvent.objects.get_or_create(
            provider='jeko',
            event_id=event_id,
            defaults={
                'event_type': event_type,
                'signature': signature,
                'headers': {'Jeko-Signature': signature},
                'payload': body,
                'payment_reference': payment_reference,
            },
        )
        if not created:
            return Response({'received': True, 'status': 'duplicate-ignored'})

        if payment_reference is None:
            event.processed = True
            event.processed_at = timezone.now()
            event.save(update_fields=['processed', 'processed_at'])
            return Response({'received': True})

        payment = Payment.objects.filter(reference=payment_reference, method='jeko').first()
        if payment is None:
            payment = Payment.objects.filter(provider_transaction_id=payment_reference, method='jeko').first()
        if payment is None:
            return Response({'error': 'Payment not found'}, status=404)

        _apply_status_safely(
            payment,
            jeko_status_to_local(body.get('status')),
            raw_payload=body,
            event_id=event_id,
        )
        event.processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=['processed', 'processed_at'])
        return Response({'received': True, 'payment_reference': payment.reference, 'payment_status': payment.status})
