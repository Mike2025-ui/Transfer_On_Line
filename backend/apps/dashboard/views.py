import json

from django.conf import settings as dj_settings
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction as db_transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from apps.core.health import check_database, check_provider_reachable, check_redis, gateway_summary
from apps.core.models import (
    AuditLog, Gateway, Operator, Payment, Service, Transaction, TransactionAttempt, TransactionEvent,
    UssdCode, UssdCodeRenderError, UssdStep, UssdStepField, USSD_TEMPLATE_KNOWN_VARS,
)
from apps.core.views import _run_concurrently
from apps.dashboard.forms import OperatorForm, ServiceForm, UssdCodeForm
from apps.devices.models import GatewaySim
from apps.devices.services.gateway_manager import IN_FLIGHT_STATUSES, GatewayManager
from apps.devices.services.gateway_score import GatewayScoreService
from apps.payments.models import WebhookEvent
from apps.payments.services.payment_service import PaymentService

# Back Office audit (Étape 3 - pourquoi certains clics redirigeaient vers
# Django Admin): django.contrib.admin.views.decorators.staff_member_required
# hardcodes login_url='admin:login' as a literal string default - it never
# reads settings.LOGIN_URL - so a bare @staff_member_required imported from
# Django Admin sends any unauthenticated/non-staff visitor straight to
# Django Admin's own login page. Built here on the auth app's own
# user_passes_test (which does take an explicit login_url) instead, pointing
# at this app's own login view - every existing @staff_member_required call
# site keeps working unchanged, same name, same behavior otherwise.
staff_member_required = user_passes_test(
    lambda u: u.is_active and u.is_staff,
    login_url='dashboard_login',
)


def dashboard_login(request):
    """The Back Office's own login page - session-based, entirely separate
    from Django Admin's (/admin/login/, left untouched) and from the mobile
    API's JWT auth (apps.accounts). A valid account that isn't staff is
    bounced back here with an error rather than granted access."""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('dashboard')
    error = None
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if not user.is_staff:
                error = "Ce compte n'a pas accès au Back Office."
            else:
                auth_login(request, user)
                return redirect(next_url or 'dashboard')
        else:
            error = "Identifiant ou mot de passe incorrect."
    else:
        form = AuthenticationForm(request)
    return render(request, 'dashboard/login.html', {'form': form, 'error': error, 'next': next_url})


def dashboard_logout(request):
    if request.method == 'POST':
        auth_logout(request)
    return redirect('dashboard_login')


def write_audit_log(request, action, details):
    """Shared by every Gestion des opérateurs write view - keeps the
    AuditLog.objects.create(...) call and its shape consistent instead of
    duplicating it in each view. `request.user` is AnonymousUser on the
    read-only views (no auth there), but every caller of this helper sits
    behind @staff_member_required, so request.user is always a real User."""
    AuditLog.objects.create(admin=request.user, action=action, details=details)

@staff_member_required
def dashboard_index(request):
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)

    transactions_today = Transaction.objects.filter(created_at__date=today).count()
    transactions_yesterday = Transaction.objects.filter(created_at__date=yesterday).count()
    pct_vs_yesterday = ((transactions_today - transactions_yesterday) / transactions_yesterday * 100) if transactions_yesterday else 0.0

    amount_today = Transaction.objects.filter(status='success', created_at__date=today).aggregate(Sum('amount'))['amount__sum'] or 0
    amount_yesterday = Transaction.objects.filter(status='success', created_at__date=yesterday).aggregate(Sum('amount'))['amount__sum'] or 0
    amount_pct = ((amount_today - amount_yesterday) / amount_yesterday * 100) if amount_yesterday else 0.0

    commission_today = amount_today * Decimal('0.01')

    total_transactions = Transaction.objects.count() or 1
    success_count = Transaction.objects.filter(status='success').count()
    failed_count = Transaction.objects.filter(status='failed').count()
    pending_count = Transaction.objects.filter(status='pending').count()

    success_percent = (success_count / total_transactions) * 100
    failed_percent = (failed_count / total_transactions) * 100
    pending_percent = (pending_count / total_transactions) * 100

    recent_transactions = Transaction.objects.select_related('service', 'operator', 'gateway').order_by('-created_at')[:10]

    services_distribution = Service.objects.annotate(
        count=Count('transaction', filter=Q(transaction__status='success'))
    ).values('name', 'count').order_by('-count')
    operators_distribution = Operator.objects.annotate(
        count=Count('transaction', filter=Q(transaction__status='success'))
    ).values('name', 'count').order_by('-count')

    gateway_stats = GatewayManager.pool_stats()
    sims_available = GatewaySim.objects.filter(is_active=True).count()
    payments_success = Payment.objects.filter(status='accepted').count()
    payments_pending = Payment.objects.filter(status='pending').count()

    # Réel, pas fabriqué : les 8 derniers événements de transaction
    # réellement journalisés (TransactionEvent), pas un texte de
    # remplissage inventé quand peu de données existent.
    recent_activities = [
        {
            'message': f'{event.transaction.reference} — {event.event_type}',
            'time': event.created_at.strftime('%H:%M:%S'),
        }
        for event in TransactionEvent.objects.select_related('transaction').order_by('-created_at')[:8]
    ]

    context = {
        'gateways_online': gateway_stats['online_gateways'],
        'gateways_offline': gateway_stats['offline_gateways'],
        'sims_available': sims_available,
        'payments_success': payments_success,
        'payments_pending': payments_pending,
        'operators_distribution': operators_distribution,
        'transactions_today': transactions_today,
        'pct_vs_yesterday': pct_vs_yesterday,
        'amount_today': amount_today,
        'amount_pct': amount_pct,
        'commission_today': commission_today,
        'success_count': success_count,
        'success_percent': success_percent,
        'failed_count': failed_count,
        'failed_percent': failed_percent,
        'pending_count': pending_count,
        'pending_percent': pending_percent,
        'recent_transactions': recent_transactions,
        'services_distribution': services_distribution,
        'recent_activities': recent_activities,
    }
    return render(request, 'dashboard/index.html', context)

