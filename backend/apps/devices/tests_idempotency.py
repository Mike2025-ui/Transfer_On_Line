"""Business-model audit, Phase 5 - idempotency guard for POST
/transactions/execute/ (ExecuteTransactionView).

Root cause (see the approved plan): Transaction.reference (uuid4) and
Payment.reference (server-timestamp + random hex) are both generated fresh
on every call, so two byte-identical requests always produced two
independent Transaction/Payment rows and, with the new engine on, two
separate Gateway/SIM reservations. Fixed via a client-supplied
Idempotency-Key (header or `idempotency_key` JSON field) stored on
Transaction.idempotency_key (nullable+unique) - see apps/core/models.py and
ExecuteTransactionView.post() in apps/devices/views.py.

Business content alone (operator/service/amount/phone) is deliberately
NEVER treated as a dedup signal - two legitimate, separate transfers can
share every field (same recipient, same amount, sent again a few seconds
later) in a money-transfer app. Only an explicit key identifies "this is a
repeat of that exact attempt", never inferred from content. A request sent
with no key at all stays exactly as undeduplicated as before this phase -
see tests_new_engine_e2e.py's Scenario7DuplicateRequestTests, which keeps
proving that boundary unmodified.

Replaying the same key after the transaction reached a terminal state
(success or failed) returns the stored transaction as-is, never triggering
a new Payment/Gateway reservation/attempt - the key identifies the request,
not a standing permission to keep retrying the business operation. A real
new attempt requires a new key (i.e. a genuine new user action)."""

import threading
from contextlib import nullcontext
from unittest.mock import patch

