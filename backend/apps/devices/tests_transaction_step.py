"""Phase C (moteur USSD interactif) - POST /api/gateway/transactions/step/.

Covers: NEW_FIELD (FIXED/DYNAMIC/multi-field/field_count mismatch),
FINAL_FIELD, RESULT (success/failed, full operator_message, reuse of
ReservationManager/RetryManager/TransactionStateMachine), per-event
Idempotency-Key replay, real concurrency (threads, real DB connections -
same pattern as tests_double_dispatch_concurrency.py), and the security
checks (wrong attempt_id, wrong gateway, terminal attempt, missing key).
"""
import threading
import uuid

from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import (
    Device, Gateway, Operator, Payment, Service, Transaction, TransactionAttempt, UssdCode, UssdStep, UssdStepField,
)
from apps.devices.models import GatewaySim


def _build_mtn_transfer_scenario(operator, service):
    """UssdCode + 5 steps matching the scenario used throughout Phase A/B/C:
    6 -> 2 -> {numero} -> {montant} -> FINAL_FIELD."""
    ussd_code = UssdCode.objects.create(
        operator=operator, service=service, label='Transfert MTN', template='*133#',
    )
    step1 = UssdStep.objects.create(ussd_code=ussd_code, order=1, step_type='INPUT')
    UssdStepField.objects.create(step=step1, order=1, field_type='FIXED', value='6')
    step2 = UssdStep.objects.create(ussd_code=ussd_code, order=2, step_type='INPUT')
    UssdStepField.objects.create(step=step2, order=1, field_type='FIXED', value='2')
    step3 = UssdStep.objects.create(ussd_code=ussd_code, order=3, step_type='INPUT')
    UssdStepField.objects.create(step=step3, order=1, field_type='DYNAMIC', value='numero')
    step4 = UssdStep.objects.create(ussd_code=ussd_code, order=4, step_type='INPUT')
    UssdStepField.objects.create(step=step4, order=1, field_type='DYNAMIC', value='montant')
    UssdStep.objects.create(ussd_code=ussd_code, order=5, step_type='FINAL_FIELD')
    return ussd_code


