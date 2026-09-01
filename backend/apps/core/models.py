import hashlib
import re
import secrets
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def hash_gateway_secret(secret):
    """One-way, deterministic - lets Gateway.api_key_hash be looked up
    directly by hash equality (no separate id/prefix needed), same as how
    a plain unique column is already used for lookup elsewhere in this
    project (e.g. Transaction.reference)."""
    return hashlib.sha256(secret.encode()).hexdigest()


def _default_max_concurrent_tasks():
    """Callable default (not a bare int) so it reads GATEWAY_MANAGER at row
    creation time, not at class-definition/import time - matters for tests
    that override the setting."""
    return settings.GATEWAY_MANAGER['MAX_CONCURRENT_TASKS']

class Device(models.Model):
    uid = models.CharField(max_length=100, unique=True)
    primary_phone = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.uid} - {self.primary_phone}"

class Service(models.Model):
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=20)
    # Additive (Étape 4, module "Services / Forfaits"): same pattern as
    # Operator.is_active - lets an admin retire a service/package from the
    # dashboard without deleting it (deletion is blocked whenever a
    # Transaction references it, same guard as operator_delete).
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class Operator(models.Model):
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=10)
    # Additive (Gestion des opérateurs): lets an admin take an operator
    # network-wide out of rotation (e.g. USSD down for maintenance) without
    # touching each UssdCode individually. Not read anywhere yet outside the
    # dashboard CRUD - existing transaction/gateway selection logic is
    # unaffected until a future phase wires it in.
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class UssdCodeNotConfigured(Exception):
    """Raised by build_ussd_code() when no active UssdCode matches
    (operator, service) and no active operator-level fallback (service=None)
    exists either. Deliberately not a silent fallback: composing a guessed
    USSD string for a real money-moving transaction is worse than failing
    loudly here."""


class UssdCodeRenderError(Exception):
    """Raised by UssdCode.render() when the template references a variable
    the current transaction context can't supply (e.g. {pin} - see
    backend/docs/operators-ussd-codes.md for why that variable has no data
    source yet)."""


USSD_TEMPLATE_VAR_RE = re.compile(r'\{(\w+)\}')
USSD_TEMPLATE_KNOWN_VARS = {'numero', 'montant', 'forfait', 'pin'}


class UssdCode(models.Model):
    """A dashboard-configurable USSD dial template for one operator, and
    optionally one specific service - replaces the hardcoded formulas that
    used to live in apps.core.serializers.build_ussd_code(). service=None
    means "generic fallback for this operator, used when no service-specific
    row is active" (see resolve_ussd_code() in serializers.py)."""

    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name='ussd_codes')
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='ussd_codes', null=True, blank=True)
    # Business-model audit (Operator -> Service -> Amount -> UssdCode):
    # amount=NULL means "generic, works for whatever montant the transaction
    # carries" (today's only behavior, preserved as the fallback tier) -
    # amount=500 means "only used when the transaction's amount is exactly
    # 500", for operators whose real dial code genuinely differs per bundle
    # price rather than accepting {montant} as a free parameter. See
    # resolve_ussd_code()'s 3-level cascade in serializers.py.
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    label = models.CharField(max_length=100)
    template = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    # Informational only - service IS NULL is the real fallback signal
    # (already guaranteed unique per operator by the constraint below).
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['operator__name', 'service__name', 'label']
        constraints = [
            # nulls_distinct=False: without it, Postgres treats every NULL
            # `amount` (and every NULL `service`) as distinct from every
            # other NULL for uniqueness purposes, so two active "generic"
            # rows for the same (operator, service) could silently coexist -
            # verified empirically against this project's dev database
            # before adding this. Requires
            # connection.features.supports_nulls_distinct_unique_constraints
            # (True here: Postgres, confirmed for this project's DB).
            models.UniqueConstraint(
                fields=['operator', 'service', 'amount'],
                condition=models.Q(is_active=True),
                nulls_distinct=False,
                name='unique_active_ussd_code_per_operator_service_amount',
            ),
        ]
        indexes = [
            models.Index(fields=['operator', 'service', 'is_active']),
        ]

    def __str__(self):
        service_label = self.service.name if self.service else 'Tous services'
        return f'{self.operator.name} - {service_label} - {self.label}'

    def render(self, context: dict) -> str:
        """Substitutes {numero}/{montant}/{forfait}/{pin} placeholders in
        self.template. Fails loudly (never leaves a literal {placeholder} in
        a string that could be dialed) on either an unknown variable name
        (ValueError - a template authoring mistake) or a known variable the
        caller's context doesn't provide (UssdCodeRenderError - a data
        availability gap, e.g. {pin})."""
        used = set(USSD_TEMPLATE_VAR_RE.findall(self.template))
        unknown = used - USSD_TEMPLATE_KNOWN_VARS
        if unknown:
            raise ValueError(f'Unknown template variable(s) {sorted(unknown)} in UssdCode #{self.pk}')
        missing = used - context.keys()
        if missing:
            raise UssdCodeRenderError(
                f'UssdCode #{self.pk} ("{self.label}") requires {sorted(missing)}, '
                f'which no data source currently provides for this transaction.'
            )
        return self.template.format(**{k: context[k] for k in used})


