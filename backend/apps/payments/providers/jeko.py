import logging
from decimal import Decimal

import requests
from django.conf import settings

from .base import PaymentInitResult, PaymentProvider, PaymentProviderError, PaymentStatusResult
from .circuit_breaker import get_breaker
from .retry import RetryableHTTPError, call_create_with_retries, call_verify_with_retries, raise_if_retryable_status

logger = logging.getLogger(__name__)

# https://developer.jeko.africa/docs/payments/checkout - the only payment
# methods documented for the redirect flow's paymentDetails.data.paymentMethod.
SUPPORTED_PAYMENT_METHODS = {'wave', 'orange', 'mtn', 'moov', 'djamo'}


class JekoError(PaymentProviderError):
    pass


def status_to_local(raw_status):
    """https://developer.jeko.africa/docs/payments/checkout documents exactly
    three payment_request statuses: pending / success / error. Shared here
    so the provider's verify_payment() and the JekoWebhookView (see
    apps/payments/webhooks.py) can never drift apart on this mapping."""
    status = str(raw_status or '').lower()
    if status == 'success':
        return 'accepted'
    if status == 'pending':
        return 'pending'
    return 'failed'


class JekoProvider(PaymentProvider):
    """https://developer.jeko.africa - standard merchant Payments API
    (Jèko Checkout / redirect flow), NOT the separate "Service Providers"
    marketplace-onboarding program (see apps/payments/providers/jeko_service.py's
    module docstring for why that one is out of scope here).

    Jèko's own docs state there is no sandbox environment - JEKO_BASE_URL
    always points at the one real API, and every create_payment() call
    creates a real payment request."""

    method = 'jeko'

    payment_requests_path = 'partner_api/payment_requests'

    def __init__(self):
        self.api_key = settings.JEKO_API_KEY
        self.api_key_id = settings.JEKO_API_KEY_ID
        self.store_id = settings.JEKO_STORE_ID
        self.base_url = settings.JEKO_BASE_URL.rstrip('/')
        self.timeout = settings.JEKO_TIMEOUT_SECONDS
        self.breaker = get_breaker('jeko')

    def _headers(self):
        return {
            'X-API-KEY': self.api_key,
            'X-API-KEY-ID': self.api_key_id,
            'Content-Type': 'application/json',
        }

    def _ensure_configured(self):
        if not (self.api_key and self.api_key_id and self.store_id):
            raise JekoError('Jèko is not configured')

    def create_payment(self, *, transaction_id, amount, description, customer, metadata=None):
        self._ensure_configured()
        amount_value = int(Decimal(amount))
        if amount_value < 100 or amount_value % 100 != 0:
            raise JekoError('Jèko amountCents must be at least 100 and a multiple of 100')

        payload = {
            'storeId': self.store_id,
            # Despite the "Cents" name, Jèko's own example shows amountCents
            # passed straight through unchanged into transaction.amount.amount
            # for XOF (which has no subunit) - not amount * 100.
            'amountCents': amount_value,
            'currency': 'XOF',
            'reference': str(transaction_id),
            'paymentDetails': {
                'type': 'redirect',
                'data': {
                    'successUrl': settings.JEKO_SUCCESS_URL,
                    'errorUrl': settings.JEKO_ERROR_URL,
                },
            },
        }

        # Multi-opérateurs : par défaut, ne pas pré-sélectionner de méthode de paiement
        # afin que le guichet Web Checkout de Djeko affiche le menu complet
        # des options (Wave, Djamo, Orange Money, Moov Money, MTN Money).
        # On n'injecte paymentMethod que si le client demande explicitement un canal dédié.
        explicit_channel = str(customer.get('payment_channel') or customer.get('channel') or '').lower()
        if explicit_channel:
            if explicit_channel not in SUPPORTED_PAYMENT_METHODS:
                raise JekoError(f'No Jèko payment method for operator: {explicit_channel}')
            payload['paymentDetails']['data']['paymentMethod'] = explicit_channel

        def _do_request():
            return requests.post(
                f'{self.base_url}/{self.payment_requests_path}',
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )

        try:
            response = self.breaker.call(call_create_with_retries, _do_request)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise JekoError(f'Jèko unreachable: {exc}') from exc

        data = self._decode(response)
        if response.status_code >= 400:
            message = data.get('message') or data.get('error') or f'HTTP {response.status_code}'
            logger.warning('Jèko payment_requests init failed: %s', data)
            raise JekoError(f'Jèko payment initialization failed: {message}')

        payment_request_id = data.get('id')
        if not payment_request_id:
            raise JekoError('Jèko response has no id')

        return PaymentInitResult(
            checkout_url=data.get('redirectUrl'),
            provider_transaction_id=str(payment_request_id),
            raw=data,
        )

    def verify_payment(self, reference):
        self._ensure_configured()

        def _do_request():
            response = requests.get(
                f'{self.base_url}/{self.payment_requests_path}/{reference}',
                headers=self._headers(),
                timeout=self.timeout,
            )
            raise_if_retryable_status(response)
            return response

        try:
            response = self.breaker.call(call_verify_with_retries, _do_request)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, RetryableHTTPError) as exc:
            raise JekoError(f'Jèko unreachable: {exc}') from exc

        data = self._decode(response)
        if response.status_code >= 400:
            message = data.get('message') or data.get('error') or f'HTTP {response.status_code}'
            logger.warning('Jèko payment_requests check failed: %s', data)
            raise JekoError(f'Jèko payment check failed: {message}')

        return PaymentStatusResult(status=status_to_local(data.get('status')), raw=data)

    def _decode(self, response):
        try:
            return response.json()
        except ValueError as exc:
            raise JekoError('Invalid Jèko response') from exc