class _StepTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = Operator.objects.create(name='MTN', code='mtn')
        self.service = Service.objects.create(name='Transfert', code='transfert')
        self.ussd_code = _build_mtn_transfer_scenario(self.operator, self.service)

        self.gateway = Gateway.objects.create(
            name='MTN - gw1', host='gw-1', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        self.sim = GatewaySim.objects.create(gateway=self.gateway, operator=self.operator, slot=0, is_active=True)
        self.secret = self.gateway.generate_secret()

        self.tx, self.attempt = self._make_transaction_with_dispatched_attempt()
        self.url = reverse('api_transaction_step')

    def _make_transaction_with_dispatched_attempt(self, attempt_status='dispatched'):
        device = Device.objects.create(uid=f'dev-{uuid.uuid4()}', primary_phone='0700000001')
        payment = Payment.objects.create(
            method='cinetpay', reference=f'PAY-{uuid.uuid4()}', amount=500, status='accepted',
        )
        tx = Transaction.objects.create(
            device=device, service=self.service, operator=self.operator, gateway=self.gateway,
            phone_number='0700000000', amount=500, status='pending',
            payment=payment, payment_method='cinetpay', ussd_code_used=self.ussd_code,
        )
        attempt = TransactionAttempt.objects.create(
            transaction=tx, gateway_sim=self.sim, attempt_number=1, status=attempt_status,
        )
        return tx, attempt

    def _post(self, body, idempotency_key='KEY-A', secret=None):
        self.client.credentials(HTTP_X_GATEWAY_SECRET=secret or self.secret, HTTP_IDEMPOTENCY_KEY=idempotency_key)
        return self.client.post(self.url, {
            'transaction_reference': self.tx.reference,
            'attempt_id': self.attempt.pk,
            **body,
        }, format='json')


class NewFieldTests(_StepTestBase):
    def test_first_new_field_resolves_fixed_step_and_advances(self):
        response = self._post({'event': 'NEW_FIELD', 'field_count': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'action': 'INPUT', 'values': ['6']})
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.current_step.order, 2)
        self.assertEqual(self.attempt.status, 'executing')

    def test_dynamic_step_resolves_from_transaction(self):
        # Advance past step 1 and 2 first.
        self._post({'event': 'NEW_FIELD', 'field_count': 1}, idempotency_key='KEY-1')
        self._post({'event': 'NEW_FIELD', 'field_count': 1}, idempotency_key='KEY-2')
        response = self._post({'event': 'NEW_FIELD', 'field_count': 1}, idempotency_key='KEY-3')
        self.assertEqual(response.data, {'action': 'INPUT', 'values': ['0700000000']})
        response = self._post({'event': 'NEW_FIELD', 'field_count': 1}, idempotency_key='KEY-4')
        self.assertEqual(response.data, {'action': 'INPUT', 'values': ['500']})

    def test_multiple_fields_resolved_in_order(self):
        step = UssdStep.objects.create(ussd_code=self.ussd_code, order=6, step_type='INPUT')
        UssdStepField.objects.create(step=step, order=1, field_type='DYNAMIC', value='numero')
        UssdStepField.objects.create(step=step, order=2, field_type='DYNAMIC', value='montant')
        UssdStepField.objects.create(step=step, order=3, field_type='FIXED', value='1')
        self.attempt.current_step = step
        self.attempt.save(update_fields=['current_step'])

        response = self._post({'event': 'NEW_FIELD', 'field_count': 3})
        self.assertEqual(response.data, {'action': 'INPUT', 'values': ['0700000000', '500', '1']})

    def test_field_count_mismatch_returns_ambiguous_input_without_advancing(self):
        response = self._post({'event': 'NEW_FIELD', 'field_count': 2})
        self.assertEqual(response.data, {'action': 'FAILED', 'error_code': 'AMBIGUOUS_INPUT'})
        self.attempt.refresh_from_db()
        self.assertIsNone(self.attempt.current_step)

    def test_non_integer_field_count_rejected(self):
        response = self._post({'event': 'NEW_FIELD', 'field_count': 'abc'})
        self.assertEqual(response.data, {'action': 'FAILED', 'error_code': 'AMBIGUOUS_INPUT'})


class IdempotencyTests(_StepTestBase):
    def test_replayed_key_returns_identical_response_without_advancing(self):
        first = self._post({'event': 'NEW_FIELD', 'field_count': 1}, idempotency_key='KEY-A')
        self.attempt.refresh_from_db()
        step_after_first = self.attempt.current_step_id

        replay = self._post({'event': 'NEW_FIELD', 'field_count': 1}, idempotency_key='KEY-A')
        self.assertEqual(replay.data, first.data)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.current_step_id, step_after_first)

    def test_new_key_advances_to_next_step(self):
        self._post({'event': 'NEW_FIELD', 'field_count': 1}, idempotency_key='KEY-A')
        response = self._post({'event': 'NEW_FIELD', 'field_count': 1}, idempotency_key='KEY-B')
        self.assertEqual(response.data, {'action': 'INPUT', 'values': ['2']})


