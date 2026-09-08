import logging
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.conf import settings as dj_settings
from django.db import transaction as db_transaction
from django.db.models import F, Prefetch
from django.utils import timezone
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.correlation import set_correlation_id
from apps.core.models import (
    Device, Gateway, Notification, Operator, Payment, Service, Transaction, TransactionAttempt, TransactionEvent,
    UssdCode, UssdCodeNotConfigured, UssdCodeRenderError, hash_gateway_secret,
)
from apps.core.serializers import gateway_task_payload, notification_payload, resolve_ussd_code, transaction_payload

logger = logging.getLogger(__name__)
from apps.core.services.retry_manager import RetryManager
from apps.core.services.transaction_state_machine import TransactionStateMachine
from apps.devices.models import SmsTask
from apps.devices.services.gateway_manager import IN_FLIGHT_STATUSES, GatewayManager
from apps.devices.services.reservation_manager import ReservationManager
from apps.devices.services.scheduler import Scheduler
from apps.devices.services.transaction_dispatcher import (
    ScenarioConfigurationError,
    fail_interactive_attempt,
    validate_scenario_code,
)
from apps.payments.providers.base import PaymentProviderError
from apps.payments.providers.registry import SUPPORTED_METHODS

SUPPORTED_JEKO_PAYMENT_METHODS = {'wave', 'orange', 'mtn', 'moov', 'djamo'}
from apps.payments.services.payment_service import PaymentService


def _sms_task_payload(task):
    return {
        'id': task.id,
        'phone_number': task.phone_number,
        'message': task.message,
        'purpose': task.purpose,
        'created_at': task.created_at.isoformat() if task.created_at else None,
    }


def _money(value, default='0'):
    try:
        return Decimal(str(value or default))
    except Exception:
        return Decimal(default)


def _handle_late_result_after_expiry(tx, latest_attempt, success, result):
    """Business-model audit Phase 3 fix (Blocage 1): a Gateway result that
    arrives after ReservationManager.release_expired() already presumed
    `latest_attempt` timed out (and already scheduled a retry there - see
    that function). `latest_attempt` is, by construction of the caller,
    already the highest attempt_number for this transaction - there is no
    newer attempt to be superseded by within a single request. Never calls
    ReservationManager.release()/RetryManager again for this same attempt
    here - that would double-count GatewaySim's counters or schedule a
    second retry. Always journals the late report."""
    TransactionEvent.log(
        tx, 'late_result_after_expiry',
        attempt_number=latest_attempt.attempt_number, success=success,
        result=result[:200] if result else '',
    )

    latest_attempt.raw_response = result
    if not success:
        latest_attempt.failure_reason = _classify_failure_reason(result)
    latest_attempt.status = 'success' if success else 'failed'
    latest_attempt.save(update_fields=['raw_response', 'failure_reason', 'status'])

    if success and not TransactionStateMachine.is_terminal(tx.status):
        tx.next_retry_at = None
        tx.save(update_fields=['next_retry_at', 'updated_at'])
        TransactionStateMachine.transition(
            tx, 'success', reason='late_ussd_result_after_expiry',
            ussd_result=result[:200] if result else '',
        )
    # A late confirmed failure: the retry release_expired() already
    # scheduled stands as-is - never scheduled a second time here.


def _classify_failure_reason(result_text):
    """Best-effort classification of the Gateway's raw dial response text
    into one of TransactionAttempt.FAILURE_REASON_CHOICES - the native USSD
    response is free text, not a structured error code. 'unknown' is always
    the safe default (never blocks a legitimate retry the way wrongly
    classifying as 'invalid_number' would). Refine the keywords as real
    device response strings become known."""
    text = (result_text or '').lower()
    if 'insuffisant' in text or 'insufficient' in text:
        return 'insufficient_balance'
    if 'invalide' in text or 'invalid' in text:
        return 'invalid_number'
    if 'reseau' in text or 'réseau' in text or 'network' in text:
        return 'network_error'
    if 'delai' in text or 'délai' in text or 'timeout' in text or 'expired' in text:
        return 'timeout'
    return 'unknown'


def _safe_gateway_task_payload(tx):
    """Same as gateway_task_payload(tx), but never raises: by the time this
    is called in TransactionResultView, ReservationManager/RetryManager/
    TransactionStateMachine have already committed the real state change -
    only the response body's ussd_code is at risk if the operator/service's
    USSD config is broken, so degrade to None there rather than 500ing a
    request whose important side effects already succeeded."""
    try:
        return gateway_task_payload(tx)
    except (UssdCodeNotConfigured, UssdCodeRenderError) as exc:
        logger.error('gateway_task_payload failed for transaction %s: %s', tx.reference, exc)
        # A truthy placeholder bypasses build_ussd_code() inside
        # gateway_task_payload() (which does `ussd_code or build_ussd_code(tx)`
        # - an empty/falsy override would just re-trigger the same raise),
        # then overwritten with the honest None below.
        payload = gateway_task_payload(tx, ussd_code='__unavailable__')
        payload['ussd_code'] = None
        return payload


def _gateway_payload(gateway):
    return {
        'id': gateway.id,
        'uuid': gateway.host or str(gateway.id),
        'name': gateway.name,
        'heartbeat_status': gateway.status,
        'last_checkin': gateway.last_heartbeat.isoformat() if gateway.last_heartbeat else None,
        'device': {
            'uuid': gateway.host or str(gateway.id),
            'phone_number': gateway.name,
            'details': {'operator': gateway.name.split(' - ')[0] if gateway.name else 'Inconnu'},
        },
    }


