import logging
from decimal import Decimal

import requests
from django.conf import settings

from .base import PaymentInitResult, PaymentProvider, PaymentProviderError, PaymentStatusResult
from .circuit_breaker import get_breaker
from .retry import RetryableHTTPError, call_create_with_retries, call_verify_with_retries, raise_if_retryable_status

logger = logging.getLogger(__name__)


class CinetPayError(PaymentProviderError):
    pass


def _status_to_local(raw_status):
    status = str(raw_status or '').upper()
    if status in {'ACCEPTED', 'SUCCEEDED', 'SUCCESS'}:
        return 'accepted'
    if status in {'REFUSED', 'REJECTED'}:
        return 'refused'
    if status in {'CANCELLED', 'CANCELED'}:
        return 'cancelled'
    if status in {'PENDING', 'WAITING'}:
        return 'pending'
    return 'failed'


class CinetPayProvider(PaymentProvider):
    method = 'cinetpay'

    def __init__(self):
        self.api_key = settings.CINETPAY_API_KEY
        self.site_id = settings.CINETPAY_SITE_ID
        self.timeout = settings.CINETPAY_TIMEOUT_SECONDS
        self.init_url = settings.CINETPAY_INIT_URL
        self.check_url = settings.CINETPAY_CHECK_URL
        self.breaker = get_breaker('cinetpay')

    def _ensure_configured(self):
        if not self.api_key or not self.site_id:
            if getattr(settings, 'CINETPAY_ALLOW_MOCK', False):
                return
            raise CinetPayError('CinetPay is not configured')

    def create_payment(self, *, transaction_id, amount, description, customer, metadata=None):
        self._ensure_configured()
        payload = {
            'apikey': self.api_key,
            'site_id': self.site_id,
            'transaction_id': transaction_id,
            'amount': int(Decimal(amount)),
            'currency': settings.CINETPAY_CURRENCY,
            'description': description,
            'notify_url': settings.CINETPAY_NOTIFY_URL,
            'return_url': settings.CINETPAY_RETURN_URL,
            'cancel_url': settings.CINETPAY_CANCEL_URL,
            'channels': settings.CINETPAY_CHANNELS,
            'lang': settings.CINETPAY_LANG,
            'customer_name': customer.get('name', 'Client'),
            'customer_surname': customer.get('surname', 'Transfer On Line'),
            'customer_phone_number': customer.get('phone', ''),
            'customer_email': customer.get('email', 'client@example.com'),
        }

        if getattr(settings, 'CINETPAY_ALLOW_MOCK', False):
            data = {
                'code': '201',
                'data': {
                    'payment_token': transaction_id,
                    'payment_url': f'http://127.0.0.1:3000/payment/mock?transaction_id={transaction_id}',
                },
            }
        else:
            def _do_request():
                response = requests.post(self.init_url, json=payload, timeout=self.timeout)
                return response

            try:
                response = self.breaker.call(call_create_with_retries, _do_request)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                raise CinetPayError(f'CinetPay unreachable: {exc}') from exc

            data = self._decode(response)
            if response.status_code >= 400 or str(data.get('code')) != '201':
                logger.warning('CinetPay init failed: %s', data)
                raise CinetPayError(data.get('message') or 'CinetPay payment initialization failed')

        inner = data.get('data') or {}
        return PaymentInitResult(
            checkout_url=inner.get('payment_url') or inner.get('url'),
            provider_transaction_id=str(inner.get('payment_token') or ''),
            raw=data,
        )

    def verify_payment(self, reference):
        self._ensure_configured()
        if getattr(settings, 'CINETPAY_ALLOW_MOCK', False):
            data = {'code': '200', 'data': {'status': 'ACCEPTED', 'transaction_id': reference}}
        else:
            def _do_request():
                response = requests.post(
                    self.check_url,
                    json={'apikey': self.api_key, 'site_id': self.site_id, 'transaction_id': reference},
                    timeout=self.timeout,
                )
                raise_if_retryable_status(response)
                return response

            try:
                response = self.breaker.call(call_verify_with_retries, _do_request)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, RetryableHTTPError) as exc:
                raise CinetPayError(f'CinetPay unreachable: {exc}') from exc

            data = self._decode(response)
            if response.status_code >= 400:
                logger.warning('CinetPay check failed: %s', data)
                raise CinetPayError(data.get('message') or 'CinetPay payment check failed')

        checked = data.get('data') or data
        return PaymentStatusResult(status=_status_to_local(checked.get('status') or checked.get('payment_status')), raw=data)

    def _decode(self, response):
        try:
            return response.json()
        except ValueError as exc:
            raise CinetPayError('Invalid CinetPay response') from exc
