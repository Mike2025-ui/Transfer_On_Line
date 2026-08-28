from django.db import models


class WebhookEvent(models.Model):
    """Audit trail + idempotency guard for inbound provider webhooks.

    A duplicate delivery (same provider + event_id) is detected via the
    unique_together constraint before any side effect is applied, so a
    replayed payment.success can never re-trigger downstream processing."""

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=150)
    event_type = models.CharField(max_length=50, blank=True)
    signature = models.TextField(blank=True)
    headers = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True, null=True)
    processed = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('provider', 'event_id')]
        indexes = [models.Index(fields=['provider', 'payment_reference'])]

    def __str__(self):
        return f'{self.provider}:{self.event_type or "event"}:{self.event_id}'
