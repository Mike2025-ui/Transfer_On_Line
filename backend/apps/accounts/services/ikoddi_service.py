import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class IkoddiError(Exception):
    """Raised for any IKODDI API failure - never shown directly to the
    client, only logged; apps.accounts.services.otp_service translates it
    to a generic OtpError."""


def _ikoddi_identity(phone_number):
    """IKODDI's documented examples always show `identity`/the URL segment
    as digits only, no leading '+' (e.g. "22670707070") - our own canonical
    stored format is E.164 with a '+' (see otp_service.normalize_phone_number).
    This strips the '+' only for the outgoing IKODDI call; the '+'-prefixed
    form stays the identity Django/JWT/User use everywhere else."""
    return phone_number.lstrip('+')


class IkoddiService:
    """The only thing in this codebase allowed to talk HTTP to IKODDI.

    Documented contract (https://docs.ikoddi.com - OTP As A Service /
    Authentification guides; nothing beyond what is documented is assumed):

        Auth: header `x-api-key: {IKODDI_API_KEY}` on every call, plus the
        organization/group id as a URL path segment (`IKODDI_GROUP_ID`).

        Send OTP:
            POST {IKODDI_BASE_URL}/groups/{group_id}/otp/{otp_app_id}/sms/{identity}
            No request body.
            Response (200): {"status": 0, "otpToken": "<opaque token>"}

        Verify OTP:
            POST {IKODDI_BASE_URL}/groups/{group_id}/otp/{otp_app_id}/verify
            Body: {"verificationKey": <otpToken>, "otp": <code>, "identity": <identity>}
            Response (200): {"status": 0, "message": "OTP Matched for ..."}
            `status` is 0 on success, -1 on failure (wrong/expired code) -
            IKODDI does not document a separate "expired" vs "wrong code"
            distinction, both come back as status -1.

        IKODDI does not document a configurable code length, expiration or
        attempt limit for OTP As A Service - none of those are invented
        here; only what is documented above is implemented.
    """

    def __init__(self, client=None):
        self._client = client or requests

    def _base(self):
        return settings.IKODDI_BASE_URL.rstrip('/')

    def _headers(self):
        return {
            'Content-Type': 'application/json',
            'x-api-key': settings.IKODDI_API_KEY,
        }

    def _group_app_path(self):
        return f'groups/{settings.IKODDI_GROUP_ID}/otp/{settings.IKODDI_OTP_APP_ID}'

    def send_otp(self, phone_number, channel='sms'):
        """Returns the opaque `otpToken` to store as PhoneOtp.verification_key."""
        identity = _ikoddi_identity(phone_number)
        url = f'{self._base()}/{self._group_app_path()}/{channel}/{identity}'
        try:
            response = self._client.post(url, headers=self._headers(), timeout=settings.IKODDI_TIMEOUT_SECONDS)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise IkoddiError(f'IKODDI unreachable: {exc}') from exc

        data = self._decode(response)
        if response.status_code >= 400 or data.get('status') != 0:
            # The exact cause is logged server-side only - never returned
            # as-is to the client (could echo back internal details).
            logger.warning('IKODDI send OTP failed (%s): %s', response.status_code, data)
            raise IkoddiError('IKODDI OTP send failed')

        otp_token = data.get('otpToken')
        if not otp_token:
            raise IkoddiError('IKODDI response has no otpToken')
        return otp_token

    def verify_otp(self, phone_number, verification_key, code):
        """Returns True on a matched code, False on a documented status -1
        rejection. Raises IkoddiError only for transport/format failures -
        a wrong/expired code is a normal, expected False, not an error."""
        identity = _ikoddi_identity(phone_number)
        url = f'{self._base()}/{self._group_app_path()}/verify'
        try:
            response = self._client.post(
                url,
                json={'verificationKey': verification_key, 'otp': str(code), 'identity': identity},
                headers=self._headers(),
                timeout=settings.IKODDI_TIMEOUT_SECONDS,
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise IkoddiError(f'IKODDI unreachable: {exc}') from exc

        data = self._decode(response)
        if response.status_code >= 400:
            logger.warning('IKODDI verify OTP failed (%s): %s', response.status_code, data)
            raise IkoddiError('IKODDI OTP verification failed')
        return data.get('status') == 0

    def _decode(self, response):
        try:
            return response.json()
        except ValueError as exc:
            raise IkoddiError('Invalid IKODDI response') from exc


def ensure_ikoddi_configured():
    if not (settings.IKODDI_API_KEY and settings.IKODDI_GROUP_ID and settings.IKODDI_OTP_APP_ID):
        raise IkoddiError('IKODDI is not configured')