def _resolve_operator(request):
    """Strict lookup, never creates - business-model audit Phase 3: a client-
    sent operator_id/name must already exist and be active, or the request
    is rejected. Replaces the old Operator.objects.get_or_create(name=...),
    which let any string a client sent spawn a permanent catalog row.
    operator_id is authoritative when present; the name path is a temporary
    compatibility seam for clients not yet updated (logged so real usage is
    visible before it is ever removed)."""
    operator_id = request.data.get('operator_id')
    if operator_id is not None:
        operator = Operator.objects.filter(id=operator_id, is_active=True).first()
        if operator is None:
            return None, Response({'error': f'operator_id={operator_id} introuvable ou inactif'}, status=404)
        return operator, None
    operator_name = request.data.get('operator') or request.data.get('operator_name') or 'Orange'
    logger.warning(
        'ExecuteTransactionView: transitional operator name lookup ("%s") - client should send operator_id',
        operator_name,
    )
    operator = Operator.objects.filter(name=operator_name, is_active=True).first()
    if operator is None:
        return None, Response({'error': f'Opérateur "{operator_name}" introuvable ou inactif'}, status=400)
    return operator, None


def _resolve_service(request):
    """See _resolve_operator() - same strict lookup, same transitional name
    seam, for Service instead of Operator."""
    service_id = request.data.get('service_id')
    if service_id is not None:
        service = Service.objects.filter(id=service_id, is_active=True).first()
        if service is None:
            return None, Response({'error': f'service_id={service_id} introuvable ou inactif'}, status=404)
        return service, None
    service_name = request.data.get('service') or request.data.get('service_name') or 'Internet (Pass data)'
    logger.warning(
        'ExecuteTransactionView: transitional service name lookup ("%s") - client should send service_id',
        service_name,
    )
    service = Service.objects.filter(name=service_name, is_active=True).first()
    if service is None:
        service = Service.objects.filter(code=service_name, is_active=True).first()
    if service is None:
        return None, Response({'error': f'Service "{service_name}" introuvable ou inactif'}, status=400)
    return service, None


def _authenticate_gateway(request):
    """Business-model audit Phase 7 (Gateway security): the ONLY source of
    Gateway identity for every Gateway-facing endpoint from here on -
    `gateway_uuid`/`gateway_id` sent by the caller are never trusted for
    identity again, only this header is. A custom header, not
    `Authorization: Bearer` - `rest_framework_simplejwt`'s JWTAuthentication
    is already registered globally (see DEFAULT_AUTHENTICATION_CLASSES) and
    would intercept/reject a bare secret sent that way before this function
    ever ran. Returns (gateway, None) on success, (None, Response) on
    failure - the raw secret is never logged, never echoed back, and never
    stored anywhere but as its own SHA-256 hash (see Gateway.generate_secret)."""
    secret = request.headers.get('X-Gateway-Secret')
    if not secret:
        logger.warning('Gateway auth rejected: no X-Gateway-Secret header on %s', request.path)
        return None, Response({'error': 'Gateway authentication required'}, status=401)
    gateway = Gateway.objects.filter(api_key_hash=hash_gateway_secret(secret)).first()
    if gateway is None:
        logger.warning('Gateway auth rejected: unrecognized secret on %s', request.path)
        return None, Response({'error': 'Invalid Gateway credentials'}, status=401)
    if not gateway.is_active:
        logger.warning('Gateway auth rejected: gateway %s is disabled', gateway.id)
        return None, Response({'error': 'Gateway is disabled'}, status=403)
    return gateway, None


class GatewayListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        gateways = Gateway.objects.filter(is_active=True).order_by('id')
        return Response([_gateway_payload(gateway) for gateway in gateways])


class GatewayHeartbeatView(APIView):
    """B3: thin adapter - all heartbeat logic lives in
    GatewayManager.register_heartbeat() now.

    Business-model audit Phase 7: `gateway_id` (URL kwarg, kept only for
    backward-compatible routing - see apps/devices/urls.py) is never used to
    pick which row this writes to anymore - a caller who merely knows
    another Gateway's numeric id could otherwise overwrite its heartbeat.
    The authenticated Gateway (resolved from the secret) is the only row
    this can ever touch."""

    permission_classes = [AllowAny]

    def post(self, request, gateway_id=None):
        gateway, error = _authenticate_gateway(request)
        if error is not None:
            return error
        gateway = GatewayManager.register_heartbeat(gateway=gateway, payload=request.data)
        return Response(_gateway_payload(gateway))