from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Gateway, Operator, Payment, Service, Transaction, TransactionAttempt, UssdCode
from apps.devices.models import GatewaySim


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class IdempotencyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500,
            label='Orange Internet 500F', template='*456*4*1#', is_active=True,
        )
        gw = Gateway.objects.create(name='Orange - gw1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        self.sim = GatewaySim.objects.create(gateway=gw, operator=self.orange, slot=0, is_active=True)
        # Business-model audit Phase 7: /transactions/result/ now requires
        # Gateway authentication - harmless for tests that never call it.
        self.client.credentials(HTTP_X_GATEWAY_SECRET=gw.generate_secret())

    def _payload(self, **overrides):
        payload = {
            'operator_id': self.orange.id, 'service_id': self.internet.id,
            'amount': 500, 'recipient_phone': '0700000001',
        }
        payload.update(overrides)
        return payload

    def _mock_create_payment(self, create_payment):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

    def _device_id(self):
        from apps.core.models import Device
        return Device.objects.create(uid='client-app-test', primary_phone='0700000001').id

    # Test 1 + Test 2 - reconciled: under this design, "two identical POSTs"
    # only means something once a key exists to say so.
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_same_idempotency_key_twice_creates_only_one_transaction(self, create_payment, _redis_lock):
        self._mock_create_payment(create_payment)
        key = 'client-attempt-1'

        first = self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')
        second = self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        # str(): Transaction.reference is a CharField with default=uuid.uuid4
        # - a freshly-created instance holds the raw UUID object in memory
        # (never round-tripped through the DB yet), while the early-return
        # branch always re-fetches from the DB, where it comes back as a
        # plain str. Same value, different Python type - not a bug.
        self.assertEqual(str(first.data['reference']), str(second.data['reference']))
        self.assertEqual(Transaction.objects.filter(idempotency_key=key).count(), 1)

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_same_key_sent_as_a_header_is_also_deduplicated(self, create_payment, _redis_lock):
        self._mock_create_payment(create_payment)
        key = 'client-attempt-header-1'

        first = self.client.post(
            reverse('api_transaction_execute'), self._payload(), format='json', HTTP_IDEMPOTENCY_KEY=key,
        )
        second = self.client.post(
            reverse('api_transaction_execute'), self._payload(), format='json', HTTP_IDEMPOTENCY_KEY=key,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Transaction.objects.filter(idempotency_key=key).count(), 1)

    # Test 3
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_different_idempotency_keys_create_two_independent_transactions(self, create_payment, _redis_lock):
        self._mock_create_payment(create_payment)

        first = self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key='key-A'), format='json')
        second = self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key='key-B'), format='json')

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.data['reference'], second.data['reference'])
        self.assertEqual(Transaction.objects.count(), 2)

    # Test 4 (deterministic half) - exercises the exact production mechanism
    # (Transaction.objects.get_or_create under the idempotency_key UNIQUE
    # constraint) with both "requests" using genuinely different Payment
    # rows, proving the DB constraint - not application ordering - is what
    # decides the single winner. The real multi-threaded race is in
    # ConcurrentIdempotentRequestTests below.
    def test_sequential_get_or_create_calls_with_the_same_key_converge_to_one_row(self, _redis_lock):
        key = 'race-key-orm'
        payment_a = Payment.objects.create(method='cinetpay', reference='PAY-RACE-A', amount=500, status='pending')
        payment_b = Payment.objects.create(method='cinetpay', reference='PAY-RACE-B', amount=500, status='pending')
        fields = dict(
            device_id=self._device_id(), service=self.internet, operator=self.orange,
            phone_number='0700000001', amount=500, status='pending',
        )

        tx_a, created_a = Transaction.objects.get_or_create(idempotency_key=key, defaults={**fields, 'payment': payment_a})
        tx_b, created_b = Transaction.objects.get_or_create(idempotency_key=key, defaults={**fields, 'payment': payment_b})

        self.assertTrue(created_a)
        self.assertFalse(created_b)
        self.assertEqual(tx_a.pk, tx_b.pk)
        self.assertEqual(Transaction.objects.filter(idempotency_key=key).count(), 1)

    # Test 5
    @patch('apps.payments.services.payment_service.PaymentService.initiate')
    def test_payment_service_initiate_is_called_exactly_once_across_duplicate_requests(self, initiate, _redis_lock):
        initiate.return_value = None
        key = 'client-attempt-initiate'

        self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')
        self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')

        self.assertEqual(initiate.call_count, 1)

    # Test 6
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_only_one_gateway_sim_reservation_across_duplicate_requests(self, create_payment, _redis_lock):
        self._mock_create_payment(create_payment)
        key = 'client-attempt-reservation'

        self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')
        self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')

        self.assertEqual(TransactionAttempt.objects.filter(gateway_sim=self.sim).count(), 1)

    # Test 7
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_only_one_transaction_attempt_exists_after_duplicate_requests(self, create_payment, _redis_lock):
        self._mock_create_payment(create_payment)
        key = 'client-attempt-single-attempt'

        self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')
        self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')

        self.assertEqual(TransactionAttempt.objects.count(), 1)

    # Test 8
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_repeating_the_original_request_does_not_schedule_a_second_retry(self, create_payment, _redis_lock):
        self._mock_create_payment(create_payment)
        key = 'client-attempt-retry'
        first = self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')
        tx = Transaction.objects.get(reference=first.data['reference'])

        self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': False, 'result': 'network error'},
            format='json',
        )
        tx.refresh_from_db()
        retry_at_after_failure = tx.next_retry_at
        self.assertIsNotNone(retry_at_after_failure)
        attempts_after_failure = tx.attempts.count()

        repeat = self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')

        self.assertEqual(repeat.status_code, 200)
        tx.refresh_from_db()
        self.assertEqual(tx.next_retry_at, retry_at_after_failure)
        self.assertEqual(tx.attempts.count(), attempts_after_failure)

    # Test 9
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.verify_payment')
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_replaying_the_key_after_success_returns_the_existing_transaction(self, create_payment, verify_payment, _redis_lock):
        from apps.payments.providers.base import PaymentStatusResult
        self._mock_create_payment(create_payment)
        key = 'client-attempt-success-replay'
        first = self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')
        tx = Transaction.objects.get(reference=first.data['reference'])

        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': tx.payment.reference}, format='json')
        self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': True, 'result': 'OK'},
            format='json',
        )
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success')
        payment_count_before = Payment.objects.count()
        attempt_count_before = tx.attempts.count()

        repeat = self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')

        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.data['reference'], str(tx.reference))
        self.assertEqual(repeat.data['status'], 'success')
        self.assertEqual(Payment.objects.count(), payment_count_before)
        tx.refresh_from_db()
        self.assertEqual(tx.attempts.count(), attempt_count_before)

    # Test 10
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_replaying_the_key_after_a_non_retryable_failure_returns_the_existing_failed_transaction(self, create_payment, _redis_lock):
        self._mock_create_payment(create_payment)
        key = 'client-attempt-failure-replay'
        first = self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')
        tx = Transaction.objects.get(reference=first.data['reference'])

        self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': False, 'result': 'Numero invalide'},
            format='json',
        )
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'failed')
        payment_count_before = Payment.objects.count()

        repeat = self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key=key), format='json')

        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.data['reference'], str(tx.reference))
        self.assertEqual(repeat.data['status'], 'failed')
        self.assertEqual(Payment.objects.count(), payment_count_before)
        self.assertEqual(Transaction.objects.filter(idempotency_key=key).count(), 1)

    # Part 8 of the brief - the legacy selector must never be called under
    # the new engine, idempotency short-circuit included. Business-model
    # audit Phase 7.2: GatewayManager.select_operator_gateway() replaced the
    # old _select_gateway() - patching the method on GatewayManager itself
    # intercepts both its callers (ExecuteTransactionView, RetryManager).
    @patch('apps.devices.services.gateway_manager.GatewayManager.select_operator_gateway')
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_select_operator_gateway_is_never_called_when_the_new_engine_is_active(self, create_payment, select_operator_gateway, _redis_lock):
        self._mock_create_payment(create_payment)

        self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key='engine-check-1'), format='json')
        self.client.post(reverse('api_transaction_execute'), self._payload(idempotency_key='engine-check-1'), format='json')

        select_operator_gateway.assert_not_called()


