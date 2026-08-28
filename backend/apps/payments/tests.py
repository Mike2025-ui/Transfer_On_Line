from contextlib import nullcontext
from unittest.mock import patch

import requests
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import Gateway, Payment, Transaction, Device, Service, Operator
from apps.payments.models import WebhookEvent
from apps.payments.providers.cinetpay import CinetPayProvider
from apps.payments.providers.geniuspay import GeniusPayProvider
from apps.payments.providers.circuit_breaker import CircuitBreaker, CircuitOpenError
from apps.payments.providers.retry import (
    RetryableHTTPError,
    call_create_with_retries,
    call_verify_with_retries,
)


@override_settings(GENIUSPAY_WEBHOOK_SECRET='', GENIUSPAY_ALLOW_MOCK=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class GeniusPayWebhookIdempotencyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        gateway = Gateway.objects.create(name='Orange - 0700000000', host='gateway-1', status='online')
        self.payment = Payment.objects.create(
            method='geniuspay',
            reference='TOL-1',
            provider_transaction_id='SANDBOX_PROVIDERREF',
            amount=1000,
            status='pending',
        )
        self.tx = Transaction.objects.create(
            device=Device.objects.create(uid='client-app', primary_phone='0700000001'),
            service=Service.objects.create(name='Internet', code='subscription'),
            operator=Operator.objects.create(name='Orange', code='orange'),
            gateway=gateway,
            phone_number='0700000001',
            amount=1000,
            payment=self.payment,
            payment_method='geniuspay',
            payment_reference='TOL-1',
        )

    def _webhook_payload(self, event_id='evt-1', status='completed', amount=1000, include_metadata=True):
        """Mirrors GeniusPay's real payload shape: `data.reference` is
        GeniusPay's OWN reference, never our Payment.reference. Our reference
        only comes back inside `data.metadata.transaction_reference`."""
        data = {
            'reference': 'SANDBOX_PROVIDERREF',
            'status': status,
            'amount': amount,
            'currency': 'XOF',
        }
        if include_metadata:
            data['metadata'] = {'transaction_reference': 'TOL-1', 'order_id': str(self.tx.reference)}
        return {'id': event_id, 'event': 'payment.success', 'data': data}

    def test_webhook_marks_payment_accepted_and_syncs_transaction(self, _redis_lock):
        response = self.client.post(reverse('api_geniuspay_webhook'), self._webhook_payload(), format='json')
        self.assertEqual(response.status_code, 200)

        self.payment.refresh_from_db()
        self.tx.refresh_from_db()
        self.assertEqual(self.payment.status, 'accepted')
        self.assertEqual(self.tx.status, 'pending')  # gateway assigned -> becomes actionable
        self.assertEqual(WebhookEvent.objects.filter(provider='geniuspay', processed=True).count(), 1)

    def test_falls_back_to_provider_transaction_id_when_metadata_is_missing(self, _redis_lock):
        """Regression test: an earlier version of this view looked up the
        payment by GeniusPay's own `data.reference` FIRST, which never
        matches our Payment.reference and made every real webhook 404."""
        payload = self._webhook_payload(include_metadata=False)
        response = self.client.post(reverse('api_geniuspay_webhook'), payload, format='json')
        self.assertEqual(response.status_code, 200)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'accepted')

    def test_duplicate_delivery_is_ignored_and_does_not_reprocess(self, _redis_lock):
        self.client.post(reverse('api_geniuspay_webhook'), self._webhook_payload(), format='json')
        self.tx.refresh_from_db()
        first_updated_at = self.tx.updated_at

        response = self.client.post(reverse('api_geniuspay_webhook'), self._webhook_payload(), format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get('status'), 'duplicate-ignored')

        self.tx.refresh_from_db()
        self.assertEqual(self.tx.updated_at, first_updated_at)
        self.assertEqual(WebhookEvent.objects.filter(provider='geniuspay').count(), 1)

    def test_reference_without_matching_payment_returns_404(self, _redis_lock):
        payload = self._webhook_payload(event_id='evt-2')
        payload['data']['metadata']['transaction_reference'] = 'UNKNOWN'
        payload['data']['reference'] = 'UNKNOWN_PROVIDER_REF'
        response = self.client.post(reverse('api_geniuspay_webhook'), payload, format='json')
        self.assertEqual(response.status_code, 404)

    def test_amount_mismatch_is_rejected_without_touching_the_payment(self, _redis_lock):
        response = self.client.post(
            reverse('api_geniuspay_webhook'),
            self._webhook_payload(amount=999999),
            format='json',
        )
        self.assertEqual(response.status_code, 400)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'pending')  # untouched

    def test_missing_secret_refuses_webhook_outside_mock_mode(self, _redis_lock):
        with override_settings(GENIUSPAY_WEBHOOK_SECRET='', GENIUSPAY_ALLOW_MOCK=False):
            response = self.client.post(reverse('api_geniuspay_webhook'), self._webhook_payload(), format='json')
        self.assertEqual(response.status_code, 503)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'pending')

    def test_invalid_transition_is_caught_not_a_500_and_keeps_the_dedup_row(self, _redis_lock):
        """Phase D audit (Critique n°2): the transaction is already in a
        terminal status different from what this event implies (e.g. it was
        separately cancelled) - PaymentService.apply_status() ->
        sync_from_payment() raises InvalidTransitionError. Must not crash the
        webhook, must not partially write the Payment, and the WebhookEvent
        dedup row must survive so a provider retry doesn't reprocess forever."""
        self.tx.status = 'cancelled'
        self.tx.save(update_fields=['status'])

        response = self.client.post(reverse('api_geniuspay_webhook'), self._webhook_payload(), format='json')

        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'pending', 'the Payment write must be rolled back, never partially applied')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'cancelled', 'the rejected transition must never apply')

        event = WebhookEvent.objects.get(provider='geniuspay', event_id='evt-1')
        self.assertTrue(event.processed, 'the dedup row must survive and be marked processed, not rolled back')

        # A provider retry of the exact same event must be a clean, cheap
        # no-op via the WebhookEvent dedup check - never re-attempt (and
        # re-fail) the status sync.
        second = self.client.post(reverse('api_geniuspay_webhook'), self._webhook_payload(), format='json')
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data.get('status'), 'duplicate-ignored')