# Pages restées hors du périmètre Étape 3/4 (non listées dans la nouvelle
# navigation demandée) - conservées telles quelles, URLs et vues inchangées,
# simplement retirées de la sidebar pour ne pas dupliquer Transactions/
# Journal d'audit sous un autre nom.
@staff_member_required
def refunds_list(request):
    return render(request, 'dashboard/refunds.html', {'title': 'Remboursements'})

@staff_member_required
def clients_list(request):
    return render(request, 'dashboard/clients.html', {'title': 'Clients'})

@staff_member_required
def reports_list(request):
    return render(request, 'dashboard/reports.html', {'title': 'Rapports'})

@staff_member_required
def notifications_list(request):
    return render(request, 'dashboard/notifications.html', {'title': 'Notifications'})

@staff_member_required
def settings_view(request):
    return render(request, 'dashboard/settings.html', {'title': 'Paramètres'})


# --- Transactions ------------------------------------------------------------

_TRANSACTION_SORT_FIELDS = {
    'date': '-created_at', 'date_asc': 'created_at',
    'amount': '-amount', 'amount_asc': 'amount',
    'status': 'status',
}


@staff_member_required
def transactions_list(request):
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    operator_id = request.GET.get('operator', '')
    service_id = request.GET.get('service', '')
    sort = request.GET.get('sort', 'date')

    transactions = Transaction.objects.select_related(
        'service', 'operator', 'gateway', 'payment',
    ).annotate(attempt_count=Count('attempts')).prefetch_related(
        # Same pattern as PendingTransactionsView's sim_attempts Prefetch
        # (apps/devices/views.py) - the latest attempt that actually got a
        # SIM assigned, so the "SIM" column shows a real GatewaySim, not
        # Gateway.host (the device UUID, unrelated to which physical SIM
        # dialed this transaction).
        Prefetch(
            'attempts',
            queryset=TransactionAttempt.objects.exclude(gateway_sim=None)
            .select_related('gateway_sim').order_by('-attempt_number'),
            to_attr='sim_attempts',
        )
    )
    if query:
        transactions = transactions.filter(Q(reference__icontains=query) | Q(phone_number__icontains=query))
    if status:
        transactions = transactions.filter(status=status)
    if operator_id:
        transactions = transactions.filter(operator_id=operator_id)
    if service_id:
        transactions = transactions.filter(service_id=service_id)
    transactions = transactions.order_by(_TRANSACTION_SORT_FIELDS.get(sort, '-created_at'))

    page = Paginator(transactions, 25).get_page(request.GET.get('page'))
    for tx in page.object_list:
        tx.latest_sim = tx.sim_attempts[0].gateway_sim if tx.sim_attempts else None
    return render(request, 'dashboard/transactions.html', {
        'title': 'Transactions', 'page_obj': page, 'query': query, 'status': status,
        'operator_id': operator_id, 'service_id': service_id, 'sort': sort,
        'status_choices': Transaction.STATUS_CHOICES,
        'operators': Operator.objects.order_by('name'), 'services': Service.objects.order_by('name'),
    })


@staff_member_required
def transaction_detail(request, pk):
    """Historique = les vraies lignes TransactionEvent/TransactionAttempt de
    cette transaction - pas un deuxième système d'historique parallèle."""
    tx = get_object_or_404(
        Transaction.objects.select_related('service', 'operator', 'gateway', 'payment', 'device'), pk=pk,
    )
    events = tx.events.all()  # Meta.ordering = ['created_at'] on TransactionEvent
    attempts = tx.attempts.select_related('gateway_sim__gateway', 'gateway_sim__operator').order_by('attempt_number')
    return render(request, 'dashboard/transaction_detail.html', {
        'title': f'Transaction {tx.reference}', 'tx': tx, 'events': events, 'attempts': attempts,
    })


# --- Paiements -----------------------------------------------------------------

