import logging
import re
import secrets

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import EmailVerificationCode

logger = logging.getLogger(__name__)


class OtpError(Exception):
    """Raised for any OTP flow failure the view should turn into a 4xx -
    the message is safe to show to the client (never leaks internals)."""


class AionError(Exception):
    """Raised for any Aion Messaging API failure - never shown directly to
    the client, only logged; request_otp()/verify_otp() translate it to a
    generic OtpError."""


def normalize_phone_number(raw):
    """Returns a real E.164 number (leading '+' plus country code) - Aion's
    API requires this, it is not cosmetic. A local Côte d'Ivoire mobile
    number (10 digits, e.g. 07XXXXXXXX - the leading digit is part of the
    subscriber number since the 2021 renumbering, not a trunk prefix to
    drop) gets +225 prepended as-is; any other number must already carry
    its own country code, since guessing one would risk silently
    mis-routing the code to the wrong country."""
    if not raw:
        raise OtpError('phone_number is required')
    cleaned = re.sub(r'[^\d+]', '', str(raw))
    digits_only = re.sub(r'\D', '', cleaned)
    if len(digits_only) < 8:
        raise OtpError('phone_number is not a valid number')
    if cleaned.startswith('+'):
        return cleaned
    if len(digits_only) == 10:
        return f'+225{digits_only}'
    raise OtpError('phone_number must include a country code (e.g. +225...)')


def _aion_headers():
    # Aion's docs accept either X-API-Key or Authorization: Bearer for every
    # endpoint - X-API-Key kept for consistency with the rest of this file's
    # existing Aion calls (see e.g. the wallet endpoints if they get added).
    return {'X-API-Key': settings.AION_API_KEY, 'Content-Type': 'application/json'}


def _ensure_aion_configured():
    if not (settings.AION_API_KEY and settings.AION_SENDER_ID):
        raise OtpError('Aion Messaging is not configured')


