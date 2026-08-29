import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import Count
from django.utils import timezone

from apps.core.locks import redis_lock
from apps.core.models import Payment
from apps.payments.providers.base import PaymentProviderError
from apps.payments.providers.registry import AUTO_METHOD, get_provider

logger = logging.getLogger(__name__)


class PaymentService:
    """The only entry point the rest of the project should use to talk to a
    payment provider. Nothing outside apps.payments imports a concrete
    provider client or a provider-specific exception."""

    @staticmethod
    def initiate(payment, *, description, customer, metadata=None):
        methods = PaymentService._provider_order(payment.method)
        failures = []
        for method in methods:
            provider = get_provider(method)
            try:
                result = provider.create_payment(
                    transaction_id=payment.reference,
                    amount=payment.amount,
                    description=description,
                    customer=customer,
                    metadata=metadata,
                )
            except PaymentProviderError as exc:
                failures.append({'provider': method, 'error': str(exc)})
                logger.warning('%s payment init failed for %s: %s', method, payment.reference, exc)
                continue

            payment.method = method
            payment.status = 'pending'
            payment.provider_transaction_id = result.provider_transaction_id
            payment.checkout_url = result.checkout_url
            payment.provider_payload = result.raw
            payment.save(update_fields=['method', 'status', 'provider_transaction_id', 'checkout_url', 'provider_payload', 'updated_at'])
            logger.info('%s payment initiated: %s -> %s', method, payment.reference, payment.checkout_url)
            return payment

        payment.status = 'failed'
        payment.provider_payload = {'provider_failures': failures}
        payment.save(update_fields=['status', 'provider_payload', 'updated_at'])
        raise PaymentProviderError('All payment providers failed')

    @staticmethod
    def _provider_order(method):
        if method != AUTO_METHOD:
            return [method]
        return [name.strip() for name in settings.PAYMENT_PROVIDER_ORDER.split(',') if name.strip()]

    @staticmethod
    def verify(payment):
        provider = get_provider(payment.method)
        result = provider.verify_payment(payment.provider_transaction_id or payment.reference)
        PaymentService.apply_status(payment, result.status, raw_payload=result.raw)
        return payment

    @staticmethod
    def apply_status(payment, new_status, raw_payload=None):
        """Idempotent and race-safe: locks the Payment row for the duration of
        the read-modify-write so two concurrent webhook deliveries (or a
        webhook racing a manual verify()) can never interleave. A status that
        hasn't actually changed is a no-op, so a replayed event can never
        re-trigger the Transaction reconciliation a second time.

        Belt-and-suspenders locking: select_for_update() is the real,
        correct row lock on PostgreSQL; redis_lock() is an additional
        cross-request lock that also works on SQLite, where
        select_for_update() is a documented no-op (see redis_lock's
        docstring). Either one degrades gracefully on its own, so combining
        them costs little and covers both deployment targets."""
        with redis_lock(f'payment:{payment.pk}'), db_transaction.atomic():
            locked = Payment.objects.select_for_update().get(pk=payment.pk)
            if locked.status == new_status:
                logger.info('%s payment %s already in status %s, skipping', locked.method, locked.reference, new_status)
                return False

            locked.status = new_status
            if raw_payload is not None:
                locked.provider_payload = raw_payload
            locked.save(update_fields=['status', 'provider_payload', 'updated_at'])
            logger.info('%s payment %s -> %s', locked.method, locked.reference, new_status)

            tx = locked.transactions.select_related('service', 'operator', 'gateway').first()
            if tx:
                tx.payment = locked  # avoid a stale re-fetch: reuse the row we just locked and wrote
                tx.sync_from_payment()

        # keep the caller's in-memory instance consistent with what was persisted
        payment.status = locked.status
        payment.provider_payload = locked.provider_payload
        return True

    @staticmethod
    def reconcile_pending(*, stale_after_minutes=10, expire_after_hours=24):
        """Safety net for payments that never receive a webhook (lost delivery,
        customer abandoning checkout, our server being down at delivery time):
        - payments stuck 'pending' for longer than stale_after_minutes get an
          active verify_payment() call against the provider;
        - payments older than expire_after_hours are declared 'failed' outright
          without calling the provider (GeniusPay's own checkout links expire
          after 24h, so there is nothing left to verify).
        Safe to call repeatedly (e.g. from cron): every step goes through the
        same idempotent apply_status() used by webhooks."""
        now = timezone.now()
        stale_cutoff = now - timedelta(minutes=stale_after_minutes)
        expiry_cutoff = now - timedelta(hours=expire_after_hours)

        candidates = list(Payment.objects.filter(status='pending', created_at__lte=stale_cutoff))
        expired = verified = errors = 0

        for payment in candidates:
            if payment.created_at <= expiry_cutoff:
                if PaymentService.apply_status(payment, 'failed', raw_payload={'reconciliation': 'expired'}):
                    expired += 1
                continue
            try:
                PaymentService.verify(payment)
                verified += 1
            except PaymentProviderError as exc:
                logger.warning('Reconciliation verify failed for %s (%s): %s', payment.reference, payment.method, exc)
                errors += 1

        summary = {'checked': len(candidates), 'verified': verified, 'expired': expired, 'errors': errors}
        logger.info('Payment reconciliation: %s', summary)
        return summary

    @staticmethod
    def funnel_summary(*, since=None):
        """Payment counts by provider and status - the building block for a
        monitoring dashboard or an alert ("too many failed GeniusPay payments
        in the last hour"). Not wired into any UI yet; safe to call from a
        shell, a management command, or a future /metrics endpoint."""
        queryset = Payment.objects.all()
        if since:
            queryset = queryset.filter(created_at__gte=since)
        rows = queryset.values('method', 'status').annotate(count=Count('id')).order_by('method', 'status')

        summary = {}
        for row in rows:
            summary.setdefault(row['method'], {})[row['status']] = row['count']
        return summary