class ExecuteTransactionView(APIView):
    """AllowAny is kept deliberately (identity architecture audit, Phase 6):
    the existing transaction engine's test suite (idempotency, cross-operator
    gateway selection, the new-engine e2e path) creates transactions
    anonymously via this exact endpoint, and requiring auth here would be an
    unrelated, invasive change to that engine. The real fix is that
    Transaction.user is now always populated from request.user when a valid
    JWT is present (see post() below) - ownership, history and notifications
    all key off that field, never off AllowAny/anonymous access to this
    specific endpoint."""

    permission_classes = [AllowAny]

    @db_transaction.atomic
    def post(self, request):
        # Business-model audit Phase 5: an Idempotency-Key identifies a
        # request, not its business content - two submissions sharing the
        # same operator/service/amount/phone can be two genuinely distinct
        # transfers (e.g. the same recipient twice in a row), so only an
        # explicit key is ever treated as "this is a repeat of that exact
        # attempt". Checked before any other validation: a replay should
        # return the original outcome as cheaply as possible, without
        # re-validating a body that no longer matters.
        idempotency_key = request.headers.get('Idempotency-Key') or request.data.get('idempotency_key')
        if idempotency_key:
            existing = Transaction.objects.select_related('service', 'operator', 'gateway', 'payment').filter(
                idempotency_key=idempotency_key,
            ).first()
            if existing is not None:
                set_correlation_id(str(existing.reference))
                return Response(transaction_payload(existing), status=200)

        phone = request.data.get('phone') or request.data.get('recipient_phone')
        amount = _money(request.data.get('amount'))
        customer = request.data.get('customer') or {}
        payment_method = str(request.data.get('payment_method') or 'auto').lower()
        jeko_payment_method = str(request.data.get('jeko_payment_method') or '').lower()

        if payment_method not in SUPPORTED_METHODS:
            return Response({'error': f'Unsupported payment_method: {payment_method}'}, status=400)
        if jeko_payment_method and jeko_payment_method not in SUPPORTED_JEKO_PAYMENT_METHODS:
            return Response({'error': f'Unsupported jeko_payment_method: {jeko_payment_method}'}, status=400)

        if not phone or amount <= 0:
            return Response({'error': 'phone/recipient_phone and amount are required'}, status=400)
        allowed_amounts = {Decimal(str(value)) for value in (200, 300, 500, 1000, 1500, 2000, 3000, 5000, 10000)}
        if amount not in allowed_amounts:
            return Response({'error': 'Montant non disponible pour une souscription.'}, status=400)

        operator, error = _resolve_operator(request)
        if error is not None:
            return error
        service, error = _resolve_service(request)
        if error is not None:
            return error

        device, _ = Device.objects.get_or_create(
            uid=request.data.get('device_uid') or 'client-app',
            defaults={'primary_phone': phone},
        )
        # Gestion des opérateurs / business-model audit: fail fast, before
        # any provider is ever called, if this (operator, service, amount)
        # has no USSD code configured - build_ussd_code() would otherwise
        # raise UssdCodeNotConfigured inside transaction_payload() *after*
        # PaymentService.initiate() has already created a real checkout
        # session with the provider, which this @db_transaction.atomic
        # rollback cannot undo remotely. The resolved row is reused below as
        # Transaction.ussd_code_used - no second lookup.
        ussd_code = resolve_ussd_code(operator, service, amount)
        if ussd_code is None:
            return Response(
                {
                    'error': (
                        f'Aucun code USSD configuré pour operator="{operator.name}", '
                        f'service="{service.name}", amount={amount}'
                    ),
                },
                status=400,
            )
        try:
            validate_scenario_code(ussd_code)
        except ScenarioConfigurationError as exc:
            return Response({'error': str(exc)}, status=400)
        payment_reference = f'TOL-{timezone.now().strftime("%Y%m%d%H%M%S")}-{uuid4().hex[:8].upper()}'
        payment = Payment.objects.create(
            method=payment_method,
            reference=payment_reference,
            amount=amount,
            status='pending',
        )
        tx_fields = dict(
            device=device,
            # Business-model audit (identity architecture): the owning
            # identity always comes from the verified JWT (request.user),
            # never from a user_id/phone_number the client could send
            # freely - None for a request with no valid Bearer token
            # (device/AllowAny remains the fallback for backward
            # compatibility with the existing transaction engine, see
            # ExecuteTransactionView's class doc), exactly like before this
            # field existed.
            user=request.user if request.user.is_authenticated else None,
            service=service,
            operator=operator,
            gateway=None,
            phone_number=phone,
            amount=amount,
            status='pending',
            payment=payment,
            payment_method=payment_method,
            payment_reference=payment.reference,
            ussd_code_used=ussd_code,
        )
        if idempotency_key:
            # get_or_create() under Transaction.idempotency_key's UNIQUE
            # constraint is what actually makes this race-safe: two requests
            # racing to insert the same key can't both win at the database
            # level, and Django's own get_or_create() already implements
            # "try create(), catch IntegrityError, re-fetch" as a nested
            # atomic()/savepoint - no need to hand-roll that here.
            tx, created = Transaction.objects.get_or_create(idempotency_key=idempotency_key, defaults=tx_fields)
            if not created:
                # Lost the race (or simply arrived after an earlier call with
                # this same key already completed) - this Payment was never
                # attached to anything and never seen by a provider, safe to
                # discard outright.
                payment.delete()
                set_correlation_id(str(tx.reference))
                return Response(transaction_payload(tx), status=200)
        else:
            tx = Transaction.objects.create(**tx_fields)
        # Transaction.reference is the id already shown to the end user and
        # sent to the Android Gateway - adopted as the correlation id for the
        # rest of this payment's lifecycle (logs, provider metadata, webhooks).
        set_correlation_id(str(tx.reference))

        customer_payload = {
            'name': customer.get('name') or request.data.get('customer_name') or 'Client',
            'surname': customer.get('surname') or request.data.get('customer_surname') or 'Transfer On Line',
            'phone': customer.get('phone') or phone,
            'email': customer.get('email') or request.data.get('customer_email') or 'client@example.com',
            'operator': operator.name,
            'operator_code': operator.code,
            'payment_method': jeko_payment_method,
        }

        try:
            PaymentService.initiate(
                payment,
                description=f'{service.name} - souscription',
                customer=customer_payload,
                metadata={'order_id': str(tx.reference), 'correlation_id': str(tx.reference)},
            )
        except PaymentProviderError as exc:
            TransactionStateMachine.transition(tx, 'failed', reason='payment_init_failed', error=str(exc))
            return Response({'error': str(exc), **transaction_payload(tx)}, status=502)

        # PaymentService.initiate() resolves payment_method='auto' to whichever
        # concrete provider actually accepted the payment and updates
        # payment.method accordingly - tx.payment_method was only ever set to
        # the client's original ('auto' or explicit) request value above, so
        # it must be refreshed here or every 'auto' transaction would forever
        # report 'auto' instead of the provider that is actually handling it.
        if tx.payment_method != payment.method:
            tx.payment_method = payment.method
            tx.save(update_fields=['payment_method', 'updated_at'])

        return Response(transaction_payload(tx), status=201)


