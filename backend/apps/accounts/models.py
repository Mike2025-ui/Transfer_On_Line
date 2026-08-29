from django.db import models


class PhoneOtp(models.Model):
    """Tracks one OTP round-trip with IKODDI (see
    apps.accounts.services.ikoddi_service) for a phone number.

    IKODDI's OTP-as-a-Service (https://docs.ikoddi.com/docs/guides/otp-guide)
    generates, sends AND verifies the code itself - Django never sees the
    plaintext code and never generates or hashes one locally. What Django
    stores here is the opaque `verificationKey` IKODDI returns when the code
    is sent (renamed `verification_key`): it has to be replayed back on the
    `/otp/{app}/verify` call to identify which pending code is being checked.
    It is a bearer-style token, not the code itself, but it is still only
    ever used server-side - never returned to the Flutter client.

    IKODDI's own documentation does not expose a configurable expiration or
    a maximum-attempts setting, so `attempts` is Django's own defensive
    3-tries cap (see otp_service.verify_otp) - genuine expiry is left
    entirely to IKODDI's `/verify` response (status -1) rather than
    guessed and enforced a second time with a fabricated TTL."""

    phone_number = models.CharField(max_length=20, db_index=True)
    verification_key = models.TextField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['phone_number', 'created_at'])]

    def __str__(self):
        return f'OTP for {self.phone_number} ({"used" if self.consumed_at else "pending"})'
