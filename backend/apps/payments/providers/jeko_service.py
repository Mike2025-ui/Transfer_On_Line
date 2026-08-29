import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class JekoPartnerError(Exception):
    pass


class JekoPartnerClient:
    """Client for Jèko's "Service Providers" program
    (https://developer.jeko.africa/docs/service_providers/introduction) -
    a SEPARATE, optional marketplace/reseller feature for platforms that
    create Jèko accounts FOR OTHER companies (marketplaces, PSP aggregators,
    wallet fintechs, PaaS). Jèko's own docs state explicitly: "Cette section
    ne concerne pas tous les intégrateurs."

    Transfer On Line collects its OWN payments (see
    apps/payments/providers/jeko.py's JekoProvider, which uses the standard
    Payments API - `/partner_api/payment_requests` - with JEKO_API_KEY/
    JEKO_API_KEY_ID/JEKO_STORE_ID), so it does not need this onboarding
    flow. This class currently has no caller anywhere in the project; it is
    kept only in case a future business decision activates the Service
    Providers program, and deliberately uses its own separate credentials
    (JEKO_PARTNER_API_KEY/_ID) so it can never be confused with the regular
    merchant payment credentials above."""

    def __init__(self):
        self.base_url = settings.JEKO_BASE_URL.rstrip('/')
        self.api_key = settings.JEKO_PARTNER_API_KEY
        self.api_key_id = settings.JEKO_PARTNER_API_KEY_ID
        self.timeout = settings.JEKO_TIMEOUT_SECONDS

    def _headers(self):
        if not self.api_key or not self.api_key_id:
            raise JekoPartnerError('Jèko Partner API is not configured')
        return {
            'X-API-KEY': self.api_key,
            'X-API-KEY-ID': self.api_key_id,
            'Content-Type': 'application/json',
            'Accept-Language': 'fr',
        }

    def _request(self, method, path, **kwargs):
        try:
            response = requests.request(
                method,
                f'{self.base_url}/{path.lstrip("/")}',
                headers=self._headers(),
                timeout=self.timeout,
                **kwargs,
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise JekoPartnerError('Jèko Partner API unreachable') from exc

        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            message = body.get('message') or body.get('error') or f'HTTP {response.status_code}'
            raise JekoPartnerError(f'Jèko Partner API: {message}')
        return body

    def locations(self):
        return self._request('GET', '/service_providers/locations')

    def activities(self):
        return self._request('GET', '/service_providers/activities')

    def onboard_business(self, *, owner, business):
        return self._request(
            'POST',
            '/service_providers/business_onboarding',
            json={'owner': owner, 'business': business},
        )

    def request_business_link(self, phone):
        return self._request(
            'POST',
            '/service_providers/business_link_requests',
            json={'phone': phone},
        )

    def get_business_link_request(self, request_id):
        return self._request('GET', f'/service_providers/business_link_requests/{request_id}')

    def create_business_api_key(self, merchant_business_id, name='Transfer On Line'):
        return self._request(
            'POST',
            '/service_providers/business_api_keys',
            json={'merchantBusinessId': merchant_business_id, 'name': name},
        )

    def business_links(self):
        return self._request('GET', '/service_providers/business_links')

    def detach_business(self, merchant_business_id):
        return self._request('DELETE', f'/service_providers/business_links/{merchant_business_id}')