class UssdStep(models.Model):
    """One ordered step of an interactive USSD scenario attached to a
    UssdCode (Phase A) - deliberately NOT a separate UssdScenario model:
    UssdCode already uniquely identifies (operator, service, amount) and
    already carries the initial dial code, so a scenario's steps hang
    directly off the UssdCode row that produces its opening code. A
    UssdCode with zero steps is exactly today's single-shot behavior,
    unchanged - this model is purely additive."""

    STEP_TYPE_CHOICES = [
        ('INPUT', 'Saisie'),
        ('FINAL_FIELD', 'Fin de saisie (attendre le résultat opérateur)'),
    ]

    ussd_code = models.ForeignKey(UssdCode, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveSmallIntegerField()
    step_type = models.CharField(max_length=20, choices=STEP_TYPE_CHOICES, default='INPUT')
    name = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['ussd_code', 'order'], name='unique_step_order_per_ussd_code'),
        ]
        indexes = [
            models.Index(fields=['ussd_code', 'order']),
        ]

    def __str__(self):
        return f'{self.ussd_code} - étape {self.order} ({self.step_type})'

    def clean(self):
        # Only checks already-persisted children (self.pk required to query
        # self.fields) - the authoritative, pre-save guard for the Admin
        # formset case is UssdStepFieldInlineFormSet.clean() in admin.py,
        # since a step and its brand-new fields can be submitted together
        # in one Admin form before either has a pk to query by.
        if self.step_type == 'FINAL_FIELD' and self.pk and self.fields.exists():
            raise ValidationError('Une étape FINAL_FIELD ne peut contenir aucun champ.')


class UssdStepField(models.Model):
    """One value to enter within a UssdStep - several may exist per step
    (Phase A, point 4/9: a single USSD screen can present multiple input
    fields). FIXED.value is a literal to type as-is; DYNAMIC.value is the
    exact name (no braces) of a variable from the *existing*
    USSD_TEMPLATE_KNOWN_VARS set already used by UssdCode.render() -
    deliberately not a new/parallel variable system."""

    FIELD_TYPE_CHOICES = [
        ('FIXED', 'Valeur fixe'),
        ('DYNAMIC', 'Variable dynamique'),
    ]

    step = models.ForeignKey(UssdStep, on_delete=models.CASCADE, related_name='fields')
    order = models.PositiveSmallIntegerField()
    field_type = models.CharField(max_length=10, choices=FIELD_TYPE_CHOICES)
    value = models.CharField(max_length=100)

    class Meta:
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['step', 'order'], name='unique_field_order_per_step'),
        ]

    def __str__(self):
        return f'{self.step} - champ {self.order} ({self.field_type}={self.value})'

    def clean(self):
        if not self.value or not self.value.strip():
            raise ValidationError('La valeur ne peut pas être vide.')
        if self.field_type == 'DYNAMIC' and self.value not in USSD_TEMPLATE_KNOWN_VARS:
            raise ValidationError(
                f"Variable inconnue '{self.value}'. Autorisées : {sorted(USSD_TEMPLATE_KNOWN_VARS)}"
            )
        if self.step_id and self.step.step_type == 'FINAL_FIELD':
            raise ValidationError('Une étape FINAL_FIELD ne peut pas avoir de champ.')


