import logging
from decimal import Decimal

import requests
from django.conf import settings

from .base import PaymentInitResult, PaymentProvider, PaymentProviderError, PaymentStatusResult
from .circuit_breaker import get_breaker
from .retry import call_create_with_retries

logger = logging.getLogger(__name__)


class FeexPayError(PaymentProviderError):
    pass


class FeexPayProvider(PaymentProvider):
    method = 'feexpay'

    def __init__(self):
        self.api_key = settings.FEEXPAY_API_KEY
        self.shop = settings.FEEXPAY_SHOP
        self.base_url = settings.FEEXPAY_BASE_URL.rstrip('/')
        self.channels = settings.FEEXPAY_CHANNELS
        self.timeout = settings.FEEXPAY_TIMEOUT_SECONDS
        self.breaker = get_breaker('feexpay')

    def _ensure_configured(self):
        if not self.api_key or not self.shop:
            raise FeexPayError('FeexPay is not configured')

    def create_payment(self, *, transaction_id, amount, description, customer, metadata=None):
        self._ensure_configured()
        amount_value = int(Decimal(amount))
        if amount_value < 100 or amount_value > 2_000_000:
            raise FeexPayError('FeexPay amount must be between 100 and 2000000 XOF')

        phone = ''.join(character for character in str(customer.get('phone') or '') if character.isdigit())
        if len(phone) == 10:
            phone = f'225{phone}'
        if len(phone) < 8:
            raise FeexPayError('FeexPay requires an international phone number')
        operator = str(customer.get('operator_code') or customer.get('operator') or '').lower()
        channel = self._channel_for(operator)
        payload = {
            'shop': self.shop,
            'amount': amount_value,
            'phoneNumber': phone,
            'first_name': customer.get('name') or 'Client',
            'last_name': customer.get('surname') or 'Transfer On Line',
            'description': description,
            'callbackInfo': str(transaction_id),
        }

        def _do_request():
            return requests.post(
                f'{self.base_url}/api/transactions/public/requesttopay/{channel}',
                json=payload,
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json',
                },
                timeout=self.timeout,
            )

        try:
            response = self.breaker.call(call_create_with_retries, _do_request)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise FeexPayError(f'FeexPay unreachable: {exc}') from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise FeexPayError('Invalid FeexPay response') from exc

        if response.status_code >= 400 or str(data.get('status', '')).upper() not in {'PENDING', 'ACCEPTED', 'SUCCESS'}:
            logger.warning('FeexPay init failed: %s', data)
            raise FeexPayError(data.get('message') or 'FeexPay payment initialization failed')

        reference = data.get('reference')
        if not reference:
            raise FeexPayError('FeexPay response has no reference')

        return PaymentInitResult(
            checkout_url=None,
            provider_transaction_id=str(reference),
            raw=data,
        )

    def verify_payment(self, reference):
        raise FeexPayError(
            'FeexPay payment status endpoint is not configured; provide the provider status API before reconciliation'
        )

    def _channel_for(self, operator):
        for key, channel in self.channels.items():
            if key in operator:
                return channel
        raise FeexPayError(f'No FeexPay channel configured for operator: {operator or "unknown"}')