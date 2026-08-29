import logging
import re

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import PhoneOtp
from apps.accounts.services.ikoddi_service import IkoddiError, IkoddiService, ensure_ikoddi_configured

logger = logging.getLogger(__name__)

OTP_MAX_ATTEMPTS = 3


class OtpError(Exception):
    """Raised for any OTP flow failure the view should turn into a 4xx -
    the message is safe to show to the client (never leaks internals)."""


def normalize_phone_number(raw):
    """Returns a real E.164 number (leading '+' plus country code) - the
    durable identity key for a User (see verify_otp below). A local Côte
    d'Ivoire mobile number (10 digits, e.g. 07XXXXXXXX - the leading digit is
    part of the subscriber number since the 2021 renumbering, not a trunk
    prefix to drop) gets +225 prepended as-is; any other number must already
    carry its own country code, since guessing one would risk silently
    mis-routing the SMS to the wrong country."""
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


def request_otp(raw_phone_number, ikoddi_service=None):
    """IKODDI's OTP As A Service generates, sends and holds the code itself
    (see ikoddi_service.py's doc) - Django never generates or stores a code
    or a hash of one. What is stored here is only the opaque
    `verificationKey` IKODDI hands back, one fresh PhoneOtp row per request,
    keyed only by phone_number - never a single shared/global "current code"
    variable. Two numbers (or two requests for the same number) never
    interfere with each other; verify_otp() below always resolves to the
    most recent unconsumed row."""
    phone_number = normalize_phone_number(raw_phone_number)
    try:
        ensure_ikoddi_configured()
    except IkoddiError as exc:
        raise OtpError('Unable to send verification code') from exc

    service = ikoddi_service or IkoddiService()
    try:
        otp_token = service.send_otp(phone_number)
    except IkoddiError as exc:
        logger.warning('IKODDI send failed for %s: %s', phone_number, exc)
        raise OtpError('Unable to send verification code') from exc

    PhoneOtp.objects.create(phone_number=phone_number, verification_key=otp_token)
    logger.info('OTP requested for %s', phone_number)


def verify_otp(raw_phone_number, submitted_code, ikoddi_service=None):
    """Resolves the most recent unconsumed PhoneOtp for this number, then
    asks IKODDI to actually verify the code (IKODDI is the source of truth
    for the code itself - Django holds no copy of it to compare against).

    IKODDI's own docs do not document a maximum-attempts behaviour, so
    OTP_MAX_ATTEMPTS is enforced locally: once reached, verification is
    refused without even calling IKODDI again. Genuine expiry is left
    entirely to IKODDI's own `status: -1` response - never guessed with a
    fabricated local TTL.

    On a matched code, creates (or reuses) the auth.User for this phone
    number - username=phone_number, set_unusable_password() - so a given
    number always resolves to the same account across devices, reinstalls
    and new phones. get_or_create() is race-safe here because
    auth.User.username already carries Django's own UNIQUE constraint: two
    concurrent verifications for the same number can't both insert a new
    row, one loses the race and re-fetches the row the other just
    committed."""
    phone_number = normalize_phone_number(raw_phone_number)

    otp = (
        PhoneOtp.objects.filter(phone_number=phone_number, consumed_at__isnull=True)
        .order_by('-created_at')
        .first()
    )
    if otp is None:
        raise OtpError('No pending code for this phone number - request one first')
    if otp.attempts >= OTP_MAX_ATTEMPTS:
        raise OtpError('Too many attempts - request a new code')

    service = ikoddi_service or IkoddiService()
    try:
        matched = service.verify_otp(phone_number, otp.verification_key, submitted_code)
    except IkoddiError as exc:
        logger.warning('IKODDI verify failed for %s: %s', phone_number, exc)
        raise OtpError('Unable to verify code') from exc

    if not matched:
        otp.attempts += 1
        otp.save(update_fields=['attempts'])
        raise OtpError('Invalid or expired code')

    otp.consumed_at = timezone.now()
    otp.save(update_fields=['consumed_at'])

    User = get_user_model()
    user, created = User.objects.get_or_create(username=phone_number)
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
        logger.info('Created customer identity for %s (user_id=%s)', phone_number, user.pk)

    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])
    return user