class Gateway(models.Model):
    name = models.CharField(max_length=100)
    host = models.CharField(max_length=255, blank=True, null=True)
    port = models.IntegerField(default=8080)
    is_active = models.BooleanField(default=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default='offline')
    # Phase B (B1): consumed by the Reservation Manager (capacity check) and
    # the GatewayScoreService (battery-aware ranking) - not read by anything
    # yet in B1 itself, see the Transaction Engine spec §1/§2.
    max_concurrent_tasks = models.PositiveSmallIntegerField(default=_default_max_concurrent_tasks)
    battery_level = models.PositiveSmallIntegerField(null=True, blank=True)
    # Phase B (B2): extended heartbeat telemetry. All optional - an older
    # mobile app build that doesn't send them yet must keep working
    # unchanged (see GatewayHeartbeatView). Populated over time as the
    # Android Gateway app is updated to report each of them.
    temperature = models.FloatField(null=True, blank=True)
    ram_available_mb = models.PositiveIntegerField(null=True, blank=True)
    storage_available_mb = models.PositiveIntegerField(null=True, blank=True)
    network_type = models.CharField(max_length=20, blank=True)
    signal_strength = models.SmallIntegerField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    app_version = models.CharField(max_length=20, blank=True)
    is_busy = models.BooleanField(default=False)
    reported_task_count = models.PositiveSmallIntegerField(null=True, blank=True)
    # Business-model audit Phase 7 (Gateway security): distinct from `host`
    # (a self-declared, unauthenticated identifier) - only the SHA-256 hash
    # is ever stored, never the plaintext secret. Null for any Gateway that
    # has not been through the admin enrollment action yet, which is exactly
    # the intended "unenrolled Gateway can never authenticate" behavior, not
    # a gap to fill in.
    api_key_hash = models.CharField(max_length=64, blank=True, null=True, unique=True)

    def generate_secret(self):
        """Issues a new secret for this Gateway, stores only its hash, and
        returns the plaintext exactly once - the only time it ever exists
        outside the physical device it gets compiled into (see
        GatewayAdmin's enrollment action). Overwrites any previous secret,
        immediately invalidating it."""
        secret = secrets.token_urlsafe(32)
        self.api_key_hash = hash_gateway_secret(secret)
        self.save(update_fields=['api_key_hash'])
        return secret

    def __str__(self):
        return self.name

class Payment(models.Model):
    METHOD_CHOICES = [
        ('auto', 'Automatique (relais)'),
        ('jeko', 'Jèko'),
        ('geniuspay', 'GeniusPay'),
    ]
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('accepted', 'Accepté'),
        ('refused', 'Refusé'),
        ('cancelled', 'Annulé'),
        ('failed', 'Échoué'),
    ]
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    reference = models.CharField(max_length=100, unique=True)
    provider_transaction_id = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    checkout_url = models.URLField(blank=True, null=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.method} - {self.reference}"