@staff_member_required
def payments_list(request):
    query = request.GET.get('q', '').strip()
    method = request.GET.get('method', '')
    status = request.GET.get('status', '')

    payments = Payment.objects.all()
    if query:
        payments = payments.filter(Q(reference__icontains=query) | Q(provider_transaction_id__icontains=query))
    if method:
        payments = payments.filter(method=method)
    if status:
        payments = payments.filter(status=status)
    payments = payments.order_by('-created_at')

    page = Paginator(payments, 25).get_page(request.GET.get('page'))
    # Each Payment's related Transaction (0 or 1 today) fetched in one extra
    # query rather than N+1 in the template - Payment has no direct FK back,
    # the relation is Transaction.payment, so this is the cheapest safe way.
    tx_by_payment = {
        tx.payment_id: tx
        for tx in Transaction.objects.filter(payment_id__in=[p.id for p in page.object_list]).select_related('operator', 'service')
    }
    for payment in page.object_list:
        payment.transaction = tx_by_payment.get(payment.id)

    checks = _run_concurrently({
        'database': check_database,
        'redis': check_redis,
        'geniuspay': lambda: check_provider_reachable(dj_settings.GENIUSPAY_BASE_URL),
        'jeko': lambda: check_provider_reachable(dj_settings.JEKO_BASE_URL),
        'gateway': gateway_summary,
    })
    recent_failed_attempts = (
        TransactionAttempt.objects.filter(status='failed')
        .select_related('transaction')
        .order_by('-created_at')[:10]
    )

    return render(request, 'dashboard/payments.html', {
        'title': 'Paiements', 'page_obj': page, 'query': query, 'method': method, 'status': status,
        'method_choices': Payment.METHOD_CHOICES, 'status_choices': Payment.STATUS_CHOICES,
        'funnel': PaymentService.funnel_summary(),
        'checks': checks,
        'redis_configured': bool(dj_settings.REDIS_URL),
        'pending_transactions': Transaction.objects.filter(status='pending').count(),
        'recent_failed_attempts': recent_failed_attempts,
        'checked_at': timezone.now(),
        # Constat vérifié (audit préalable) - pas une supposition : webhook
        # GeniusPay refuse toute livraison réelle tant que
        # GENIUSPAY_WEBHOOK_SECRET est vide et GENIUSPAY_ALLOW_MOCK est faux.
        'geniuspay_webhook_misconfigured': (
            not dj_settings.GENIUSPAY_WEBHOOK_SECRET and not dj_settings.GENIUSPAY_ALLOW_MOCK
        ),
    })


# --- Gateways ------------------------------------------------------------------

@staff_member_required
def gateways_list(request):
    gateways = [GatewayManager.gateway_state(gw) for gw in Gateway.objects.filter(is_active=True).order_by('name')]
    return render(request, 'dashboard/gateways.html', {
        'title': 'Gateways', 'gateways': gateways, 'stats': GatewayManager.pool_stats(),
    })