class ConcurrencyTests(TransactionTestCase):
    """Real threads, real separate DB connections - same proof pattern as
    tests_double_dispatch_concurrency.py (Phase 7.3)."""

    def setUp(self):
        self.operator = Operator.objects.create(name='MTN', code='mtn')
        self.service = Service.objects.create(name='Transfert', code='transfert')
        self.ussd_code = _build_mtn_transfer_scenario(self.operator, self.service)
        self.gateway = Gateway.objects.create(
            name='MTN - gw1', host='gw-1', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        self.sim = GatewaySim.objects.create(gateway=self.gateway, operator=self.operator, slot=0, is_active=True)
        self.secret = self.gateway.generate_secret()
        device = Device.objects.create(uid=f'dev-{uuid.uuid4()}', primary_phone='0700000001')
        payment = Payment.objects.create(
            method='cinetpay', reference=f'PAY-{uuid.uuid4()}', amount=500, status='accepted',
        )
        self.tx = Transaction.objects.create(
            device=device, service=self.service, operator=self.operator, gateway=self.gateway,
            phone_number='0700000000', amount=500, status='pending',
            payment=payment, payment_method='cinetpay', ussd_code_used=self.ussd_code,
        )
        self.attempt = TransactionAttempt.objects.create(
            transaction=self.tx, gateway_sim=self.sim, attempt_number=1, status='dispatched',
        )
        self.url = reverse('api_transaction_step')

    def _post_in_thread(self, idempotency_key, results, index, barrier):
        try:
            client = APIClient()
            client.credentials(HTTP_X_GATEWAY_SECRET=self.secret, HTTP_IDEMPOTENCY_KEY=idempotency_key)
            barrier.wait(timeout=5)
            response = client.post(self.url, {
                'transaction_reference': self.tx.reference,
                'attempt_id': self.attempt.pk,
                'event': 'NEW_FIELD',
                'field_count': 1,
            }, format='json')
            results[index] = response.data
        finally:
            connections.close_all()

    def test_two_identical_keys_simultaneously_advance_only_once(self):
        results = [None, None]
        barrier = threading.Barrier(2)
        threads = [
            threading.Thread(target=self._post_in_thread, args=('KEY-A', results, i, barrier))
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(results[0], {'action': 'INPUT', 'values': ['6']})
        self.assertEqual(results[1], {'action': 'INPUT', 'values': ['6']})
        self.attempt.refresh_from_db()
        # Advanced exactly ONE step (order=2), never two (order=3).
        self.assertEqual(self.attempt.current_step.order, 2)

    def test_hundred_races_never_double_advance(self):
        for _ in range(100):
            self.attempt.current_step = None
            self.attempt.last_step_idempotency_key = ''
            self.attempt.last_step_response = {}
            self.attempt.status = 'dispatched'
            self.attempt.save()

            results = [None, None]
            barrier = threading.Barrier(2)
            threads = [
                threading.Thread(target=self._post_in_thread, args=('KEY-RACE', results, i, barrier))
                for i in range(2)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
            self.attempt.refresh_from_db()
            self.assertEqual(self.attempt.current_step.order, 2, 'double advance detected')
        print('\n[Phase C] step idempotency race: 100 races - double_advance=0')


class FinalFieldTests(_StepTestBase):
    def setUp(self):
        super().setUp()
        final_step = self.ussd_code.steps.get(order=5)
        self.attempt.current_step = final_step
        self.attempt.save(update_fields=['current_step'])

    def test_final_field_on_correct_step_returns_done_without_advancing(self):
        response = self._post({'event': 'FINAL_FIELD'})
        self.assertEqual(response.data, {'action': 'DONE'})
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.current_step.order, 5)
        self.assertEqual(self.attempt.status, 'executing')

    def test_final_field_replayed_with_same_key_returns_identical_response(self):
        first = self._post({'event': 'FINAL_FIELD'}, idempotency_key='KEY-F')
        replay = self._post({'event': 'FINAL_FIELD'}, idempotency_key='KEY-F')
        self.assertEqual(first.data, replay.data)

    def test_final_field_on_non_final_step_rejected(self):
        self.attempt.current_step = self.ussd_code.steps.get(order=1)
        self.attempt.save(update_fields=['current_step'])
        response = self._post({'event': 'FINAL_FIELD'})
        self.assertEqual(response.data, {'action': 'FAILED', 'error_code': 'UNKNOWN_SCREEN'})


class ResultTests(_StepTestBase):
    def test_success_stores_full_operator_message_and_transitions_transaction(self):
        message = 'Transfert effectué avec succès. Montant : 500 FCFA. ID : 847291.'
        response = self._post({'event': 'RESULT', 'status': 'SUCCESS', 'operator_message': message})
        self.assertEqual(response.data, {'action': 'DONE', 'status': 'SUCCESS'})
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.raw_response, message)
        self.assertEqual(self.attempt.status, 'success')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'success')

    def test_failed_non_retryable_stores_full_message_and_fails_transaction(self):
        message = "Votre transfert n'a pas pu être effectué."
        response = self._post({
            'event': 'RESULT', 'status': 'FAILED', 'operator_message': message, 'error_code': 'invalid_number',
        })
        self.assertEqual(response.data, {'action': 'DONE', 'status': 'FAILED'})
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.raw_response, message)
        self.assertEqual(self.attempt.failure_reason, 'invalid_number')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'failed')

    def test_failed_retryable_schedules_retry_via_existing_retry_manager(self):
        response = self._post({
            'event': 'RESULT', 'status': 'FAILED', 'operator_message': 'Erreur réseau', 'error_code': 'network_error',
        })
        self.assertEqual(response.data, {'action': 'DONE', 'status': 'RETRY_SCHEDULED'})
        self.tx.refresh_from_db()
        self.assertIsNotNone(self.tx.next_retry_at)
        self.assertEqual(self.tx.status, 'pending')  # not permanently failed - a retry is queued

    def test_gateway_sim_counters_updated_via_reservation_manager_reuse(self):
        self.sim.refresh_from_db()
        before = self.sim.success_count
        self._post({'event': 'RESULT', 'status': 'SUCCESS', 'operator_message': 'OK'})
        self.sim.refresh_from_db()
        self.assertEqual(self.sim.success_count, before + 1)