class Transaction(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('processing', 'En cours'),
        ('success', 'Réussi'),
        ('failed', 'Échoué'),
        ('cancelled', 'Annulé'),
    ]

    reference = models.CharField(max_length=50, unique=True, default=uuid.uuid4)
    # Business-model audit Phase 5: client-supplied request identity, distinct
    # from `reference` (server-generated, changes on every call by design).
    # Null for every caller that sends none - a repeated request without a
    # key stays undeduplicated on purpose (see ExecuteTransactionView.post()
    # and tests_idempotency.py for why content alone is never a safe dedup
    # signal in a money-transfer app).
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='transactions',
    )  # nullable: existing anonymous flow via `device` keeps working unchanged
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE)
    gateway = models.ForeignKey(Gateway, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    phone_number = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    payment_method = models.CharField(max_length=20, choices=Payment.METHOD_CHOICES, blank=True, null=True)
    payment_reference = models.CharField(max_length=100, blank=True, null=True)
    # Business-model audit: purely informational pointer to the UssdCode row
    # that resolve_ussd_code() picked for this transaction at creation time -
    # SET_NULL so an admin can still delete/retire an old configuration
    # later without being blocked by transaction history. The literal dialed
    # string (which survives even if this row disappears) already lives on
    # TransactionAttempt.ussd_code - this field only answers "which
    # configuration produced it", for audit/debugging.
    ussd_code_used = models.ForeignKey(
        'UssdCode', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions_used_in',
    )
    # Phase B: set by RetryManager when a failed attempt is eligible for an
    # automatic retry; cleared once that retry has been dispatched (or
    # exhausted). Not read by anything outside RetryManager yet - see
    # apps.core.services.retry_manager.
    next_retry_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.commission:
            self.commission = self.amount * Decimal('0.01')
        super().save(*args, **kwargs)

    def sync_from_payment(self):
        """Derive our own status from the linked Payment's status.

        Phase D audit (Critique n°1): an accepted payment must never resolve
        to the terminal 'failed' status just because no Gateway happened to
        be assigned yet (e.g. every Gateway was offline when this Transaction
        was created) - 'failed' has no outgoing transitions
        (TransactionStateMachine.TRANSITIONS), so that used to strand an
        already-paid customer permanently, with no automatic recovery path.
        'pending' is correct here regardless of `self.gateway`: money has
        been captured, so the transaction stays open/actionable rather than
        being written off. Note this fix does not by itself get such a
        transaction assigned to a Gateway - see the Phase D report for that
        residual gap, deliberately left out of this minimal fix to avoid
        introducing a new double-dispatch risk."""
        from apps.core.services.transaction_state_machine import TransactionStateMachine

        if not self.payment:
            return
        new_status = 'pending' if self.payment.status == 'accepted' else 'failed'
        TransactionStateMachine.transition(self, new_status, reason='payment_status_synced', payment_status=self.payment.status)

    def __str__(self):
        return f"{self.reference} - {self.amount} FCFA"

class TransactionEvent(models.Model):
    """Timestamped audit log of everything meaningful that happens to a
    Transaction - not just status changes (TransactionStateMachine is one
    caller among possibly several: retry decisions, dispatch attempts,
    webhook-driven updates can all log here too). `metadata` is a free-form
    JSON bag deliberately not modeled as separate columns - the set of
    interesting fields differs per event_type and will keep growing as more
    of the Transaction Engine gets built; a rigid schema would need a
    migration for every new event type."""

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=50)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['transaction', 'created_at'])]

    @classmethod
    def log(cls, transaction, event_type, **metadata):
        return cls.objects.create(transaction=transaction, event_type=event_type, metadata=metadata)

    def __str__(self):
        return f'{self.transaction.reference} - {self.event_type} @ {self.created_at}'


