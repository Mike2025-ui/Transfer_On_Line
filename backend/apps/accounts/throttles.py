from rest_framework.throttling import SimpleRateThrottle


class PhoneNumberOtpThrottle(SimpleRateThrottle):
    """Throttles by the phone_number in the request body rather than by IP -
    an IP-based limit would not stop someone spamming SMS to a victim's
    number from different networks, and would incorrectly limit many
    customers sharing one NAT/IP. Rate is OTP_REQUEST_THROTTLE_RATE (see
    settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['otp-request'])."""

    scope = 'otp-request'

    def get_cache_key(self, request, view):
        phone_number = request.data.get('phone_number')
        if not phone_number:
            return None  # missing field -> serializer validation returns 400, nothing to throttle
        return self.cache_format % {'scope': self.scope, 'ident': str(phone_number).strip()}