class CircuitBreakerTests(TestCase):
    def test_opens_after_threshold_and_fails_fast_without_calling_func(self):
        breaker = CircuitBreaker('test-provider', failure_threshold=3, reset_timeout=60)
        calls = []

        def always_fails():
            calls.append(1)
            raise requests.exceptions.ConnectionError('boom')

        for _ in range(3):
            with self.assertRaises(requests.exceptions.ConnectionError):
                breaker.call(always_fails)
        self.assertEqual(len(calls), 3)

        # circuit is now open: the underlying function must NOT be invoked again
        with self.assertRaises(CircuitOpenError):
            breaker.call(always_fails)
        self.assertEqual(len(calls), 3, 'breaker must fail fast without calling the provider again')

    def test_recovers_after_reset_timeout_via_half_open_probe(self):
        breaker = CircuitBreaker('test-provider-2', failure_threshold=1, reset_timeout=0)
        with self.assertRaises(requests.exceptions.ConnectionError):
            breaker.call(lambda: (_ for _ in ()).throw(requests.exceptions.ConnectionError('boom')))

        # reset_timeout=0 -> the very next call is treated as a HALF_OPEN probe
        result = breaker.call(lambda: 'ok')
        self.assertEqual(result, 'ok')

        # a clean success must have closed the circuit again
        self.assertEqual(breaker.call(lambda: 'still ok'), 'still ok')


class RetryPolicyTests(TestCase):
    def test_create_payment_does_not_retry_on_timeout(self):
        """A POST that creates a payment must never be retried on a Timeout -
        we cannot know whether the provider already processed it, and
        retrying could create a second payment for the same transaction."""
        calls = []

        def times_out():
            calls.append(1)
            raise requests.exceptions.Timeout('slow provider')

        with self.assertRaises(requests.exceptions.Timeout):
            call_create_with_retries(times_out)
        self.assertEqual(len(calls), 1, 'create_payment must not retry on an ambiguous Timeout')

    def test_create_payment_retries_on_pre_send_connection_error(self):
        """A ConnectionError means the request never reached the provider -
        safe to retry."""
        calls = []

        def fails_twice_then_succeeds():
            calls.append(1)
            if len(calls) < 2:
                raise requests.exceptions.ConnectionError('refused')
            return 'ok'

        result = call_create_with_retries(fails_twice_then_succeeds, max_attempts=3, base_delay_seconds=0)
        self.assertEqual(result, 'ok')
        self.assertEqual(len(calls), 2)

    def test_verify_payment_retries_on_timeout_and_retryable_status(self):
        """verify_payment is a GET: safe to retry on any transient failure."""
        calls = []

        def fails_then_succeeds():
            calls.append(1)
            if len(calls) < 3:
                raise requests.exceptions.Timeout('slow')
            return 'ok'

        result = call_verify_with_retries(fails_then_succeeds, max_attempts=4, base_delay_seconds=0)
        self.assertEqual(result, 'ok')
        self.assertEqual(len(calls), 3)

    def test_retries_are_bounded_and_give_up(self):
        calls = []

        def always_times_out():
            calls.append(1)
            raise requests.exceptions.Timeout('always slow')

        with self.assertRaises(requests.exceptions.Timeout):
            call_verify_with_retries(always_times_out, max_attempts=3, base_delay_seconds=0)
        self.assertEqual(len(calls), 3, 'must give up after max_attempts, never retry forever')


class PaymentProviderRefundInterfaceTests(TestCase):
    """B1: PaymentProvider.refund() exists on the interface but neither
    provider implements it yet (see the base class docstring) - this locks
    in that both fail loudly and identically rather than silently, so a
    future RefundService can rely on catching NotImplementedError uniformly."""

    def test_cinetpay_refund_is_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            CinetPayProvider().refund('some-reference')

    def test_geniuspay_refund_is_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            GeniusPayProvider().refund('some-reference')