class Notification(models.Model):
    """A persistent, in-app notification belonging to exactly one
    authenticated identity (settings.AUTH_USER_MODEL) - never to a phone
    number, device or Transaction directly, so it survives a phone change
    or reinstall exactly like Transaction.user does. Created ONLY once a
    Transaction genuinely reaches a terminal state (see
    create_for_transaction_status(), called from
    TransactionStateMachine.transition() - the single authority for every
    status change) - never optimistically at creation time, and never via
    an SMS (SMS costs money; this is the in-app channel the business-model
    audit explicitly asked to be preferred instead)."""

    TYPE_CHOICES = [
        ('transaction_success', 'Transaction réussie'),
        ('transaction_failed', 'Transaction échouée'),
        ('transaction_cancelled', 'Transaction annulée'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField()
    type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    # SET_NULL, not CASCADE: a Transaction being purged later (if that ever
    # happens) must never silently delete the user's notification history.
    transaction = models.ForeignKey(
        Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications',
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f'{self.title} -> user_id={self.user_id} ({"lu" if self.is_read else "non lu"})'

    @classmethod
    def create_for_transaction_status(cls, transaction, status):
        """Called only from TransactionStateMachine.transition(), only for
        a status that is both terminal and genuinely new (never a reflexive
        re-apply of the same status). Returns None (no notification
        created) for a Transaction with no authenticated owner
        (transaction.user_id is None) - there is no identity to notify."""
        if transaction.user_id is None:
            return None
        labels = {
            'success': ('Transaction réussie', 'transaction_success'),
            'failed': ('Transaction échouée', 'transaction_failed'),
            'cancelled': ('Transaction annulée', 'transaction_cancelled'),
        }
        if status not in labels:
            return None
        title, notif_type = labels[status]
        message = f'{transaction.service.name} - {transaction.amount} FCFA - Référence {transaction.reference}'
        return cls.objects.create(
            user_id=transaction.user_id, title=title, message=message, type=notif_type, transaction=transaction,
        )


class TransactionAttempt(models.Model):
    """One row per execution attempt for a Transaction - the Reservation
    Manager creates this row as the reservation itself (status='assigned')
    rather than a separate Reservation model, since the two would carry the
    exact same lifecycle. A Transaction can have several of these if the
    first attempt fails and a retry runs on a different SIM; today
    Transaction only ever points at a single gateway, so a retry silently
    overwrote history - this is what makes retries auditable.

    Lives in apps.core (not apps.devices) per the validated Phase B
    architecture: it belongs to the Transaction Engine's domain even though
    it references a devices.GatewaySim."""

    STATUS_CHOICES = [
        ('assigned', 'Assignée'),
        ('dispatched', 'Envoyée'),
        ('executing', 'En cours'),
        ('success', 'Réussie'),
        ('failed', 'Échouée'),
        ('expired', 'Expirée'),
    ]
    FAILURE_REASON_CHOICES = [
        ('insufficient_balance', 'Solde insuffisant'),
        ('invalid_number', 'Numéro invalide'),
        ('network_error', 'Erreur réseau'),
        ('timeout', 'Délai dépassé'),
        ('unknown', 'Inconnue'),
    ]

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='attempts')
    attempt_number = models.PositiveSmallIntegerField()
    gateway_sim = models.ForeignKey('devices.GatewaySim', on_delete=models.SET_NULL, null=True, blank=True, related_name='attempts')
    ussd_code = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='assigned')
    dispatched_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    raw_response = models.TextField(blank=True)
    failure_reason = models.CharField(max_length=30, choices=FAILURE_REASON_CHOICES, blank=True)
    # Phase C (moteur USSD interactif) - progression du scénario, distincte
    # d'attempt_number (qui reste le compteur de RETRY, jamais mélangé avec
    # ceci). NULL = aucune étape encore répondue (le prochain NEW_FIELD/
    # FINAL_FIELD résout la première UssdStep du scénario).
    current_step = models.ForeignKey(
        'UssdStep', on_delete=models.SET_NULL, null=True, blank=True, related_name='attempts_at_this_step',
    )
    # Idempotence PAR ÉVÉNEMENT (pas par transaction, voir Transaction.
    # idempotency_key pour ce cas différent) : protège contre le rejeu réseau
    # d'une même requête de step après que current_step a déjà avancé -
    # select_for_update() seul protège la concurrence, pas le rejeu (deux
    # requêtes strictement identiques, l'une après l'autre, pas en même
    # temps). Une clé identique à la dernière traitée renvoie
    # last_step_response tel quel, sans recalcul ni avancée.
    last_step_idempotency_key = models.CharField(max_length=100, blank=True)
    last_step_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['transaction', 'attempt_number'], name='unique_transaction_attempt_number'),
        ]
        indexes = [
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.transaction.reference} - tentative {self.attempt_number} ({self.status})"

class Refund(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
        ('completed', 'Terminé'),
    ]
    METHOD_CHOICES = [
        ('provider_auto', 'Automatique (fournisseur)'),
        ('manual', 'Manuel'),
    ]
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_comment = models.TextField(blank=True, null=True)
    # Phase B (B1): not consumed by any service yet - RefundService (later
    # in Phase B) will be the first reader/writer of these three fields.
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, blank=True)
    provider_refund_id = models.CharField(max_length=100, blank=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='processed_refunds')
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Remboursement pour {self.transaction.reference}"

class Settings(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.key} = {self.value}"

class AdminProfile(models.Model):
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='admin_profile')
    phone = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return self.user.username

class AuditLog(models.Model):
    admin = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.admin} - {self.action} - {self.timestamp}"

