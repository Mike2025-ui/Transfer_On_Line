"""Phase D4.1 - gateway_task_payload(): is_interactive / attempt_id.

Covers: simple UssdCode (no steps) -> is_interactive=False; UssdCode with
steps -> is_interactive=True + real attempt_id (never Transaction.id, never
reference); legacy engine -> is_interactive=False, no attempt_id; every
pre-existing payload key unchanged.
"""
import uuid

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import (
    Device, Gateway, Operator, Payment, Service, Transaction, TransactionAttempt, UssdCode, UssdStep,
)
from apps.core.serializers import gateway_task_payload
from apps.devices.models import GatewaySim

_TE_SETTINGS = {'TIMEOUT_SECONDS': 90, 'MAX_RETRY': 3}


def _make_transaction(operator, service, ussd_code, gateway):
    device = Device.objects.create(uid=f'dev-{uuid.uuid4()}', primary_phone='0700000001')
    payment = Payment.objects.create(method='cinetpay', reference=f'PAY-{uuid.uuid4()}', amount=500, status='accepted')
    return Transaction.objects.create(
        device=device, service=service, operator=operator, gateway=gateway,
        phone_number='0700000000', amount=500, status='pending',
        payment=payment, payment_method='cinetpay', ussd_code_used=ussd_code,
    )


@override_settings(TRANSACTION_ENGINE=_TE_SETTINGS, USE_NEW_TRANSACTION_ENGINE=True)
class InteractivePayloadNewEngineTests(TestCase):
    def setUp(self):
        self.operator = Operator.objects.create(name='MTN', code='mtn')
        self.service = Service.objects.create(name='Transfert', code='transfert')
        self.gateway = Gateway.objects.create(
            name='MTN - gw1', host='gw-1', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        self.sim = GatewaySim.objects.create(gateway=self.gateway, operator=self.operator, slot=0, is_active=True)

    def test_simple_ussd_code_is_not_interactive(self):
        code = UssdCode.objects.create(operator=self.operator, service=self.service, label='Simple', template='*456*{montant}#')
        tx = _make_transaction(self.operator, self.service, code, self.gateway)
        attempt = TransactionAttempt.objects.create(transaction=tx, gateway_sim=self.sim, attempt_number=1, status='dispatched')

        payload = gateway_task_payload(tx)

        self.assertFalse(payload['is_interactive'])
        self.assertEqual(payload['attempt_id'], attempt.id)

    def test_ussd_code_with_steps_is_interactive(self):
        code = UssdCode.objects.create(operator=self.operator, service=self.service, label='Interactif', template='*133#')
        UssdStep.objects.create(ussd_code=code, order=1, step_type='INPUT')
        tx = _make_transaction(self.operator, self.service, code, self.gateway)
        attempt = TransactionAttempt.objects.create(transaction=tx, gateway_sim=self.sim, attempt_number=1, status='dispatched')

        payload = gateway_task_payload(tx)

        self.assertTrue(payload['is_interactive'])
        self.assertEqual(payload['attempt_id'], attempt.id)
        # Never Transaction.id, never reference.
        self.assertNotEqual(payload['attempt_id'], tx.id)

    def test_no_attempt_reserved_yet_is_not_interactive_regardless_of_steps(self):
        code = UssdCode.objects.create(operator=self.operator, service=self.service, label='Interactif', template='*133#')
        UssdStep.objects.create(ussd_code=code, order=1, step_type='INPUT')
        tx = _make_transaction(self.operator, self.service, code, self.gateway)
        # No TransactionAttempt created at all.

        payload = gateway_task_payload(tx)

        self.assertFalse(payload['is_interactive'])
        self.assertNotIn('attempt_id', payload)

    def test_all_pre_existing_payload_keys_unchanged(self):
        code = UssdCode.objects.create(operator=self.operator, service=self.service, label='Simple', template='*456*{montant}#')
        tx = _make_transaction(self.operator, self.service, code, self.gateway)
        TransactionAttempt.objects.create(transaction=tx, gateway_sim=self.sim, attempt_number=1, status='dispatched')

        payload = gateway_task_payload(tx)

        for key in (
            'id', 'reference', 'transaction_type', 'operator', 'service', 'operation',
            'recipient_phone', 'amount', 'commission', 'status', 'ussd_code', 'created_at', 'updated_at',
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload['id'], tx.id)
        self.assertEqual(payload['reference'], tx.reference)
        self.assertNotIn('payment_method', payload)  # still excluded, unchanged


@override_settings(TRANSACTION_ENGINE=_TE_SETTINGS, USE_NEW_TRANSACTION_ENGINE=False)
class InteractivePayloadLegacyEngineTests(TestCase):
    def test_legacy_engine_never_reports_interactive_or_attempt_id(self):
        operator = Operator.objects.create(name='MTN', code='mtn')
        service = Service.objects.create(name='Transfert', code='transfert')
        gateway = Gateway.objects.create(name='MTN - gw1', host='gw-1', status='online', is_active=True)
        code = UssdCode.objects.create(operator=operator, service=service, label='Interactif', template='*133#')
        UssdStep.objects.create(ussd_code=code, order=1, step_type='INPUT')
        tx = _make_transaction(operator, service, code, gateway)

        payload = gateway_task_payload(tx)

        self.assertFalse(payload['is_interactive'])
        self.assertNotIn('attempt_id', payload)
        self.assertNotIn('sim_slot', payload)
