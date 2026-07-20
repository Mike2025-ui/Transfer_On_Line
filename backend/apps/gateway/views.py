from decimal import Decimal
from uuid import uuid4

from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Device, Gateway, Operator, Payment, Service, Transaction
from .cinetpay import CinetPayClient, CinetPayError, cinetpay_status_to_local


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
        'payment_status': tx.payment.status if tx.payment else None,
        'checkout_url': tx.payment.checkout_url if tx.payment else None,
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


def _select_gateway():
    gateway = Gateway.objects.filter(is_active=True, status='online').order_by('-last_heartbeat').first()
    if gateway is None:
        gateway = Gateway.objects.filter(is_active=True).order_by('id').first()
    return gateway


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
        customer = request.data.get('customer') or {}

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
        gateway = _select_gateway()
        payment_reference = f'TOL-{timezone.now().strftime("%Y%m%d%H%M%S")}-{uuid4().hex[:8].upper()}'
        payment = Payment.objects.create(
            method='cinetpay',
            reference=payment_reference,
            amount=amount,
            status='pending',
        )
        tx = Transaction.objects.create(
            device=device,
            service=service,
            operator=operator,
            gateway=gateway,
            phone_number=phone,
            amount=amount,
            status='pending',
            payment=payment,
            payment_method='cinetpay',
            payment_reference=payment.reference,
        )

        try:
            init_data = CinetPayClient().initialize_payment(
                transaction_id=payment.reference,
                amount=amount,
                description=f'{service.name} - {operation}',
                customer={
                    'name': customer.get('name') or request.data.get('customer_name') or 'Client',
                    'surname': customer.get('surname') or request.data.get('customer_surname') or 'Transfer On Line',
                    'phone': customer.get('phone') or phone,
                    'email': customer.get('email') or request.data.get('customer_email') or 'client@example.com',
                },
            )
        except CinetPayError as exc:
            payment.status = 'failed'
            payment.provider_payload = {'error': str(exc)}
            payment.save(update_fields=['status', 'provider_payload', 'updated_at'])
            tx.status = 'failed'
            tx.save(update_fields=['status', 'updated_at'])
            return Response({'error': str(exc), **_transaction_payload(tx)}, status=502)

        data = init_data.get('data') or {}
        payment.provider_transaction_id = str(data.get('payment_token') or '')
        payment.checkout_url = data.get('payment_url') or data.get('url')
        payment.provider_payload = init_data
        payment.save(update_fields=['provider_transaction_id', 'checkout_url', 'provider_payload', 'updated_at'])
        return Response(_transaction_payload(tx), status=201)


class PendingTransactionsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        gateway_uuid = request.query_params.get('gateway_uuid')
        queryset = Transaction.objects.select_related('service', 'operator', 'gateway', 'payment').filter(
            status='pending',
            payment__status='accepted',
        )
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


class CinetPayNotifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        transaction_id = (
            request.data.get('cpm_trans_id')
            or request.data.get('transaction_id')
            or request.data.get('payment_reference')
        )
        if not transaction_id:
            return Response({'error': 'transaction_id required'}, status=400)

        payment = Payment.objects.filter(reference=transaction_id).first()
        if payment is None:
            return Response({'error': 'Payment not found'}, status=404)

        try:
            check_data = CinetPayClient().check_payment(payment.reference)
        except CinetPayError as exc:
            return Response({'error': str(exc)}, status=502)

        checked = check_data.get('data') or check_data
        payment.status = cinetpay_status_to_local(checked.get('status') or checked.get('payment_status'))
        payment.provider_payload = {'notification': request.data, 'check': check_data}
        payment.save(update_fields=['status', 'provider_payload', 'updated_at'])

        tx = payment.transactions.select_related('service', 'operator', 'gateway').first()
        if tx:
            tx.status = 'pending' if payment.status == 'accepted' and tx.gateway else 'failed'
            tx.save(update_fields=['status', 'updated_at'])

        return Response({
            'payment_reference': payment.reference,
            'payment_status': payment.status,
            'transaction': _transaction_payload(tx) if tx else None,
        })