@staff_member_required
def gateway_toggle(request, pk):
    """Activer/désactiver une Gateway sans passer par Django Admin - même
    mécanique que ussd_code_toggle (JSON, CSRF via en-tête, journalisé)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    gateway = get_object_or_404(Gateway, pk=pk)
    gateway.is_active = not gateway.is_active
    gateway.save(update_fields=['is_active'])
    write_audit_log(
        request, 'gateway.activate' if gateway.is_active else 'gateway.deactivate',
        f'Gateway {"activée" if gateway.is_active else "désactivée"}: {gateway.name}',
    )
    return JsonResponse({'id': gateway.id, 'is_active': gateway.is_active})


# --- SIM -------------------------------------------------------------------

@staff_member_required
def gateway_sims_list(request):
    operator_id = request.GET.get('operator', '')
    active = request.GET.get('active', '')
    sims = GatewaySim.objects.select_related('gateway', 'operator')
    if operator_id:
        sims = sims.filter(operator_id=operator_id)
    if active == 'active':
        sims = sims.filter(is_active=True)
    elif active == 'inactive':
        sims = sims.filter(is_active=False)
    # Same in_flight annotation GatewayManager.eligible_sims() uses, so
    # GatewayScoreService.score() (reused as-is, not reimplemented) reflects
    # real current load rather than defaulting every row to "no load".
    sims = sims.annotate(
        in_flight=Count('gateway__sims__attempts', filter=Q(gateway__sims__attempts__status__in=IN_FLIGHT_STATUSES), distinct=True),
    ).order_by('gateway__name', 'slot')

    rows = []
    for sim in sims:
        rows.append({'sim': sim, 'score': round(GatewayScoreService.score(sim), 2)})

    page = Paginator(rows, 25).get_page(request.GET.get('page'))
    return render(request, 'dashboard/sims.html', {
        'title': 'Cartes SIM', 'page_obj': page,
        'operators': Operator.objects.order_by('name'), 'operator_id': operator_id, 'active': active,
    })


@staff_member_required
def sim_toggle(request, pk):
    """Activer/désactiver une carte SIM sans passer par Django Admin (qui ne
    l'expose même pas aujourd'hui - GatewaySim n'y est pas enregistrée)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    sim = get_object_or_404(GatewaySim, pk=pk)
    sim.is_active = not sim.is_active
    sim.save(update_fields=['is_active'])
    write_audit_log(
        request, 'sim.activate' if sim.is_active else 'sim.deactivate',
        f'SIM {"activée" if sim.is_active else "désactivée"}: {sim.gateway.name} slot {sim.slot} ({sim.operator.name})',
    )
    return JsonResponse({'id': sim.id, 'is_active': sim.is_active})


# --- Scheduler ---------------------------------------------------------------

@staff_member_required
def scheduler_monitor(request):
    """Consultation seule - aucune logique de sélection Gateway/SIM n'est
    dupliquée ici, uniquement des agrégats sur ce que Scheduler/
    ReservationManager/RetryManager ont déjà écrit (TransactionAttempt,
    TransactionEvent)."""
    attempt_status_counts = dict(
        TransactionAttempt.objects.values_list('status').annotate(c=Count('id')).order_by()
    )
    failure_reason_counts = dict(
        TransactionAttempt.objects.exclude(failure_reason='')
        .values_list('failure_reason').annotate(c=Count('id')).order_by()
    )
    pending_transactions = Transaction.objects.filter(status='pending').count()
    due_retries = Transaction.objects.filter(next_retry_at__isnull=False, next_retry_at__lte=timezone.now()).count()
    recent_events = (
        TransactionEvent.objects.filter(
            event_type__in=[
                'gateway_assigned', 'retry_scheduled', 'retry_exhausted',
                'retry_dispatched', 'retry_no_gateway_available',
            ]
        )
        .select_related('transaction')
        .order_by('-created_at')[:30]
    )
    recent_attempts = (
        TransactionAttempt.objects.select_related('transaction', 'gateway_sim__gateway', 'gateway_sim__operator')
        .order_by('-created_at')[:20]
    )
    return render(request, 'dashboard/scheduler.html', {
        'title': 'Scheduler', 'engine_enabled': dj_settings.USE_NEW_TRANSACTION_ENGINE,
        'attempt_status_counts': attempt_status_counts, 'failure_reason_counts': failure_reason_counts,
        'pending_transactions': pending_transactions, 'due_retries': due_retries,
        'recent_events': recent_events, 'recent_attempts': recent_attempts,
    })


# --- Services / Forfaits -----------------------------------------------------

@staff_member_required
def services_list(request):
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    services = Service.objects.all().order_by('name')
    if query:
        services = services.filter(Q(name__icontains=query) | Q(code__icontains=query))
    if status == 'active':
        services = services.filter(is_active=True)
    elif status == 'inactive':
        services = services.filter(is_active=False)
    services = services.annotate(ussd_code_count=Count('ussd_codes'))
    page = Paginator(services, 20).get_page(request.GET.get('page'))
    return render(request, 'dashboard/services/list.html', {
        'title': 'Services / Forfaits', 'page_obj': page, 'query': query, 'status': status,
    })


@staff_member_required
def service_create(request):
    if request.method == 'POST':
        form = ServiceForm(request.POST)
        if form.is_valid():
            service = form.save()
            write_audit_log(request, 'service.create', f'Service créé: {service.name} (code={service.code})')
            return redirect('services')
    else:
        form = ServiceForm()
    return render(request, 'dashboard/services/form.html', {'title': 'Nouveau service', 'form': form})


@staff_member_required
def service_edit(request, pk):
    service = get_object_or_404(Service, pk=pk)
    if request.method == 'POST':
        form = ServiceForm(request.POST, instance=service)
        if form.is_valid():
            changes = _form_changes_description(form)
            form.save()
            write_audit_log(request, 'service.update', f'Service modifié: {service.name} — {changes}')
            return redirect('services')
    else:
        form = ServiceForm(instance=service)
    return render(request, 'dashboard/services/form.html', {
        'title': f'Modifier {service.name}', 'form': form, 'object': service,
    })


@staff_member_required
def service_delete(request, pk):
    service = get_object_or_404(Service, pk=pk)
    has_transactions = Transaction.objects.filter(service=service).exists()
    if request.method == 'POST':
        if has_transactions:
            return render(request, 'dashboard/services/confirm_delete.html', {
                'title': f'Supprimer {service.name}', 'object': service, 'has_transactions': True,
                'error': "Impossible de supprimer : des transactions existent pour ce service. Désactivez-le à la place.",
            })
        name, code = service.name, service.code
        service.delete()
        write_audit_log(request, 'service.delete', f'Service supprimé: {name} (code={code})')
        return redirect('services')
    return render(request, 'dashboard/services/confirm_delete.html', {
        'title': f'Supprimer {service.name}', 'object': service, 'has_transactions': has_transactions,
    })


# --- Codes USSD (vue globale) -------------------------------------------------

@staff_member_required
def ussd_codes_all(request):
    """Vue transverse, tous opérateurs confondus - le CRUD/l'édition/le
    toggle restent exactement ceux de l'Étape 2 (ussd_code_edit, _toggle,
    _delete, _preview), cette vue n'ajoute qu'un point d'entrée direct depuis
    le menu principal sans passer par un opérateur précis."""
    query = request.GET.get('q', '').strip()
    operator_id = request.GET.get('operator', '')
    service_id = request.GET.get('service', '')
    active = request.GET.get('active', '')
    codes = UssdCode.objects.select_related('operator', 'service')
    if query:
        codes = codes.filter(Q(label__icontains=query) | Q(template__icontains=query))
    if operator_id:
        codes = codes.filter(operator_id=operator_id)
    if service_id:
        codes = codes.filter(service_id=service_id)
    if active == 'active':
        codes = codes.filter(is_active=True)
    elif active == 'inactive':
        codes = codes.filter(is_active=False)
    codes = codes.order_by('operator__name', 'service__name', 'label').annotate(step_count=Count('steps'))

    page = Paginator(codes, 25).get_page(request.GET.get('page'))
    return render(request, 'dashboard/ussd_codes_all.html', {
        'title': 'Codes USSD', 'page_obj': page, 'query': query,
        'operators': Operator.objects.order_by('name'), 'services': Service.objects.order_by('name'),
        'operator_id': operator_id, 'service_id': service_id, 'active': active,
    })


# --- Logs / Événements -------------------------------------------------------

@staff_member_required
def audit_logs(request):
    """Trois journaux réels affichés côte à côte (onglets) - AuditLog
    (actions admin), TransactionEvent (cycle de vie transaction),
    WebhookEvent (livraisons webhook) - aucun nouveau modèle, pas de
    deuxième système d'historique."""
    tab = request.GET.get('tab', 'audit')

    audit_page = tx_event_page = webhook_page = None
    if tab == 'audit':
        logs = AuditLog.objects.select_related('admin').order_by('-timestamp')
        action_filter = request.GET.get('action', '')
        if action_filter:
            logs = logs.filter(action=action_filter)
        audit_page = Paginator(logs, 30).get_page(request.GET.get('page'))
    elif tab == 'transactions':
        events = TransactionEvent.objects.select_related('transaction').order_by('-created_at')
        event_type = request.GET.get('event_type', '')
        if event_type:
            events = events.filter(event_type=event_type)
        tx_event_page = Paginator(events, 30).get_page(request.GET.get('page'))
    elif tab == 'webhooks':
        events = WebhookEvent.objects.order_by('-received_at')
        provider = request.GET.get('provider', '')
        if provider:
            events = events.filter(provider=provider)
        webhook_page = Paginator(events, 30).get_page(request.GET.get('page'))

    return render(request, 'dashboard/audit.html', {
        'title': "Logs / Événements", 'tab': tab,
        'audit_page': audit_page, 'tx_event_page': tx_event_page, 'webhook_page': webhook_page,
        'action_filter': request.GET.get('action', ''), 'event_type_filter': request.GET.get('event_type', ''),
        'provider_filter': request.GET.get('provider', ''),
    })


# --- Santé du système ---------------------------------------------------------

@staff_member_required
def system_health(request):
    """Réutilise exactement les fonctions de apps.core.health (les mêmes que
    /api/health/) - aucune nouvelle vérification inventée. N'affiche 'OK' que
    pour ce qui a été réellement vérifié à l'instant du chargement."""
    checks = _run_concurrently({
        'database': check_database,
        'redis': check_redis,
        'geniuspay': lambda: check_provider_reachable(dj_settings.GENIUSPAY_BASE_URL),
        'jeko': lambda: check_provider_reachable(dj_settings.JEKO_BASE_URL),
        'gateway': gateway_summary,
    })
    recent_failed_attempts = (
        TransactionAttempt.objects.filter(status='failed')
        .select_related('transaction')
        .order_by('-created_at')[:10]
    )
    return render(request, 'dashboard/system_health.html', {
        'title': 'Santé du système', 'checks': checks,
        'pending_transactions': Transaction.objects.filter(status='pending').count(),
        'recent_failed_attempts': recent_failed_attempts,
        'redis_configured': bool(dj_settings.REDIS_URL),
        'checked_at': timezone.now(),
    })


# --- Gestion des opérateurs -------------------------------------------------
# Back Office audit: every dashboard view, read or write, is behind
# @staff_member_required (see its definition near the top of this file) -
# the whole Back Office is staff-only, not just the views that write.

def _form_changes_description(form):
    """Human-readable diff of a bound, valid ModelForm's changed fields, e.g.
    'nom: "Orange" -> "Orange CI"; actif: True -> False'. Matches this repo's
    AuditLog.details convention of plain readable strings, not JSON."""
    parts = []
    for field_name in form.changed_data:
        field = form.fields[field_name]
        old_value = form.initial.get(field_name)
        new_value = form.cleaned_data.get(field_name)
        parts.append(f'{field.label or field_name}: "{old_value}" -> "{new_value}"')
    return '; '.join(parts) if parts else 'aucun changement'


@staff_member_required
def operators_list(request):
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    operators = Operator.objects.all().order_by('name')
    if query:
        operators = operators.filter(Q(name__icontains=query) | Q(code__icontains=query))
    if status == 'active':
        operators = operators.filter(is_active=True)
    elif status == 'inactive':
        operators = operators.filter(is_active=False)
    operators = operators.annotate(ussd_code_count=Count('ussd_codes'))

    page = Paginator(operators, 20).get_page(request.GET.get('page'))
    return render(request, 'dashboard/operators/list.html', {
        'title': 'Opérateurs', 'page_obj': page, 'query': query, 'status': status,
    })


@staff_member_required
def operator_create(request):
    if request.method == 'POST':
        form = OperatorForm(request.POST)
        if form.is_valid():
            operator = form.save()
            write_audit_log(request, 'operator.create', f'Opérateur créé: {operator.name} (code={operator.code})')
            return redirect('operators')
    else:
        form = OperatorForm()
    return render(request, 'dashboard/operators/form.html', {'title': 'Nouvel opérateur', 'form': form})


@staff_member_required
def operator_edit(request, pk):
    operator = get_object_or_404(Operator, pk=pk)
    if request.method == 'POST':
        form = OperatorForm(request.POST, instance=operator)
        if form.is_valid():
            changes = _form_changes_description(form)
            form.save()
            write_audit_log(request, 'operator.update', f'Opérateur modifié: {operator.name} — {changes}')
            return redirect('operators')
    else:
        form = OperatorForm(instance=operator)
    return render(request, 'dashboard/operators/form.html', {
        'title': f'Modifier {operator.name}', 'form': form, 'object': operator,
    })


@staff_member_required
def operator_delete(request, pk):
    operator = get_object_or_404(Operator, pk=pk)
    # FK is CASCADE today (Transaction.operator) - deleting an operator with
    # any transaction history would silently wipe that history. Deactivation
    # is the safe equivalent (see Operator.is_active) and keeps everything.
    has_transactions = Transaction.objects.filter(operator=operator).exists()
    if request.method == 'POST':
        if has_transactions:
            return render(request, 'dashboard/operators/confirm_delete.html', {
                'title': f'Supprimer {operator.name}', 'object': operator, 'has_transactions': True,
                'error': "Impossible de supprimer : des transactions existent pour cet opérateur. Désactivez-le à la place.",
            })
        name, code = operator.name, operator.code
        operator.delete()
        write_audit_log(request, 'operator.delete', f'Opérateur supprimé: {name} (code={code})')
        return redirect('operators')
    return render(request, 'dashboard/operators/confirm_delete.html', {
        'title': f'Supprimer {operator.name}', 'object': operator, 'has_transactions': has_transactions,
    })


@staff_member_required
def ussd_codes_list(request, pk):
    operator = get_object_or_404(Operator, pk=pk)
    codes = operator.ussd_codes.select_related('service').order_by('service__name', 'label').annotate(step_count=Count('steps'))
    service_filter = request.GET.get('service', '')
    active_filter = request.GET.get('active', '')
    query = request.GET.get('q', '').strip()
    if query:
        codes = codes.filter(Q(label__icontains=query) | Q(template__icontains=query))
    if service_filter:
        codes = codes.filter(service_id=service_filter)
    if active_filter == 'active':
        codes = codes.filter(is_active=True)
    elif active_filter == 'inactive':
        codes = codes.filter(is_active=False)

    page = Paginator(codes, 20).get_page(request.GET.get('page'))
    return render(request, 'dashboard/operators/ussd_codes_list.html', {
        'title': f'Codes USSD — {operator.name}', 'operator': operator, 'page_obj': page,
        'services': Service.objects.all().order_by('name'), 'query': query,
        'service_filter': service_filter, 'active_filter': active_filter,
    })


def _serialize_steps(code):
    """UssdStep/UssdStepField -> plain JSON-able structure, in the exact
    order the execution engine itself reads (apps.devices.views:
    _resolve_current_or_first_step/_resolve_step_fields already query
    `.order_by('order')` on both) - what the step/field editor loads is
    always what the Gateway would actually dial."""
    return [
        {
            'order': step.order,
            'step_type': step.step_type,
            'name': step.name,
            'fields': [
                {'order': field.order, 'field_type': field.field_type, 'value': field.value}
                for field in step.fields.order_by('order')
            ],
        }
        for step in code.steps.order_by('order')
    ]


def _safe_parse_for_redisplay(raw):
    """Best-effort re-parse of a submitted steps_json for redisplay after a
    validation error - never raises, falls back to an empty scenario rather
    than losing the whole page. Separate from _parse_steps_json(), which
    intentionally returns None on any error (including a business-rule one)
    and must not be used to decide what the form redisplays."""
    try:
        parsed = json.loads(raw or '[]')
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _parse_steps_json(raw):
    """Validates the dashboard step/field editor's submitted structure
    against exactly the rules the models themselves already enforce
    (UssdStep/UssdStepField.clean(), plus their unique-order constraints) -
    no new business rule invented here. Returns (steps, None) on success or
    (None, [error, ...]) otherwise; never partially applies anything."""
    errors = []
    try:
        steps = json.loads(raw or '[]')
    except (TypeError, ValueError):
        return None, ['Structure des étapes invalide (JSON illisible).']
    if not isinstance(steps, list):
        return None, ['Structure des étapes invalide.']
    if not steps:
        # A UssdCode with zero steps is exactly today's plain single-shot
        # dial (see UssdStep's own docstring) - not an error, this is how a
        # scenario-less code is represented.
        return [], None

    seen_step_orders = set()
    for step_index, step in enumerate(steps, start=1):
        step_type = step.get('step_type')
        order = step.get('order')
        if step_type not in dict(UssdStep.STEP_TYPE_CHOICES):
            errors.append(f'Étape {step_index} : type d\'étape invalide.')
        if not isinstance(order, int) or order < 1:
            errors.append(f'Étape {step_index} : ordre invalide.')
        elif order in seen_step_orders:
            errors.append(f'Étape {step_index} : deux étapes ne peuvent pas avoir le même ordre ({order}).')
        else:
            seen_step_orders.add(order)

        fields = step.get('fields') or []
        if step_type == 'FINAL_FIELD' and fields:
            errors.append(f'Étape {step_index} : une étape "Fin de saisie" ne peut contenir aucune valeur.')
        seen_field_orders = set()
        for field_index, field in enumerate(fields, start=1):
            field_type = field.get('field_type')
            value = str(field.get('value') or '').strip()
            f_order = field.get('order')
            if field_type not in dict(UssdStepField.FIELD_TYPE_CHOICES):
                errors.append(f'Étape {step_index}, valeur {field_index} : type de valeur invalide.')
            if not value:
                errors.append(f'Étape {step_index}, valeur {field_index} : la valeur ne peut pas être vide.')
            elif field_type == 'DYNAMIC' and value not in USSD_TEMPLATE_KNOWN_VARS:
                errors.append(
                    f'Étape {step_index}, valeur {field_index} : variable dynamique inconnue "{value}". '
                    f'Autorisées : {", ".join(sorted(USSD_TEMPLATE_KNOWN_VARS))}.'
                )
            if not isinstance(f_order, int) or f_order < 1:
                errors.append(f'Étape {step_index}, valeur {field_index} : ordre invalide.')
            elif f_order in seen_field_orders:
                errors.append(f'Étape {step_index}, valeur {field_index} : deux valeurs ne peuvent pas avoir le même ordre.')
            else:
                seen_field_orders.add(f_order)

    if errors:
        return None, errors
    return steps, None


def _save_steps(code, steps):
    """Replaces every UssdStep/UssdStepField of `code` with `steps` (already
    validated by _parse_steps_json) - called inside the same db_transaction
    .atomic() block as the UssdCode header save. A full replace rather than
    a diff/patch: simpler and just as safe, since neither model is ever
    referenced by transaction *history* - Transaction.ussd_code_used and
    TransactionAttempt.current_step are both on_delete=SET_NULL (see
    apps.core.models), so deleting old steps only clears an informational
    pointer, never a historical row. code.steps.all().delete() cascades to
    UssdStepField via UssdStepField.step's on_delete=CASCADE."""
    code.steps.all().delete()
    for step_data in steps:
        step = UssdStep.objects.create(
            ussd_code=code, order=step_data['order'],
            step_type=step_data['step_type'], name=step_data.get('name', ''),
        )
        for field_data in step_data.get('fields') or []:
            UssdStepField.objects.create(
                step=step, order=field_data['order'],
                field_type=field_data['field_type'], value=str(field_data['value']).strip(),
            )


@staff_member_required
def ussd_code_create(request, pk):
    operator = get_object_or_404(Operator, pk=pk)
    steps_initial = []
    if request.method == 'POST':
        form = UssdCodeForm(request.POST)
        raw_steps_json = request.POST.get('steps_json', '[]')
        steps, step_errors = _parse_steps_json(raw_steps_json)
        steps_initial = steps if steps is not None else _safe_parse_for_redisplay(raw_steps_json)
        if step_errors:
            for message in step_errors:
                form.add_error(None, message)
        if form.is_valid() and not step_errors:
            code = form.save(commit=False)
            code.operator = operator
            try:
                # A savepoint, not a bare try/except: PostgreSQL aborts the
                # whole enclosing transaction on the first IntegrityError, so
                # without this, every ORM call after the except block (audit
                # log, redirect, even the test client's own assertions) would
                # fail with TransactionManagementError instead of recovering.
                with db_transaction.atomic():
                    code.save()
                    _save_steps(code, steps)
            except IntegrityError:
                form.add_error(
                    None,
                    "Un code actif existe déjà pour ce couple opérateur/service. "
                    "Désactivez-le d'abord si vous voulez le remplacer.",
                )
            else:
                service_name = code.service.name if code.service else 'défaut'
                write_audit_log(
                    request, 'ussd_code.create',
                    f'Code USSD créé: {code.label} pour {operator.name}/{service_name} — '
                    f'template="{code.template}", {len(steps)} étape(s)',
                )
                return redirect('ussd_codes', pk=operator.pk)
    else:
        form = UssdCodeForm()
    return render(request, 'dashboard/operators/ussd_code_form.html', {
        'title': f'Nouveau code USSD — {operator.name}', 'form': form, 'operator': operator,
        'steps_initial': steps_initial,
    })


@staff_member_required
def ussd_code_edit(request, pk):
    code = get_object_or_404(UssdCode, pk=pk)
    operator = code.operator
    steps_initial = _serialize_steps(code)
    if request.method == 'POST':
        form = UssdCodeForm(request.POST, instance=code)
        raw_steps_json = request.POST.get('steps_json', '[]')
        steps, step_errors = _parse_steps_json(raw_steps_json)
        steps_initial = steps if steps is not None else _safe_parse_for_redisplay(raw_steps_json)
        if step_errors:
            for message in step_errors:
                form.add_error(None, message)
        if form.is_valid() and not step_errors:
            changes = _form_changes_description(form)
            try:
                with db_transaction.atomic():
                    form.save()
                    _save_steps(code, steps)
            except IntegrityError:
                form.add_error(
                    None,
                    "Un code actif existe déjà pour ce couple opérateur/service. "
                    "Désactivez-le d'abord si vous voulez le remplacer.",
                )
            else:
                write_audit_log(
                    request, 'ussd_code.update',
                    f'Code USSD modifié: {code.label} ({operator.name}) — {changes}, {len(steps)} étape(s)',
                )
                return redirect('ussd_codes', pk=operator.pk)
    else:
        form = UssdCodeForm(instance=code)
    return render(request, 'dashboard/operators/ussd_code_form.html', {
        'title': f'Modifier {code.label}', 'form': form, 'operator': operator, 'object': code,
        'steps_initial': steps_initial,
    })


@staff_member_required
def ussd_code_delete(request, pk):
    code = get_object_or_404(UssdCode, pk=pk)
    operator = code.operator
    if request.method == 'POST':
        if code.is_default:
            return render(request, 'dashboard/operators/ussd_code_confirm_delete.html', {
                'title': f'Supprimer {code.label}', 'object': code, 'operator': operator,
                'error': "Impossible de supprimer le code par défaut de cet opérateur. Désactivez-le à la place.",
            })
        label, service_name = code.label, (code.service.name if code.service else 'défaut')
        code.delete()
        write_audit_log(request, 'ussd_code.delete', f'Code USSD supprimé: {label} ({operator.name}/{service_name})')
        return redirect('ussd_codes', pk=operator.pk)
    return render(request, 'dashboard/operators/ussd_code_confirm_delete.html', {
        'title': f'Supprimer {code.label}', 'object': code, 'operator': operator,
    })


@staff_member_required
def ussd_code_toggle(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    code = get_object_or_404(UssdCode, pk=pk)
    new_state = not code.is_active
    code.is_active = new_state
    try:
        with db_transaction.atomic():
            code.save(update_fields=['is_active', 'updated_at'])
    except IntegrityError:
        return JsonResponse({
            'error': "Un autre code est déjà actif pour ce couple opérateur/service. Désactivez-le d'abord.",
        }, status=409)
    write_audit_log(
        request, 'ussd_code.activate' if new_state else 'ussd_code.deactivate',
        f'Code USSD {"activé" if new_state else "désactivé"}: {code.label} ({code.operator.name})',
    )
    return JsonResponse({'id': code.id, 'is_active': code.is_active})


@staff_member_required
def ussd_code_preview(request):
    """No DB write - renders `template` against example values so the admin
    can see the result live while editing (Édition rapide requirement)."""
    template = request.GET.get('template', '')
    context = {
        'numero': request.GET.get('numero') or '0700000000',
        'montant': request.GET.get('montant') or '1000',
        'forfait': request.GET.get('forfait') or 'Exemple',
    }
    preview_code = UssdCode(template=template)
    try:
        rendered = preview_code.render(context)
    except (ValueError, UssdCodeRenderError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({'result': rendered})


@staff_member_required
def operators_history(request):
    logs = AuditLog.objects.filter(
        Q(action__startswith='operator.') | Q(action__startswith='ussd_code.')
    ).select_related('admin').order_by('-timestamp')
    action_filter = request.GET.get('action', '')
    if action_filter:
        logs = logs.filter(action=action_filter)
    page = Paginator(logs, 30).get_page(request.GET.get('page'))
    return render(request, 'dashboard/operators/history.html', {
        'title': "Historique des opérateurs", 'page_obj': page, 'action_filter': action_filter,
    })
