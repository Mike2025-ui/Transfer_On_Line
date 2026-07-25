import logging
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class CinetPayError(Exception):
    pass


class CinetPayClient:
    init_url = 'https://api-checkout.cinetpay.com/v2/payment'
    check_url = 'https://api-checkout.cinetpay.com/v2/payment/check'

    def __init__(self):
        self.api_key = settings.CINETPAY_API_KEY
        self.site_id = settings.CINETPAY_SITE_ID
        self.secret_key = settings.CINETPAY_SECRET_KEY
        self.timeout = settings.CINETPAY_TIMEOUT_SECONDS

    def _ensure_configured(self):
        if not self.api_key or not self.site_id:
            if getattr(settings, 'CINETPAY_ALLOW_MOCK', False):
                return
            raise CinetPayError('CinetPay is not configured')

    def initialize_payment(self, *, transaction_id, amount, description, customer):
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
            return {
                'code': '201',
                'data': {
                    'payment_token': transaction_id,
                    'payment_url': f"http://127.0.0.1:3000/payment/mock?transaction_id={transaction_id}",
                },
            }

        response = requests.post(self.init_url, json=payload, timeout=self.timeout)
        data = self._decode(response)
        if response.status_code >= 400 or str(data.get('code')) != '201':
            logger.warning('CinetPay init failed: %s', data)
            raise CinetPayError(data.get('message') or 'CinetPay payment initialization failed')
        return data

    def check_payment(self, transaction_id):
        self._ensure_configured()
        if getattr(settings, 'CINETPAY_ALLOW_MOCK', False):
            return {
                'code': '200',
                'data': {'status': 'ACCEPTED', 'transaction_id': transaction_id},
            }

        response = requests.post(
            self.check_url,
            json={
                'apikey': self.api_key,
                'site_id': self.site_id,
                'transaction_id': transaction_id,
            },
            timeout=self.timeout,
        )
        data = self._decode(response)
        if response.status_code >= 400:
            logger.warning('CinetPay check failed: %s', data)
            raise CinetPayError(data.get('message') or 'CinetPay payment check failed')
        return data

    def _decode(self, response):
        try:
            return response.json()
        except ValueError as exc:
            raise CinetPayError('Invalid CinetPay response') from exc


def cinetpay_status_to_local(raw_status):
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