class SecurityAndValidationTests(_StepTestBase):
    def test_missing_idempotency_key_rejected(self):
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret)
        response = self.client.post(self.url, {
            'transaction_reference': self.tx.reference, 'attempt_id': self.attempt.pk, 'event': 'NEW_FIELD',
            'field_count': 1,
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_empty_idempotency_key_rejected(self):
        response = self._post({'event': 'NEW_FIELD', 'field_count': 1}, idempotency_key='')
        self.assertEqual(response.status_code, 400)

    def test_wrong_attempt_id_rejected(self):
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret, HTTP_IDEMPOTENCY_KEY='KEY-A')
        response = self.client.post(self.url, {
            'transaction_reference': self.tx.reference, 'attempt_id': 999999, 'event': 'NEW_FIELD', 'field_count': 1,
        }, format='json')
        self.assertEqual(response.status_code, 404)

    def test_attempt_id_for_different_transaction_reference_rejected(self):
        other_tx, other_attempt = self._make_transaction_with_dispatched_attempt()
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret, HTTP_IDEMPOTENCY_KEY='KEY-A')
        response = self.client.post(self.url, {
            'transaction_reference': self.tx.reference,  # mismatched on purpose
            'attempt_id': other_attempt.pk,
            'event': 'NEW_FIELD', 'field_count': 1,
        }, format='json')
        self.assertEqual(response.status_code, 404)

    def test_different_gateway_cannot_act_on_this_attempt(self):
        other_gateway = Gateway.objects.create(name='MTN - gw2', host='gw-2', is_active=True, status='online')
        other_secret = other_gateway.generate_secret()
        response = self._post({'event': 'NEW_FIELD', 'field_count': 1}, secret=other_secret)
        self.assertEqual(response.status_code, 403)

    def test_terminal_attempt_rejected(self):
        self.attempt.status = 'success'
        self.attempt.save(update_fields=['status'])
        response = self._post({'event': 'NEW_FIELD', 'field_count': 1})
        self.assertEqual(response.status_code, 409)

    def test_unknown_event_rejected(self):
        response = self._post({'event': 'SOMETHING_ELSE'})
        self.assertEqual(response.status_code, 400)

    def test_no_gateway_secret_rejected(self):
        self.client.credentials(HTTP_IDEMPOTENCY_KEY='KEY-A')
        response = self.client.post(self.url, {
            'transaction_reference': self.tx.reference, 'attempt_id': self.attempt.pk,
            'event': 'NEW_FIELD', 'field_count': 1,
        }, format='json')
        self.assertEqual(response.status_code, 401)