def _aion_post(path, json_body):
    """Shared POST plumbing for every Aion Messaging call in this module -
    one place for the base URL, timeout, transport-error translation and
    JSON-decoding, so /verify/start and /verify/check never duplicate it."""
    try:
        response = requests.post(
            f'{settings.AION_BASE_URL.rstrip("/")}/{path}',
            json=json_body,
            headers=_aion_headers(),
            timeout=20,
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        raise AionError(f'Aion Messaging unreachable: {exc}') from exc

    if response.status_code >= 400:
        # 401 (bad/missing key), 422 (validation error - includes an
        # invalid/expired code for /verify/check, per Aion's documented HTTP
        # status table, which is generic across every endpoint), 429 (rate
        # limit), 500 (provider error). The exact cause is logged
        # server-side only, never returned as-is to the client.
        raise AionError(f'Aion Messaging returned {response.status_code}: {response.text[:200]}')

    try:
        data = response.json()
    except ValueError as exc:
        raise AionError('Invalid Aion Messaging response') from exc
    if not data.get('success', True):
        raise AionError(f'Aion Messaging reported failure: {data}')
    return data


def _verify_start(phone_number):
    """POST /verify/start - documented request body is {phone, sender_id};
    the success response body is NOT shown in Aion's docs, only the fact
    that /verify/check later requires a `verification_id`. Treated like
    every other Aion endpoint here: HTTP 2xx with no explicit
    `success: false` is the positive case, and the response must carry a
    `verification_id` for the flow to continue at all."""
    return _aion_post('verify/start', {'phone': phone_number, 'sender_id': settings.AION_SENDER_ID})


def _verify_check(verification_id, code):
    """POST /verify/check - documented request body is {verification_id,
    code}; the response body is NOT shown in Aion's docs either. Same
    defensive rule as _verify_start: only HTTP 2xx without an explicit
    `success: false` is treated as "code accepted" - any other outcome
    (4xx/5xx, network error, `success: false`) is treated as "code invalid
    or expired", never as a crash. This exact behaviour should be confirmed
    against a real Aion account once one is available (see
    RealAionVerifyTests in tests.py)."""
    return _aion_post('verify/check', {'verification_id': verification_id, 'code': code})


def request_otp(raw_phone_number):
    """Aion Messaging is the sole OTP provider: it generates the code, sends
    it, and later validates it - Django never sees the code itself and
    stores no OTP state locally. Returns the `verification_id` Aion assigns
    to this attempt; the caller (RequestOtpView) hands it to the client,
    which must send it back unchanged with the submitted code (see
    VerifyOtpSerializer) - this is the identifier Aion's own /verify/check
    contract requires, nothing invented beyond that."""
    phone_number = normalize_phone_number(raw_phone_number)
    _ensure_aion_configured()
    try:
        data = _verify_start(phone_number)
    except AionError as exc:
        logger.warning('Aion Messaging verify/start failed for %s: %s', phone_number, exc)
        raise OtpError('Unable to send verification code') from exc

    verification_id = data.get('verification_id')
    if verification_id is None:
        logger.error('Aion Messaging verify/start response had no verification_id: %s', data)
        raise OtpError('Unable to send verification code')

    logger.info('Aion Messaging OTP started for %s (verification_id=%s)', phone_number, verification_id)
    return verification_id


def verify_otp(raw_phone_number, submitted_code, verification_id):
    """Validates the code against Aion (the only verifier - no local
    fallback), then creates (or reuses) the auth.User for this phone number
    - username=phone_number, set_unusable_password() - so a given number
    always resolves to the same account across devices. This identity logic
    is provider-agnostic and unchanged from before this migration."""
    phone_number = normalize_phone_number(raw_phone_number)
    if not verification_id:
        raise OtpError('verification_id is required')

    try:
        _verify_check(verification_id, submitted_code)
    except AionError as exc:
        logger.warning('Aion Messaging verify/check failed for %s: %s', phone_number, exc)
        raise OtpError('Code invalide ou expiré') from exc

    User = get_user_model()
    user, created = User.objects.get_or_create(username=phone_number)
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
        logger.info('Created customer account for %s (user_id=%s)', phone_number, user.pk)

    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])
    return user


def request_email_code(email):
    email = email.strip().lower()
    code = f'{secrets.randbelow(1_000_000):06d}'
    EmailVerificationCode.objects.filter(email=email).delete()
    verification = EmailVerificationCode.objects.create(
        email=email,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    subject = 'Votre code de vérification Transfer On Line'
    text = f'Votre code est {code}. Il expire dans 10 minutes.'
    if settings.RESEND_API_KEY:
        try:
            response = requests.post(
                'https://api.resend.com/emails',
                headers={
                    'Authorization': f'Bearer {settings.RESEND_API_KEY}',
                    'Content-Type': 'application/json',
                },
                json={
                    'from': settings.RESEND_FROM_EMAIL,
                    'to': [email],
                    'subject': subject,
                    'text': text,
                    'html': f'<p>{text}</p>',
                },
                timeout=20,
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise OtpError('Impossible d’envoyer le code par email') from exc
        if response.status_code >= 400:
            logger.warning('Resend email failed: %s', response.text[:200])
            raise OtpError('Impossible d’envoyer le code par email')
    else:
        send_mail(subject, text, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
    return verification.pk


def verify_email_code(email, submitted_code, verification_id):
    email = email.strip().lower()
    verification = EmailVerificationCode.objects.filter(pk=verification_id, email=email).first()
    if verification is None or verification.expires_at <= timezone.now() or verification.attempts >= 5:
        raise OtpError('Code invalide ou expiré')
    verification.attempts += 1
    verification.save(update_fields=['attempts'])
    if not check_password(submitted_code, verification.code_hash):
        raise OtpError('Code invalide ou expiré')
    User = get_user_model()
    user, created = User.objects.get_or_create(username=email, defaults={'email': email})
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    verification.delete()
    return user
