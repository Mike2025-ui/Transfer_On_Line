from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Device, Gateway, Operator, Payment, Service, Transaction


def _money(value, default='0'):
    try:
        return Decimal(str(value or default))
    except Exception:
        return Decimal(default)


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


def _transaction_payload(tx, ussd_code=None):
    return {
        'id': tx.id,
        'reference': tx.reference,
        'transaction_type': tx.service.code or tx.service.name,
        'operator': tx.operator.name,
        'service': tx.service.name,
        'operation': tx.service.code or tx.service.name,
        'recipient_phone': tx.phone_number,
        'amount': float(tx.amount),
        'commission': float(tx.commission),
        'status': tx.status,
        'payment_method': tx.payment_method,
        'payment_reference': tx.payment_reference,
        'ussd_code': ussd_code or _build_ussd_code(tx),
        'created_at': tx.created_at.isoformat() if tx.created_at else None,
        'updated_at': tx.updated_at.isoformat() if tx.updated_at else None,
    }


def _build_ussd_code(tx):
    amount = int(tx.amount)
    phone = tx.phone_number
    service_code = (tx.service.code or tx.service.name).lower()
    if 'transfer' in service_code or 'transfert' in service_code:
        return f'*123*{phone}*{amount}#'
    return f'*456*{amount}#'


class GatewayListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        gateways = Gateway.objects.filter(is_active=True).order_by('id')
        return Response([_gateway_payload(gateway) for gateway in gateways])


class GatewayHeartbeatView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, gateway_id=None):
        details = request.data.get('details') or {}
        gateway_uuid = details.get('uuid') or request.data.get('gateway_uuid')
        phone_number = details.get('phone_number') or request.data.get('phone_number') or 'Gateway Android'
        operator_name = details.get('operator') or request.data.get('operator') or 'Gateway'

        gateway = None
        if gateway_id is not None:
            gateway = Gateway.objects.filter(id=gateway_id).first()
        if gateway is None and gateway_uuid:
            gateway = Gateway.objects.filter(host=gateway_uuid).first()
        if gateway is None:
            gateway = Gateway.objects.create(
                name=f'{operator_name} - {phone_number}',
                host=gateway_uuid or '',
                status='online',
            )

        gateway.name = f'{operator_name} - {phone_number}'
        if gateway_uuid:
            gateway.host = gateway_uuid
        gateway.status = request.data.get('status') or 'online'
        gateway.last_heartbeat = timezone.now()
        gateway.save()
        return Response(_gateway_payload(gateway))


class ExecuteTransactionView(APIView):
    permission_classes = [AllowAny]

    @db_transaction.atomic
    def post(self, request):
        operator_name = request.data.get('operator') or request.data.get('operator_name') or 'Orange'
        service_name = request.data.get('service') or request.data.get('service_name') or 'Internet'
        operation = request.data.get('operation') or request.data.get('transaction_type') or 'subscription'
        phone = request.data.get('phone') or request.data.get('recipient_phone')
        amount = _money(request.data.get('amount'))
        payment_method = request.data.get('payment_method') or request.data.get('paymentMethod')
        payment_reference = request.data.get('payment_reference') or request.data.get('reference')

        if not phone or amount <= 0:
            return Response({'error': 'phone/recipient_phone and amount are required'}, status=400)

        device, _ = Device.objects.get_or_create(
            uid=request.data.get('device_uid') or 'client-app',
            defaults={'primary_phone': phone},
        )
        operator, _ = Operator.objects.get_or_create(
            name=operator_name,
            defaults={'code': operator_name.lower().replace(' ', '_')},
        )
        service, _ = Service.objects.get_or_create(
            name=service_name,
            defaults={'code': operation},
        )
        gateway = Gateway.objects.filter(is_active=True, status='online').order_by('-last_heartbeat').first()
        if gateway is None:
            gateway = Gateway.objects.filter(is_active=True).order_by('id').first()

        payment = None
        if payment_method:
            payment = Payment.objects.create(
                method=_payment_code(payment_method),
                reference=payment_reference or f'PAY-{timezone.now().timestamp()}',
                amount=amount,
                status='success',
            )

        tx = Transaction.objects.create(
            device=device,
            service=service,
            operator=operator,
            gateway=gateway,
            phone_number=phone,
            amount=amount,
            status='pending' if gateway else 'failed',
            payment=payment,
            payment_method=_payment_code(payment_method) if payment_method else None,
            payment_reference=payment_reference,
        )
        return Response(_transaction_payload(tx), status=201)


class PendingTransactionsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        gateway_uuid = request.query_params.get('gateway_uuid')
        queryset = Transaction.objects.select_related('service', 'operator', 'gateway').filter(status='pending')
        if gateway_uuid:
            queryset = queryset.filter(gateway__host=gateway_uuid)
        return Response([_transaction_payload(tx) for tx in queryset.order_by('created_at')[:10]])


class TransactionResultView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        reference = request.data.get('transaction_reference') or request.data.get('reference')
        success = request.data.get('success') in [True, 'true', 'True', '1', 1]
        result = request.data.get('result') or request.data.get('ussd_response') or ''
        if not reference:
            return Response({'error': 'transaction_reference required'}, status=400)
        tx = Transaction.objects.filter(reference=reference).first()
        if tx is None:
            return Response({'error': 'Transaction not found'}, status=404)
        tx.status = 'success' if success else 'failed'
        if result:
            tx.payment_reference = result[:100]
        tx.save()
        return Response(_transaction_payload(tx))


def _payment_code(label):
    normalized = (label or '').lower().replace(' ', '_').replace('-', '_')
    if 'mtn' in normalized:
        return 'mtn_momo'
    if 'wave' in normalized:
        return 'wave'
    return 'orange_money'
