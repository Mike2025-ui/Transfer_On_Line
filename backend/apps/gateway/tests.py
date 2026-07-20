from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import Gateway, Payment, Transaction


@override_settings(
    CINETPAY_API_KEY='api-key',
    CINETPAY_SITE_ID='site-id',
    CINETPAY_NOTIFY_URL='https://api.example.com/api/payments/cinetpay/notify/',
    CINETPAY_RETURN_URL='https://app.example.com/payment/success',
)
class CinetPayFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.gateway = Gateway.objects.create(
            name='Orange - 0700000000',
            host='gateway-1',
            status='online',
        )

    @patch('apps.gateway.views.CinetPayClient.initialize_payment')
    def test_execute_transaction_initializes_cinetpay_checkout(self, initialize_payment):
        initialize_payment.return_value = {
            'code': '201',
            'data': {
                'payment_token': 'token-123',
                'payment_url': 'https://checkout.cinetpay.com/pay/token-123',
            },
        }

        response = self.client.post(
            reverse('api_transaction_execute'),
            {
                'operator': 'Orange',
                'service': 'Internet',
                'operation': 'subscription',
                'phone': '0700000001',
                'amount': 1000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['payment_method'], 'cinetpay')
        self.assertEqual(response.data['payment_status'], 'pending')
        self.assertEqual(response.data['checkout_url'], 'https://checkout.cinetpay.com/pay/token-123')
        self.assertTrue(Payment.objects.filter(method='cinetpay', amount=Decimal('1000')).exists())

    @patch('apps.gateway.views.CinetPayClient.check_payment')
    def test_pending_transactions_are_exposed_only_after_accepted_payment(self, check_payment):
        payment = Payment.objects.create(method='cinetpay', reference='PAY-1', amount=1000)
        tx = Transaction.objects.create(
            device_id=self._device_id(),
            service_id=self._service_id(),
            operator_id=self._operator_id(),
            gateway=self.gateway,
            phone_number='0700000001',
            amount=1000,
            payment=payment,
            payment_method='cinetpay',
            payment_reference='PAY-1',
        )
        self.assertEqual(self.client.get(reverse('api_transaction_pending')).data, [])

        check_payment.return_value = {'data': {'status': 'ACCEPTED'}}
        notify = self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': 'PAY-1'}, format='json')
        self.assertEqual(notify.status_code, 200)

        pending = self.client.get(reverse('api_transaction_pending'))
        self.assertEqual(len(pending.data), 1)
        self.assertEqual(pending.data[0]['reference'], str(tx.reference))

    def _device_id(self):
        from apps.core.models import Device

        return Device.objects.create(uid='client-app', primary_phone='0700000001').id

    def _service_id(self):
        from apps.core.models import Service

        return Service.objects.create(name='Internet', code='subscription').id

    def _operator_id(self):
        from apps.core.models import Operator

        return Operator.objects.create(name='Orange', code='orange').id