class ConcurrentIdempotentRequestTests(TransactionTestCase):
    """Real multi-threaded race (Part 4 of the brief), not a simulation:
    two independent DB connections racing to create a Transaction under the
    same Idempotency-Key. Requires TransactionTestCase, not TestCase - a
    plain TestCase wraps the whole test body in one uncommitted transaction,
    which a second OS thread's own connection would never see (it wouldn't
    even see the Operator/Service/UssdCode fixtures from setUp)."""

    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500,
            label='Orange Internet 500F', template='*456*4*1#', is_active=True,
        )
        gw = Gateway.objects.create(name='Orange - gw1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        self.sim = GatewaySim.objects.create(gateway=gw, operator=self.orange, slot=0, is_active=True)

    @override_settings(USE_NEW_TRANSACTION_ENGINE=True)
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    @patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
    def test_two_concurrent_requests_with_the_same_key_produce_a_single_transaction(self, _redis_lock, create_payment):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

        key = 'race-key-http'
        payload = {
            'operator_id': self.orange.id, 'service_id': self.internet.id,
            'amount': 500, 'recipient_phone': '0700000001', 'idempotency_key': key,
        }
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=5)
                response = APIClient().post(reverse('api_transaction_execute'), payload, format='json')
                results.append(response)
            except Exception as exc:  # surfaced in the main thread below
                errors.append(exc)
            finally:
                # This thread never goes through Django's request/response
                # cycle machinery that normally closes connections - without
                # this, the connection opened by this thread stays attached
                # to the test database and the teardown DROP DATABASE fails
                # with "database is being accessed by other users".
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        if errors:
            raise errors[0]
        self.assertEqual(len(results), 2)
        status_codes = sorted(r.status_code for r in results)
        self.assertEqual(
            status_codes, [200, 201],
            'exactly one request must create, the other must be deduplicated - never both, never neither',
        )
        self.assertEqual(Transaction.objects.filter(idempotency_key=key).count(), 1)
        self.assertEqual(Payment.objects.count(), 1, "the losing request's orphan Payment must be discarded, never left dangling")
        self.assertEqual(TransactionAttempt.objects.count(), 1)
        self.assertEqual(create_payment.call_count, 1)
