from django.shortcuts import render
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from apps.core.models import Transaction, Gateway, Service

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

    real_time_activities = []
    for tx in Transaction.objects.order_by('-created_at')[:5]:
        if tx.status == 'success':
            msg = f"Transaction réussie - {tx.service.name} - {tx.amount} FCFA ({tx.phone_number})"
        elif tx.status == 'failed':
            msg = f"Transaction échouée - {tx.service.name} - {tx.amount} FCFA ({tx.phone_number})"
        else:
            msg = f"Transaction en attente - {tx.service.name} - {tx.amount} FCFA ({tx.phone_number})"
        real_time_activities.append({'message': msg, 'time': tx.created_at.strftime('%H:%M:%S')})
    if len(real_time_activities) < 3:
        real_time_activities.append({'message': 'Paiement reçu - Orange Money - 1 000 FCFA', 'time': timezone.now().strftime('%H:%M:%S')})
        if Gateway.objects.exists():
            gw = Gateway.objects.first()
            real_time_activities.append({'message': f'Gateway {gw.name} est maintenant Online', 'time': timezone.now().strftime('%H:%M:%S')})

    context = {
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
        'real_time_activities': real_time_activities,
    }
    return render(request, 'dashboard/index.html', context)

# Pages vides pour le menu
def transactions_list(request):
    return render(request, 'dashboard/transactions.html', {'title': 'Transactions'})

def refunds_list(request):
    return render(request, 'dashboard/refunds.html', {'title': 'Remboursements'})

def gateways_list(request):
    return render(request, 'dashboard/gateways.html', {'title': 'Gateways'})

def clients_list(request):
    return render(request, 'dashboard/clients.html', {'title': 'Clients'})

def reports_list(request):
    return render(request, 'dashboard/reports.html', {'title': 'Rapports'})

def notifications_list(request):
    return render(request, 'dashboard/notifications.html', {'title': 'Notifications'})

def settings_view(request):
    return render(request, 'dashboard/settings.html', {'title': 'Paramètres'})

def audit_logs(request):
    return render(request, 'dashboard/audit.html', {'title': "Journal d'audit"})
