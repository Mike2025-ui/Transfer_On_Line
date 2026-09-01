"""Business-model audit, Phase 4 - end-to-end integration suite for the new
Transaction Engine (USE_NEW_TRANSACTION_ENGINE), exercised exclusively via
@override_settings scoped to each test class - .env/settings.py are never
touched, and the flag stays 'false' everywhere outside these tests.

Each scenario drives the real HTTP endpoints (POST /transactions/execute/,
GET /transactions/pending/, POST /transactions/result/,
`dispatch_due_transaction_retries`) exactly as a real Flutter Client and a
real Gateway phone would - no real USSD, no real Gateway hardware, no real
payment provider (JekoProvider.create_payment stays mocked, same as the
rest of this project's test suite).

The "simulated Gateway" in every scenario below is deliberately dumb: it
only ever reads gateway_task_payload() (via the /transactions/pending/
response) and posts a canned result back. It never imports or references
Operator/Service/UssdCode/Scheduler - proving, structurally, that the
backend alone decides everything before any task reaches it."""

from contextlib import nullcontext
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Gateway, Operator, Service, Transaction, TransactionAttempt, UssdCode
from apps.devices.models import GatewaySim
from apps.devices.services.reservation_manager import ReservationManager
from apps.payments.services.payment_service import PaymentService


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class Scenario1FullSuccessTests(TestCase):
    """Orange + Internet + 500 FCFA, success, all 14 checkpoints requested."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')  # decoy - must never be picked
        self.internet = Service.objects.create(name='Internet', code='subscription')
        self.ussd_code = UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500,
            label='Orange Internet 500F', template='*456*4*1#', is_active=True,
        )
        self.orange_gw = Gateway.objects.create(
            name='Orange - gw1', host='gw-orange', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        self.orange_sim = GatewaySim.objects.create(gateway=self.orange_gw, operator=self.orange, slot=1, is_active=True)
        mtn_gw = Gateway.objects.create(
            name='MTN - gw2', host='gw-mtn', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        GatewaySim.objects.create(gateway=mtn_gw, operator=self.mtn, slot=0, is_active=True)
        # Business-model audit Phase 7: the simulated Gateway authenticates as
        # itself, exactly like a real device would - Orange, never the decoy.
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.orange_gw.generate_secret())

    @patch('apps.payments.providers.jeko.JekoProvider.verify_payment')
    @patch('apps.payments.providers.jeko.JekoProvider.create_payment')
    def test_full_success_cycle(self, create_payment, verify_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult, PaymentStatusResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': self.orange.id, 'service_id': self.internet.id, 'amount': 500, 'recipient_phone': '0700000001'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        tx = Transaction.objects.get(reference=response.data['reference'])

        # PendingTransactionsView only exposes a task once payment is
        # confirmed - call PaymentService.verify() directly (mocked
        # verify_payment(), no real payment provider call), same pattern as
        # the rest of this project's suites.
        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        PaymentService.verify(tx.payment)

        # 1. Transaction créée.
        self.assertIsNotNone(tx.pk)
        self.assertEqual(tx.operator_id, self.orange.id)
        self.assertEqual(tx.service_id, self.internet.id)
        self.assertEqual(tx.amount, 500)

        # 2 & 3. UssdCode correctement sélectionné et figé.
        self.assertEqual(tx.ussd_code_used_id, self.ussd_code.id)

        # 4. Scheduler sélectionne uniquement le Gateway Orange (jamais MTN,
        # présent dans le setUp précisément pour le prouver).
        self.assertEqual(tx.gateway_id, self.orange_gw.id)

        # 5, 6, 7. TransactionAttempt créé, gateway_sim = SIM Orange, bon slot.
        attempt = tx.attempts.get(attempt_number=1)
        self.assertEqual(attempt.gateway_sim_id, self.orange_sim.id)
        self.assertEqual(attempt.gateway_sim.slot, 1)
        self.assertEqual(attempt.status, 'assigned')

        # --- Simulation du Gateway : lit UNIQUEMENT la tâche déjà préparée ---
        pending = self.client.get(reverse('api_transaction_pending'), {'gateway_uuid': self.orange_gw.host})
        self.assertEqual(len(pending.data), 1)
        task = pending.data[0]

        # 8 & 9. Code USSD déjà entièrement rendu, transmis avec le sim_slot -
        # le "Gateway simulé" ci-dessous ne fait jamais que le lire.
        self.assertEqual(task['ussd_code'], '*456*4*1#')
        self.assertNotIn('{', task['ussd_code'], 'aucun placeholder ne doit jamais atteindre le Gateway')
        self.assertEqual(task['sim_slot'], 1)

        # 10. Résultat SUCCESS simulé - aucun vrai USSD, aucun vrai réseau.
        result_response = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': task['reference'], 'success': True, 'result': 'OK'},
            format='json',
        )
        self.assertEqual(result_response.status_code, 200)

        # 11. TransactionAttempt -> success.
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'success')
        self.assertEqual(attempt.raw_response, 'OK')

        # 12. Transaction -> success.
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success')

        # 13. ReservationManager.release() a bien été appelé - effet observable.
        self.orange_sim.refresh_from_db()
        self.assertEqual(self.orange_sim.success_count, 1)

        # 14. Aucun retry programmé.
        self.assertIsNone(tx.next_retry_at)


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class Scenario2OrangeUnavailableTests(TestCase):
    """Orange Gateway OFFLINE, MTN Gateway ONLINE - MTN must never be picked."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Orange défaut',
            template='*456*{montant}#', is_active=True, is_default=True,
        )
        self.orange_gw = Gateway.objects.create(
            name='Orange - gw1', host='gw-orange', status='offline', is_active=True, last_heartbeat=timezone.now(),
        )
        self.orange_sim = GatewaySim.objects.create(gateway=self.orange_gw, operator=self.orange, slot=0, is_active=True)
        mtn_gw = Gateway.objects.create(
            name='MTN - gw2', host='gw-mtn', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        GatewaySim.objects.create(gateway=mtn_gw, operator=self.mtn, slot=0, is_active=True)

    @patch('apps.payments.providers.jeko.JekoProvider.create_payment')
    def test_orange_offline_never_falls_back_to_mtn_then_recovers(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': self.orange.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        tx = Transaction.objects.get(reference=response.data['reference'])

        self.assertIsNone(tx.gateway_id, 'Orange hors ligne : aucun Gateway ne doit être assigné, surtout pas MTN')
        self.assertEqual(tx.status, 'pending')
        self.assertIsNotNone(tx.next_retry_at)
        self.assertEqual(tx.attempts.count(), 0)

        # Orange revient en ligne.
        self.orange_gw.status = 'online'
        self.orange_gw.last_heartbeat = timezone.now()
        self.orange_gw.save(update_fields=['status', 'last_heartbeat'])
        tx.next_retry_at = timezone.now() - timedelta(seconds=1)
        tx.save(update_fields=['next_retry_at'])

        call_command('dispatch_due_transaction_retries', stdout=StringIO())

        tx.refresh_from_db()
        self.assertEqual(tx.gateway_id, self.orange_gw.id)
        self.assertEqual(tx.attempts.count(), 1)
        self.assertEqual(tx.attempts.get(attempt_number=1).gateway_sim_id, self.orange_sim.id)


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class Scenario3RetryableFailureTests(TestCase):
    """"network error" -> retryable, new attempt on a different SIM."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=1000,
            label='Orange 1000F', template='*456*4*2#', is_active=True,
        )
        self.gw1 = Gateway.objects.create(name='Orange - gw1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        self.gw2 = Gateway.objects.create(name='Orange - gw2', host='gw2', status='online', is_active=True, last_heartbeat=timezone.now())
        GatewaySim.objects.create(gateway=self.gw1, operator=self.orange, slot=0, is_active=True)
        GatewaySim.objects.create(gateway=self.gw2, operator=self.orange, slot=0, is_active=True)

    @patch('apps.payments.providers.jeko.JekoProvider.create_payment')
    def test_network_error_is_retried_on_a_different_sim(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': self.orange.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'},
            format='json',
        )
        tx = Transaction.objects.get(reference=response.data['reference'])
        first_sim_id = tx.attempts.get(attempt_number=1).gateway_sim_id

        # Business-model audit Phase 7: authenticate as whichever Gateway the
        # Scheduler actually picked (gw1 or gw2 - not deterministic here).
        self.client.credentials(HTTP_X_GATEWAY_SECRET=Gateway.objects.get(pk=tx.gateway_id).generate_secret())
        result_response = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': False, 'result': 'network error'},
            format='json',
        )
        self.assertEqual(result_response.status_code, 200)

        first_attempt = tx.attempts.get(attempt_number=1)
        self.assertEqual(first_attempt.failure_reason, 'network_error')
        tx.refresh_from_db()
        self.assertIsNotNone(tx.next_retry_at)
        self.assertEqual(tx.status, 'pending')

        tx.next_retry_at = timezone.now() - timedelta(seconds=1)
        tx.save(update_fields=['next_retry_at'])
        call_command('dispatch_due_transaction_retries', stdout=StringIO())

        tx.refresh_from_db()
        self.assertEqual(tx.attempts.count(), 2)
        second_attempt = tx.attempts.get(attempt_number=2)
        self.assertNotEqual(second_attempt.gateway_sim_id, first_sim_id, 'la SIM déjà tentée doit être exclue')
        first_attempt.refresh_from_db()
        self.assertEqual(first_attempt.status, 'failed', 'la tentative précédente reste historique')
        self.assertEqual(tx.gateway_id, second_attempt.gateway_sim.gateway_id)


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class Scenario4NonRetryableFailureTests(TestCase):
    """"Numero invalide" -> never retried, transaction ends up 'failed'."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=1000,
            label='Orange 1000F', template='*456*4*2#', is_active=True,
        )
        gw = Gateway.objects.create(name='Orange - gw1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        GatewaySim.objects.create(gateway=gw, operator=self.orange, slot=0, is_active=True)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=gw.generate_secret())

    @patch('apps.payments.providers.jeko.JekoProvider.create_payment')
    def test_invalid_number_is_never_retried_and_fails_the_transaction(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': self.orange.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'},
            format='json',
        )
        tx = Transaction.objects.get(reference=response.data['reference'])

        result_response = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': False, 'result': 'Numero invalide'},
            format='json',
        )
        self.assertEqual(result_response.status_code, 200)

        attempt = tx.attempts.get(attempt_number=1)
        self.assertEqual(attempt.failure_reason, 'invalid_number')
        tx.refresh_from_db()
        self.assertIsNone(tx.next_retry_at)
        self.assertEqual(tx.status, 'failed')
        self.assertEqual(tx.attempts.count(), 1, 'aucune nouvelle tentative ne doit jamais être créée')


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class Scenario5TimeoutTests(TestCase):
    """A reservation older than TIMEOUT_SECONDS is expired, classified as a
    timeout, and becomes retryable through the normal dispatch command."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=1000,
            label='Orange 1000F', template='*456*4*2#', is_active=True,
        )
        self.gw1 = Gateway.objects.create(name='Orange - gw1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        self.gw2 = Gateway.objects.create(name='Orange - gw2', host='gw2', status='online', is_active=True, last_heartbeat=timezone.now())
        GatewaySim.objects.create(gateway=self.gw1, operator=self.orange, slot=0, is_active=True)
        GatewaySim.objects.create(gateway=self.gw2, operator=self.orange, slot=0, is_active=True)

    @patch('apps.payments.providers.jeko.JekoProvider.create_payment')
    def test_timeout_schedules_a_retry_and_dispatch_creates_a_new_attempt(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': self.orange.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'},
            format='json',
        )
        tx = Transaction.objects.get(reference=response.data['reference'])
        attempt = tx.attempts.get(attempt_number=1)
        TransactionAttempt.objects.filter(pk=attempt.pk).update(created_at=timezone.now() - timedelta(seconds=99999))

        released = ReservationManager.release_expired()
        self.assertEqual(released, 1)

        attempt.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual(attempt.status, 'expired')
        self.assertEqual(attempt.failure_reason, 'timeout')
        self.assertIsNotNone(tx.next_retry_at)

        tx.next_retry_at = timezone.now() - timedelta(seconds=1)
        tx.save(update_fields=['next_retry_at'])
        call_command('dispatch_due_transaction_retries', stdout=StringIO())

        tx.refresh_from_db()
        self.assertEqual(tx.attempts.count(), 2)
        self.assertEqual(tx.attempts.get(attempt_number=2).status, 'assigned')


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class Scenario6LateResultTests(TestCase):
    """A Gateway result arriving after release_expired() already presumed a
    timeout - success, failure, and a repeated duplicate of each."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=1000,
            label='Orange 1000F', template='*456*4*2#', is_active=True,
        )
        gw = Gateway.objects.create(name='Orange - gw1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        self.sim = GatewaySim.objects.create(gateway=gw, operator=self.orange, slot=0, is_active=True)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=gw.generate_secret())

    def _create_and_expire(self, create_payment):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})
        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': self.orange.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'},
            format='json',
        )
        tx = Transaction.objects.get(reference=response.data['reference'])
        attempt = tx.attempts.get(attempt_number=1)
        TransactionAttempt.objects.filter(pk=attempt.pk).update(created_at=timezone.now() - timedelta(seconds=99999))
        ReservationManager.release_expired()
        return tx, attempt

    def _report(self, tx, success, result):
        return self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': success, 'result': result},
            format='json',
        )

    @patch('apps.payments.providers.jeko.JekoProvider.create_payment')
    def test_late_success_resolves_without_double_effects(self, create_payment, _redis_lock):
        tx, attempt = self._create_and_expire(create_payment)

        response = self._report(tx, True, 'OK')

        self.assertEqual(response.status_code, 200)
        tx.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(tx.status, 'success')
        self.assertIsNone(tx.next_retry_at)
        self.assertEqual(attempt.status, 'success')
        self.sim.refresh_from_db()
        self.assertEqual(self.sim.success_count, 0, 'jamais un second comptage - le timeout avait déjà compté une fois en échec')
        self.assertEqual(self.sim.failure_count, 1)

    @patch('apps.payments.providers.jeko.JekoProvider.create_payment')
    def test_late_failure_corrects_the_record_without_a_second_retry(self, create_payment, _redis_lock):
        tx, attempt = self._create_and_expire(create_payment)
        tx.refresh_from_db()
        retry_at_from_expiry = tx.next_retry_at

        self._report(tx, False, 'Numero invalide')

        attempt.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual(attempt.status, 'failed')
        self.assertEqual(attempt.failure_reason, 'invalid_number')
        self.assertEqual(tx.next_retry_at, retry_at_from_expiry, 'jamais un second retry programmé pour ce résultat tardif')
        self.assertEqual(
            tx.events.filter(event_type='retry_scheduled').count(), 1,
            "une seule décision de retry doit exister - celle prise au moment de l'expiration",
        )

    @patch('apps.payments.providers.jeko.JekoProvider.create_payment')
    def test_the_same_late_result_reported_twice_is_fully_idempotent(self, create_payment, _redis_lock):
        tx, attempt = self._create_and_expire(create_payment)
        self._report(tx, True, 'OK')
        self.sim.refresh_from_db()
        success_after_first = self.sim.success_count
        failure_after_first = self.sim.failure_count

        second = self._report(tx, True, 'OK')

        self.assertEqual(second.status_code, 200)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success')
        self.sim.refresh_from_db()
        self.assertEqual(self.sim.success_count, success_after_first)
        self.assertEqual(self.sim.failure_count, failure_after_first)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'success', 'jamais corrompu par le second rapport')


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class Scenario7DuplicateRequestTests(TestCase):
    """Two distinct notions of "duplicate", reported separately - see the
    plan and the final report for why the second one is a documented
    finding, not a fix applied without a product decision."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=1000,
            label='Orange 1000F', template='*456*4*2#', is_active=True,
        )
        gw = Gateway.objects.create(name='Orange - gw1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        self.sim = GatewaySim.objects.create(gateway=gw, operator=self.orange, slot=0, is_active=True)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=gw.generate_secret())

    @patch('apps.payments.providers.jeko.JekoProvider.create_payment')
    def test_duplicate_result_report_for_the_same_transaction_is_idempotent(self, create_payment, _redis_lock):
        """The "undesired concurrent execution" case on the dispatch/Gateway
        side - already protected by select_for_update()/
        TransactionStateMachine.is_terminal(); this proves it under the new
        engine specifically."""
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})
        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': self.orange.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'},
            format='json',
        )
        tx = Transaction.objects.get(reference=response.data['reference'])
        payload = {'transaction_reference': str(tx.reference), 'success': True, 'result': 'OK'}

        first = self.client.post(reverse('api_transaction_result'), payload, format='json')
        second = self.client.post(reverse('api_transaction_result'), payload, format='json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200, 'un doublon ne doit jamais provoquer une erreur serveur')
        self.sim.refresh_from_db()
        self.assertEqual(self.sim.success_count, 1, 'jamais compté deux fois')
        tx.refresh_from_db()
        self.assertEqual(tx.attempts.count(), 1, 'aucune seconde exécution/réservation créée')

    @patch('apps.payments.providers.jeko.JekoProvider.create_payment')
    def test_submitting_the_exact_same_creation_request_twice_creates_two_independent_transactions(self, create_payment, _redis_lock):
        """CONSTAT (pas une correction) : /transactions/execute/ ne porte
        aujourd'hui aucune clé d'idempotence - Transaction.reference et
        Payment.reference sont générées côté serveur à chaque appel. Deux
        soumissions identiques produisent donc deux Transactions distinctes,
        chacune avec sa propre réservation Gateway/SIM. Documenté ici
        volontairement sans correctif : concevoir une clé d'idempotence
        (client-générée ? fenêtre de temps ? hash de charge utile ?) est une
        décision de produit/API, pas un défaut à corriger à l'aveugle."""
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})
        payload = {'operator_id': self.orange.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'}

        first = self.client.post(reverse('api_transaction_execute'), payload, format='json')
        second = self.client.post(reverse('api_transaction_execute'), payload, format='json')

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(
            first.data['reference'], second.data['reference'],
            "constat actuel : aucune déduplication côté serveur sur l'endpoint de création",
        )
        self.assertEqual(Transaction.objects.count(), 2)