class TransactionStatusView(APIView):
    """Read-only status lookup for the Flutter Client - the only channel it
    has to learn what actually happened to a transaction after opening the
    payment checkout URL (it has no other way: it never sees webhooks and
    was never given a polling channel before this). Looked up by
    `reference`, not `id` - the Flutter Client only ever receives
    `reference` back from ExecuteTransactionView, never the numeric id.

    AllowAny is kept for the same backward-compatibility reason as
    ExecuteTransactionView - but ownership IS enforced below whenever the
    transaction actually has one: an authenticated user can never read a
    different authenticated user's transaction, even by guessing/sharing a
    reference. A transaction with no owner (anonymous/device-only flow)
    keeps its current behavior unchanged."""

    permission_classes = [AllowAny]

    def get(self, request, reference):
        tx = Transaction.objects.select_related('service', 'operator', 'gateway', 'payment').filter(
            reference=reference,
        ).first()
        if tx is None or (tx.user_id is not None and tx.user_id != getattr(request.user, 'id', None)):
            # Identical response for "doesn't exist" and "isn't yours" -
            # never confirm to a caller that a reference they don't own
            # actually exists.
            return Response({'error': 'Transaction not found'}, status=404)

        try:
            payload = transaction_payload(tx)
        except (UssdCodeNotConfigured, UssdCodeRenderError) as exc:
            # Same degrade-don't-500 pattern already used for this payload
            # elsewhere (see apps.payments.webhooks._safe_transaction_payload) -
            # a broken USSD config must never block the Client from at least
            # learning its payment status.
            logger.error('transaction_payload failed for transaction %s: %s', tx.reference, exc)
            payload = transaction_payload(tx, ussd_code='__unavailable__')
            payload['ussd_code'] = None

        status_value = payload['status']
        payload.update({
            'is_pending': not TransactionStateMachine.is_terminal(status_value),
            'is_success': status_value == 'success',
            'is_failed': status_value == 'failed',
            'is_cancelled': status_value == 'cancelled',
        })
        return Response(payload)


class _PersonalDataPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class MyTransactionsView(APIView):
    """Identity architecture (Phase 7): the customer's own purchase
    history, queried exclusively from `request.user` - never from a
    phone_number/user_id/device_uid the client could send freely. Requires
    a real JWT: unlike ExecuteTransactionView/TransactionStatusView, there
    is no anonymous/device-based equivalent of "my history" to stay
    backward-compatible with, so this is IsAuthenticated from the start."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Transaction.objects.filter(user=request.user).select_related(
            'service', 'operator', 'payment',
        ).order_by('-created_at')
        paginator = _PersonalDataPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        results = [transaction_payload(tx) for tx in page]
        return paginator.get_paginated_response(results)


class NotificationListView(APIView):
    """Identity architecture (Phase 8): every query filtered by
    `request.user` - a user can never list another user's notifications,
    regardless of what id/phone_number/anything else is sent."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(user=request.user).select_related('transaction')
        paginator = _PersonalDataPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        results = [notification_payload(n) for n in page]
        return paginator.get_paginated_response(results)


class UnreadNotificationCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({'unread_count': count})


