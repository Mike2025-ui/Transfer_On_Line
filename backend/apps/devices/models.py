from django.db import models


class GatewaySim(models.Model):
    """One row per physical SIM card inserted in a Gateway phone - a dual-SIM
    phone produces two rows. This is the piece that lets the Scheduler (Phase
    B, B4) guarantee an Orange transaction is only ever dialed from an Orange
    SIM - GatewayManager.select_operator_gateway() enforces the exact same
    rule for the legacy engine too (business-model audit Phase 7.2).

    success_count/failure_count/consecutive_failures are deliberately
    denormalized counters (not computed via COUNT() on TransactionAttempt at
    selection time) - the Scheduler runs this lookup on every dispatch, and
    at 100 phones that must stay a cheap indexed read, not an aggregate query
    over the whole attempt history."""

    gateway = models.ForeignKey('core.Gateway', on_delete=models.CASCADE, related_name='sims')
    operator = models.ForeignKey('core.Operator', on_delete=models.CASCADE, related_name='gateway_sims')
    msisdn = models.CharField(max_length=20, blank=True)
    slot = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    success_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['gateway', 'slot'], name='unique_gateway_slot'),
        ]
        indexes = [
            models.Index(fields=['operator', 'is_active']),
        ]

    def __str__(self):
        return f'{self.gateway.name} - slot {self.slot} - {self.operator.name}'


class SmsTask(models.Model):
    """A validated SMS job for an Android Gateway phone to send - the same
    'server creates a task, a Gateway polls and reports the result' pattern
    already used for USSD transactions (se.views), just for
    SMS instead of a USSD dial. Kept as its own model/endpoints rather than
    folded into Transaction polling: the payload shape and lifecycle are
    different (no payment involved, no USSD code), and mixing the two would
    complicate the Gateway app's dispatch logic for no benefit."""

    PURPOSE_CHOICES = [
        ('otp', 'Code de vérification'),
        ('notification', 'Notification'),
    ]
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('sent', 'Envoyé'),
        ('failed', 'Échoué'),
    ]

    phone_number = models.CharField(max_length=20)
    message = models.CharField(max_length=160)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    gateway = models.ForeignKey(
        'core.Gateway', null=True, blank=True, on_delete=models.SET_NULL, related_name='sms_tasks',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.purpose} -> {self.phone_number} ({self.status})'
