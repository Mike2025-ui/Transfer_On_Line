import hashlib
import hmac
import logging
import time
from decimal import Decimal

import requests
from django.conf import settings

from .base import PaymentInitResult, PaymentProvider, PaymentProviderError, PaymentStatusResult
from .circuit_breaker import get_breaker
from .retry import RetryableHTTPError, call_create_with_retries, call_verify_with_retries, raise_if_retryable_status

logger = logging.getLogger(__name__)


class GeniusPayError(PaymentProviderError):
    pass


def status_to_local(raw_status):
    status = str(raw_status or '').lower()
    if status == 'completed':
        return 'accepted'
    if status in {'failed', 'expired'}:
        return 'failed'
    if status == 'cancelled':
        return 'cancelled'
    if status == 'refunded':
        return 'failed'
    if status in {'pending', 'processing'}:
        return 'pending'
    return 'failed'


def verify_webhook_signature(*, raw_body, timestamp, signature, secret, max_age_seconds=300):
    """HMAC-SHA256 over "{timestamp}.{raw_json_body}", per GeniusPay's webhook docs."""
    if not (timestamp and signature and secret):
        return False
    try:
        if abs(time.time() - int(timestamp)) > max_age_seconds:
            return False
    except ValueError:
        return False
    body_str = raw_body.decode('utf-8') if isinstance(raw_body, bytes) else raw_body
    signed_payload = f'{timestamp}.{body_str}'
    expected = hmac.new(secret.encode('utf-8'), signed_payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class GeniusPayProvider(PaymentProvider):
    method = 'geniuspay'

    payments_path = '/payments'

    def __init__(self):
        self.api_key = settings.GENIUSPAY_API_KEY
        self.api_secret = settings.GENIUSPAY_API_SECRET
        self.base_url = settings.GENIUSPAY_BASE_URL.rstrip('/')
        self.timeout = settings.GENIUSPAY_TIMEOUT_SECONDS
        self.breaker = get_breaker('geniuspay')

    def _headers(self):
        return {
            'X-API-Key': self.api_key,
            'X-API-Secret': self.api_secret,
            'Content-Type': 'application/json',
        }

    def _ensure_configured(self):
        if not self.api_key or not self.api_secret:
            if getattr(settings, 'GENIUSPAY_ALLOW_MOCK', False):
                return
            raise GeniusPayError('GeniusPay is not configured')

    def create_payment(self, *, transaction_id, amount, description, customer, metadata=None):
        """Checkout mode: payment_method is intentionally omitted so GeniusPay
        returns a hosted checkout_url where the customer picks Wave/Orange/MTN/card."""
        self._ensure_configured()
        amount_value = int(Decimal(amount))
        if amount_value < 200:
            raise GeniusPayError('GeniusPay amount must be at least 200 XOF')

        if getattr(settings, 'GENIUSPAY_ALLOW_MOCK', False):
            data = {
                'success': True,
                'data': {
                    'reference': transaction_id,
                    'checkout_url': f'http://127.0.0.1:3000/payment/mock?transaction_id={transaction_id}',
                    'status': 'pending',
                },
            }
        else:
            payload = {
                'amount': amount_value,
                'currency': settings.GENIUSPAY_CURRENCY,
                'description': description,
                'customer': {
                    'name': customer.get('name') or 'Client',
                    'phone': customer.get('phone') or '',
                    'email': customer.get('email') or '',
                },
                'success_url': settings.GENIUSPAY_SUCCESS_URL,
                'error_url': settings.GENIUSPAY_ERROR_URL,
                # `transaction_reference` is our Payment.reference - the
                # primary lookup key a webhook uses to find this payment back
                # (see apps/payments/webhooks.py). Anything the caller put in
                # `metadata` (e.g. correlation_id = Transaction.reference) is
                # preserved as-is and comes back to us in every webhook event
                # for this payment too.
                'metadata': {**(metadata or {}), 'transaction_reference': transaction_id},
            }

            def _do_request():
                return requests.post(
                    f'{self.base_url}{self.payments_path}',
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                )

            try:
                response = self.breaker.call(call_create_with_retries, _do_request)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                raise GeniusPayError(f'GeniusPay unreachable: {exc}') from exc

            data = self._decode(response)
            if response.status_code >= 400 or not data.get('success'):
                error = data.get('error') or {}
                logger.warning('GeniusPay init failed: %s', data)
                raise GeniusPayError(error.get('message') or 'GeniusPay payment initialization failed')

        inner = data.get('data') or {}
        return PaymentInitResult(
            checkout_url=inner.get('checkout_url') or inner.get('payment_url'),
            provider_transaction_id=str(inner.get('reference') or ''),
            raw=data,
        )

    def verify_payment(self, reference):
        self._ensure_configured()
        if getattr(settings, 'GENIUSPAY_ALLOW_MOCK', False):
            data = {'success': True, 'data': {'reference': reference, 'status': 'completed'}}
        else:
            def _do_request():
                response = requests.get(
                    f'{self.base_url}{self.payments_path}/{reference}',
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                raise_if_retryable_status(response)
                return response

            try:
                response = self.breaker.call(call_verify_with_retries, _do_request)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, RetryableHTTPError) as exc:
                raise GeniusPayError(f'GeniusPay unreachable: {exc}') from exc

            data = self._decode(response)
            if response.status_code >= 400 or not data.get('success'):
                error = data.get('error') or {}
                logger.warning('GeniusPay check failed: %s', data)
                raise GeniusPayError(error.get('message') or 'GeniusPay payment check failed')

        inner = data.get('data') or {}
        return PaymentStatusResult(status=status_to_local(inner.get('status')), raw=data)

    def _decode(self, response):
        try:
            return response.json()
        except ValueError as exc:
            raise GeniusPayError('Invalid GeniusPay response') from exc