class MarkNotificationReadView(APIView):
    """Scoped to `request.user` in the same lookup, not checked
    afterwards: a notification belonging to another user simply does not
    exist from this caller's point of view (404, not 403 - never confirms
    it exists for someone else)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        notification = Notification.objects.filter(id=notification_id, user=request.user).first()
        if notification is None:
            return Response({'error': 'Notification not found'}, status=404)
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        return Response(notification_payload(notification))


class OperatorListView(APIView):
    """Read-only catalog for the Flutter Client - lets it show only the
    operators an admin has actually activated from the dashboard instead of
    a hardcoded Orange/MTN/Moov list. No relation to Service exists on the
    model (see UssdCode for the only per-operator/service link, which is
    about USSD dialing templates, not product eligibility), so this is a
    flat list, not filtered by anything else."""

    permission_classes = [AllowAny]

    def get(self, request):
        operators = Operator.objects.filter(is_active=True).order_by('name')
        return Response([{'id': o.id, 'name': o.name, 'code': o.code} for o in operators])


class ServiceListView(APIView):
    """Read-only catalog for the Flutter Client - same rationale as
    OperatorListView."""

    permission_classes = [AllowAny]

    def get(self, request):
        services = Service.objects.filter(is_active=True).order_by('name')
        return Response([{'id': s.id, 'name': s.name, 'code': s.code} for s in services])


class AmountListView(APIView):
    """Business-model audit: lets the Flutter Client know which specific
    montants an admin has configured a dedicated UssdCode for, for a given
    (operator, service) - never a named "forfait", just the number. An empty
    list is itself the answer "no fixed catalog here, free amount entry is
    fine" - resolve_ussd_code()'s amount=NULL generic tier already handles
    any amount for this pair (see serializers.py), this endpoint only
    surfaces the amount-specific overrides, it never invents amounts, and a
    nonexistent/inactive operator or service simply yields an empty list
    like any other unmatched filter, matching the read-only style already
    used by OperatorListView/ServiceListView."""

    permission_classes = [AllowAny]

    def get(self, request, operator_id, service_id):
        amounts = (
            UssdCode.objects
            .filter(operator_id=operator_id, service_id=service_id, is_active=True, amount__isnull=False)
            .order_by('amount')
            .values_list('amount', flat=True)
            .distinct()
        )
        return Response([{'amount': float(a)} for a in amounts])


class PendingTransactionsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        gateway, error = _authenticate_gateway(request)
        if error is not None:
            return error
        # Business-model audit Phase 7: an explicit gateway_uuid is no longer
        # what selects the rows below (the authenticated gateway is) - kept
        # only as a compatibility/consistency check. A caller authenticated
        # as one Gateway but claiming a different uuid is an impersonation
        # attempt, not a routine mismatch, so this rejects outright rather
        # than silently ignoring the mismatched value.
        gateway_uuid = request.query_params.get('gateway_uuid')
        if gateway_uuid and gateway_uuid != gateway.host:
            return Response({'error': 'gateway_uuid does not match the authenticated Gateway'}, status=403)
        queryset = Transaction.objects.select_related('service', 'operator', 'gateway', 'payment').filter(
            status='pending',
            payment__status='accepted',
            gateway_id=gateway.id,
        )
        # Business-model audit Phase 7.2: second barrier, always active
        # regardless of USE_NEW_TRANSACTION_ENGINE - even if a bug elsewhere
        # ever let a mismatched Transaction.gateway slip through, the
        # authenticated Gateway must still actually hold an active SIM for
        # this transaction's operator before it's ever handed the task.
        # .distinct() belongs on THIS filter, not only inside the flag-gated
        # block below: a Gateway can legitimately have two active SIMs for
        # the same operator (real dual-SIM-same-operator phone), and the
        # gateway__sims join would otherwise return that pending transaction
        # twice in the JSON array.
        queryset = queryset.filter(
            gateway__sims__operator=F('operator'), gateway__sims__is_active=True,
        ).distinct()
        # Stabilisation RC1 (priorité haute n°6): without this, gateway_task_payload()
        # runs one extra `attempts` query per transaction when the new engine is on
        # (up to 10 here) - prefetch the same filtered/ordered queryset it needs
        # (exclude(gateway_sim=None).order_by('-attempt_number').first()) once for
        # the whole page, stashed as `sim_attempts` so gateway_task_payload() can
        # read `tx.sim_attempts[0]` instead of issuing its own query. No-op when
        # the flag is off: nothing ever reads `sim_attempts` in that path. The
        # dispatched/executing exclusion below only makes sense once
        # TransactionAttempt rows exist, which - Phase 7.2 - still only
        # happens under the new engine; the legacy path never creates one, so
        # this stays flag-gated (Django compiles .exclude() over a to-many
        # relation as a NOT EXISTS subquery, not a join, so chaining it after
        # the .distinct() above never reintroduces duplicate rows).
        if dj_settings.USE_NEW_TRANSACTION_ENGINE:
            queryset = queryset.exclude(
                attempts__status__in=['dispatched', 'executing'],
            ).prefetch_related(
                Prefetch(
                    'attempts',
                    queryset=TransactionAttempt.objects.exclude(gateway_sim=None)
                    .select_related('gateway_sim')
                    .order_by('-attempt_number'),
                    to_attr='sim_attempts',
                )
            )
        # gateway_task_payload(), not transaction_payload(): the Android Gateway
        # only ever receives a validated task to execute over USSD, never the
        # payment provider name, its reference, status or checkout URL.
        payloads = []
        for tx in queryset.order_by('created_at')[:10]:
            # Business-model audit Phase 7 (double dispatch): claim the
            # attempt (assigned -> dispatched) before ever handing this task
            # out. A plain conditional UPDATE is already atomic under
            # PostgreSQL MVCC - no select_for_update needed, there is no
            # intervening read/decision between the compare and the write.
            # `dispatched`/`dispatched_at` already exist on TransactionAttempt
            # and IN_FLIGHT_STATUSES already treats `dispatched` exactly like
            # `assigned` everywhere it's read (ReservationManager,
            # TransactionResultView) - no new state, no migration.
            if dj_settings.USE_NEW_TRANSACTION_ENGINE:
                sim_attempts = getattr(tx, 'sim_attempts', None)
                attempt = sim_attempts[0] if sim_attempts else None
                if attempt is not None:
                    claimed = TransactionAttempt.objects.filter(
                        pk=attempt.pk, status='assigned',
                    ).update(status='dispatched', dispatched_at=timezone.now())
                    if not claimed:
                        continue  # already dispatched by a concurrent poll
            try:
                payloads.append(gateway_task_payload(tx))
            except (UssdCodeNotConfigured, UssdCodeRenderError) as exc:
                # Gestion des opérateurs: one misconfigured operator/service
                # (USSD code deactivated after this transaction was created,
                # for example) must never break polling for every gateway -
                # skip just this transaction, the RetryManager/Scheduler will
                # revisit it once the config is fixed.
                logger.error('Skipping transaction %s from pending poll: %s', tx.reference, exc)
        return Response(payloads)


class TransactionResultView(APIView):
    permission_classes = [AllowAny]

    @db_transaction.atomic
    def post(self, request):
        gateway, error = _authenticate_gateway(request)
        if error is not None:
            return error
        reference = request.data.get('transaction_reference') or request.data.get('reference')
        success = request.data.get('success') in [True, 'true', 'True', '1', 1]
        result = request.data.get('result') or request.data.get('ussd_response') or ''
        if not reference:
            return Response({'error': 'transaction_reference required'}, status=400)

        # Phase D audit (Critique n°3): lock the Transaction row for the
        # duration of this report. A duplicate/near-simultaneous USSD result
        # for the same transaction is a realistic event on an unreliable
        # mobile network - without this lock, two such reports could both
        # read the same in-flight TransactionAttempt before either commits,
        # each independently calling ReservationManager.release() on it
        # (silently double-incrementing GatewaySim.success_count/
        # failure_count/consecutive_failures) and racing on Transaction.status.
        # Serializing on this row means the second report always re-reads the
        # state the first one already committed, rather than acting on stale
        # data read before either write.
        tx = Transaction.objects.select_for_update().filter(reference=reference).first()
        if tx is None:
            return Response({'error': 'Transaction not found'}, status=404)
        set_correlation_id(str(tx.reference))

        # Business-model audit Phase 7: tx.gateway_id is the authoritative
        # "which physical Gateway currently holds this task" pointer in both
        # the legacy and new-engine paths - set at creation, reassigned on
        # every retry (RetryManager.dispatch_due_retries). Checked BEFORE the
        # is_terminal() duplicate short-circuit below, not after: otherwise
        # an authenticated-but-unrelated Gateway could learn an already-
        # resolved transaction's final state/ussd_code just by posting a
        # bogus result for a reference it observed, without ever having been
        # the Gateway actually dispatched to it. None also rejects - nobody
        # legitimately reports a result for a task never assigned to anyone.
        if tx.gateway_id is None or tx.gateway_id != gateway.id:
            return Response({'error': 'This Gateway was not assigned this transaction'}, status=403)

        if TransactionStateMachine.is_terminal(tx.status):
            # Already resolved by an earlier report for this transaction -
            # a duplicate/retried delivery. Never re-run ReservationManager
            # .release()/RetryManager.handle_failed_attempt() a second time.
            logger.info('%s: ignoring duplicate result report (already %s)', tx.reference, tx.status)
            return Response(_safe_gateway_task_payload(tx))

        if result:
            tx.payment_reference = result[:100]
            tx.save(update_fields=['payment_reference', 'updated_at'])

        attempt = None
        if dj_settings.USE_NEW_TRANSACTION_ENGINE:
            attempt = tx.attempts.filter(status__in=IN_FLIGHT_STATUSES).order_by('-attempt_number').first()
            if attempt is None:
                latest_attempt = tx.attempts.order_by('-attempt_number').first()
                if latest_attempt is not None and latest_attempt.status == 'expired':
                    # Business-model audit Phase 3 (Blocage 1): this is not
                    # necessarily a duplicate - release_expired() may have
                    # only *presumed* a timeout. Handle it as a genuine late
                    # result rather than discarding it outright.
                    _handle_late_result_after_expiry(tx, latest_attempt, success, result)
                    return Response(_safe_gateway_task_payload(tx))
                if tx.attempts.exists():
                    # Every attempt for this transaction is already resolved
                    # ('success'/'failed') - a concurrent/duplicate report got
                    # here first and already released the last in-flight one.
                    # Never re-apply the side effects below on stale information.
                    logger.info('%s: ignoring duplicate result report (no in-flight attempt left)', tx.reference)
                    return Response(_safe_gateway_task_payload(tx))

        if attempt is not None:
            # Business-model audit Phase 2: record what the Gateway actually
            # reported *before* releasing the reservation - RetryManager
            # reads failure_reason (see NON_RETRYABLE_FAILURE_REASONS) right
            # after release(), so it must already be set by then.
            attempt.raw_response = result
            if not success:
                attempt.failure_reason = _classify_failure_reason(result)
            attempt.save(update_fields=['raw_response', 'failure_reason'])
            ReservationManager.release(attempt, 'success' if success else 'failed')
            if not success:
                retry_at = RetryManager.handle_failed_attempt(tx, attempt)
                if retry_at is not None:
                    # A retry is scheduled: the transaction is not
                    # permanently failed, it stays 'pending' (see the mobile
                    # cutover decision - no new status value, isPending on
                    # the Flutter Client keeps meaning exactly what it says).
                    # dispatch_due_retries() reassigns tx.gateway once it
                    # reserves the next attempt, putting it back in front of
                    # whichever gateway polls PendingTransactionsView next.
                    return Response(_safe_gateway_task_payload(tx))

        TransactionStateMachine.transition(
            tx, 'success' if success else 'failed',
            reason='ussd_result_reported', ussd_result=result[:200] if result else '',
        )
        return Response(_safe_gateway_task_payload(tx))


def _resolve_current_or_first_step(attempt):
    """First touch of an attempt's scenario: current_step is still NULL, so
    the first UssdStep (lowest order) of the resolved UssdCode is what the
    Gateway's first NEW_FIELD/FINAL_FIELD event refers to. Returns None if
    the transaction has no resolved UssdCode or the scenario has no steps at
    all (a plain single-shot UssdCode, out of scope for this endpoint)."""
    if attempt.current_step_id is not None:
        return attempt.current_step
    ussd_code = attempt.transaction.ussd_code_used
    if ussd_code is None:
        return None
    return ussd_code.steps.order_by('order').first()


def _resolve_step_fields(step, transaction):
    """FIXED/DYNAMIC resolution (Phase A/B) - reuses UssdCode's own known-
    variable set, never a second variable system. Returns None if a DYNAMIC
    field references a variable this transaction cannot supply (e.g.
    {pin}), same "fail loudly, never guess" posture as UssdCode.render()."""
    context = {
        'numero': transaction.phone_number,
        'montant': int(transaction.amount) if transaction.amount is not None else None,
        'forfait': transaction.service.name if transaction.service_id else None,
        'pin': None,
    }
    values = []
    for field in step.fields.order_by('order'):
        if field.field_type == 'FIXED':
            values.append(field.value)
            continue
        resolved = context.get(field.value)
        if resolved is None:
            return None
        values.append(str(resolved))
    return values


class TransactionStepView(APIView):
    """Phase C: intermediate Gateway <-> Backend exchange during an
    interactive USSD scenario (UssdCode -> UssdStep -> UssdStepField, Phase
    A/B). Deliberately separate from TransactionResultView: that endpoint's
    request/response shape (success/result -> full gateway_task_payload) is
    for the simple one-shot dial path and stays untouched - this endpoint's
    RESULT event reuses the SAME underlying primitives
    (ReservationManager.release/RetryManager.handle_failed_attempt/
    TransactionStateMachine.transition), never a second implementation of
    that decision logic, just a different wire shape for a different
    Gateway workflow.

    Per-event idempotency (Idempotency-Key header, one key per logical
    event - NOT the same concept as Transaction.idempotency_key, which
    dedupes transaction *creation*): select_for_update() alone only
    serializes concurrent requests, it does not make a replayed request
    return anything but "whatever current_step is now" - a network retry of
    an already-answered event would otherwise silently advance the scenario
    a second time. A key matching last_step_idempotency_key short-circuits
    to last_step_response before any resolution/advancement happens."""

    permission_classes = [AllowAny]

    @db_transaction.atomic
    def post(self, request):
        gateway, error = _authenticate_gateway(request)
        if error is not None:
            return error

        reference = request.data.get('transaction_reference')
        attempt_id = request.data.get('attempt_id')
        event = request.data.get('event')
        idempotency_key = request.headers.get('Idempotency-Key') or request.data.get('idempotency_key')

        if not reference or not attempt_id or not event:
            return Response({'error': 'transaction_reference, attempt_id and event are required'}, status=400)
        if not idempotency_key:
            return Response({'error': 'Idempotency-Key header required'}, status=400)
        if event not in ('NEW_FIELD', 'FINAL_FIELD', 'RESULT'):
            return Response({'error': f'Unknown event "{event}"'}, status=400)

        # Locks the row for the whole request: read of current_step/
        # last_step_idempotency_key, resolution, and every write below all
        # happen under this same lock - never released and re-acquired
        # mid-request (business-model audit Phase C, point 8).
        # of=('self',): current_step/gateway_sim are nullable FKs, so the
        # select_related() below compiles to LEFT OUTER JOINs - PostgreSQL
        # refuses a bare FOR UPDATE on the nullable side of one ("FOR UPDATE
        # cannot be applied to the nullable side of an outer join"). This
        # scopes the lock to the TransactionAttempt row alone, exactly what
        # point 8 asks for - the joined rows are only ever read, not locked.
        attempt = TransactionAttempt.objects.select_for_update(of=('self',)).select_related(
            'transaction__service', 'transaction__operator', 'transaction__ussd_code_used',
            'gateway_sim__gateway', 'current_step__ussd_code',
        ).filter(pk=attempt_id, transaction__reference=reference).first()
        if attempt is None:
            return Response({'error': 'Attempt not found for this transaction_reference'}, status=404)

        if attempt.gateway_sim_id is None or attempt.gateway_sim.gateway_id != gateway.id:
            return Response({'error': 'This Gateway was not assigned this attempt'}, status=403)

        if attempt.status not in ('dispatched', 'executing'):
            return Response({'error': f'Attempt is not active (status={attempt.status})'}, status=409)

        set_correlation_id(str(attempt.transaction.reference))

        # Idempotence par événement - avant tout traitement, avant toute
        # avancée de current_step. Un rejeu réseau doit être totalement
        # transparent : ni recalcul, ni second effet de bord.
        if idempotency_key == attempt.last_step_idempotency_key:
            return Response(attempt.last_step_response)

        if attempt.status == 'dispatched':
            attempt.status = 'executing'
            attempt.save(update_fields=['status'])

        if event == 'NEW_FIELD':
            response_body = self._handle_new_field(attempt, request.data)
        elif event == 'FINAL_FIELD':
            response_body = self._handle_final_field(attempt)
        else:
            response_body = self._handle_result(attempt, request.data)

        if response_body.get('action') == 'FAILED':
            response_body['status'] = fail_interactive_attempt(
                attempt,
                response_body.get('error_code', 'unknown'),
                response_body,
            )

        attempt.last_step_idempotency_key = idempotency_key
        attempt.last_step_response = response_body
        attempt.save(update_fields=['last_step_idempotency_key', 'last_step_response', 'current_step'])
        return Response(response_body)

    def _handle_new_field(self, attempt, data):
        step = _resolve_current_or_first_step(attempt)
        if step is None or step.step_type != 'INPUT':
            return {'action': 'FAILED', 'error_code': 'UNKNOWN_SCREEN'}

        raw_field_count = data.get('field_count')
        try:
            field_count = int(raw_field_count)
        except (TypeError, ValueError):
            return {'action': 'FAILED', 'error_code': 'AMBIGUOUS_INPUT'}

        expected_count = step.fields.count()
        if field_count != expected_count:
            # Never guessed: a mismatched field_count never advances
            # current_step, whether reported too high or too low.
            return {'action': 'FAILED', 'error_code': 'AMBIGUOUS_INPUT'}

        values = _resolve_step_fields(step, attempt.transaction)
        if values is None:
            return {'action': 'FAILED', 'error_code': 'INPUT_ERROR'}

        attempt.current_step = step.ussd_code.steps.filter(order__gt=step.order).order_by('order').first()
        return {'action': 'INPUT', 'values': values}

    def _handle_final_field(self, attempt):
        step = _resolve_current_or_first_step(attempt)
        if step is None or step.step_type != 'FINAL_FIELD':
            return {'action': 'FAILED', 'error_code': 'UNKNOWN_SCREEN'}
        # current_step deliberately left untouched: FINAL_FIELD marks "no
        # more values to send", not a transition to a further step.
        return {'action': 'DONE'}

    def _handle_result(self, attempt, data):
        status_value = (data.get('status') or '').upper()
        if status_value not in ('SUCCESS', 'FAILED'):
            return {'action': 'FAILED', 'error_code': 'INVALID_RESULT_STATUS'}
        # Full operator message, never truncated (unlike
        # Transaction.payment_reference's 100-char cap used by the simple
        # TransactionResultView path) - raw_response is an unbounded
        # TextField precisely so the complete message survives.
        operator_message = data.get('operator_message') or ''
        error_code = data.get('error_code') or ''
        success = status_value == 'SUCCESS'

        attempt.raw_response = operator_message
        if not success:
            attempt.failure_reason = error_code if error_code in dict(TransactionAttempt.FAILURE_REASON_CHOICES) else 'unknown'
        attempt.save(update_fields=['raw_response', 'failure_reason'])

        tx = attempt.transaction
        # Reuses the exact same primitives TransactionResultView already
        # calls for the simple path - no second success/failure decision
        # engine.
        ReservationManager.release(attempt, 'success' if success else 'failed')
        if not success:
            retry_at = RetryManager.handle_failed_attempt(tx, attempt)
            if retry_at is not None:
                return {'action': 'DONE', 'status': 'RETRY_SCHEDULED'}
        TransactionStateMachine.transition(
            tx, 'success' if success else 'failed',
            reason='ussd_step_result_reported', ussd_result=operator_message[:200],
        )
        return {'action': 'DONE', 'status': status_value}


class SmsPendingView(APIView):
    """Same polling contract as PendingTransactionsView, but for SMS jobs
    (currently just OTP codes - see apps.accounts.services.request_otp)
    instead of USSD tasks. Kept as a separate endpoint/model rather than
    merged into the transaction queue: an SMS job has no payment, no USSD
    code, and a different payload shape - mixing the two would complicate
    the Gateway app's dispatch logic for no real benefit."""

    permission_classes = [AllowAny]

    def get(self, request):
        gateway, error = _authenticate_gateway(request)
        if error is not None:
            return error
        queryset = SmsTask.objects.filter(status='pending').order_by('created_at')[:10]
        return Response([_sms_task_payload(task) for task in queryset])


class SmsResultView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        gateway, error = _authenticate_gateway(request)
        if error is not None:
            return error
        task_id = request.data.get('id')
        success = request.data.get('success') in [True, 'true', 'True', '1', 1]
        if not task_id:
            return Response({'error': 'id required'}, status=400)

        task = SmsTask.objects.filter(id=task_id).first()
        if task is None:
            return Response({'error': 'SMS task not found'}, status=404)

        task.status = 'sent' if success else 'failed'
        task.sent_at = timezone.now()
        # Business-model audit Phase 7: the authenticated Gateway, never a
        # self-declared gateway_uuid from the body - SmsTask has no per-
        # gateway reservation/claim concept (any authenticated Gateway may
        # pick up any pending SMS job), so there is no ownership check to
        # make here beyond "the caller is a real, active Gateway."
        task.gateway = gateway
        task.save(update_fields=['status', 'sent_at', 'gateway'])
        return Response({'id': task.id, 'status': task.status})
