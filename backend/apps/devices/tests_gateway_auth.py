"""Business-model audit, Phase 7 - Gateway authentication + double-dispatch
protection.

Every Gateway-facing endpoint (heartbeat, pending, result, sms pending, sms
result) used to be `AllowAny` and trusted a client-supplied `gateway_uuid`
string as identity - `GatewayManager.register_heartbeat()` auto-created a
row for any unknown uuid, and `PendingTransactionsView`/`TransactionResultView`
never checked that the caller was actually the Gateway a task was assigned
to. This suite proves the fix: identity now comes exclusively from a secret
(`Gateway.api_key_hash`, see `apps/core/models.py::Gateway.generate_secret`)
sent as the `X-Gateway-Secret` header and checked by
`apps.devices.views._authenticate_gateway` - `gateway_uuid`/`gateway_id`
sent by a caller are never trusted for identity again."""

from contextlib import nullcontext
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Gateway, Operator, Service, Transaction, TransactionAttempt, UssdCode
from apps.devices.models import GatewaySim


class GatewayHeartbeatAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.gateway = Gateway.objects.create(name='Orange - gw1', host='')
        self.secret = self.gateway.generate_secret()

    def _heartbeat(self, gateway_id=None, gateway_uuid='gw-1'):
        url = (
            reverse('api_gateway_heartbeat', args=[gateway_id])
            if gateway_id is not None
            else reverse('api_gateway_heartbeat_create')
        )
        return self.client.post(
            url,
            {'status': 'online', 'gateway_uuid': gateway_uuid, 'details': {'uuid': gateway_uuid}},
            format='json',
        )

    # Test 1 - Gateway valide -> heartbeat accepté.
    def test_valid_gateway_heartbeat_is_accepted(self):
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret)
        response = self._heartbeat()
        self.assertEqual(response.status_code, 200)
        self.gateway.refresh_from_db()
        self.assertEqual(self.gateway.host, 'gw-1')

    def test_missing_secret_is_rejected(self):
        response = self._heartbeat()
        self.assertEqual(response.status_code, 401)

    # Test 2 - Gateway inconnu -> rejeté, jamais auto-provisionné.
    def test_unknown_secret_is_rejected_and_never_auto_provisions_a_gateway(self):
        self.client.credentials(HTTP_X_GATEWAY_SECRET='this-secret-was-never-issued-by-anyone')
        response = self._heartbeat()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Gateway.objects.count(), 1, 'no row is ever created for an unrecognized secret')

    # Test 3 - mauvais secret pour une Gateway réelle -> rejeté.
    def test_wrong_secret_for_a_real_gateway_is_rejected(self):
        self.client.credentials(HTTP_X_GATEWAY_SECRET='a-plausible-but-incorrect-secret-string')
        response = self._heartbeat()
        self.assertEqual(response.status_code, 401)

    # Test 13 - Gateway authentifiée mais inactive -> 403, jamais traitée comme valide.
    def test_authenticated_but_inactive_gateway_is_rejected(self):
        self.gateway.is_active = False
        self.gateway.save(update_fields=['is_active'])
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret)
        response = self._heartbeat()
        self.assertEqual(response.status_code, 403)
        self.gateway.refresh_from_db()
        self.assertEqual(self.gateway.host, '', 'a disabled Gateway must never have its row updated')

    # Test 4 - Gateway A ne peut pas usurper Gateway B, ni via l'id de l'URL
    # ni via gateway_uuid dans le corps - seule l'identité authentifiée compte.
    def test_gateway_cannot_impersonate_another_gateway_via_url_id_or_body_uuid(self):
        victim = Gateway.objects.create(name='Victim', host='victim-uuid', status='offline')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret)  # authenticated as self.gateway, not victim

        response = self._heartbeat(gateway_id=victim.id, gateway_uuid='victim-uuid')

        self.assertEqual(response.status_code, 200)
        victim.refresh_from_db()
        self.assertEqual(victim.status, 'offline', "the URL's gateway_id must never select another Gateway's row")
        self.assertIsNone(victim.last_heartbeat)
        self.gateway.refresh_from_db()
        self.assertEqual(self.gateway.status, 'online', "only the authenticated caller's own row is ever written")
        self.assertEqual(self.gateway.host, 'victim-uuid', 'host stays informational telemetry, stamped on the real caller')


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class PendingTransactionsAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Orange défaut',
            template='*456*{montant}#', is_active=True, is_default=True,
        )
        UssdCode.objects.create(
            operator=self.mtn, service=None, label='MTN défaut',
            template='*456*{montant}#', is_active=True, is_default=True,
        )
        self.orange_gw = Gateway.objects.create(
            name='Orange - gw1', host='gw-orange', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        GatewaySim.objects.create(gateway=self.orange_gw, operator=self.orange, slot=0, is_active=True)
        self.orange_secret = self.orange_gw.generate_secret()

        self.mtn_gw = Gateway.objects.create(
            name='MTN - gw2', host='gw-mtn', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        GatewaySim.objects.create(gateway=self.mtn_gw, operator=self.mtn, slot=0, is_active=True)
        self.mtn_secret = self.mtn_gw.generate_secret()

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.verify_payment')
    def _create_transaction(self, operator, create_payment, verify_payment):
        from apps.payments.providers.base import PaymentInitResult, PaymentStatusResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})
        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': operator.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'},
            format='json',
        )
        tx = Transaction.objects.get(reference=response.data['reference'])
        # PendingTransactionsView only exposes a task once payment is
        # confirmed - simulate the CinetPay notify ping, same pattern as the
        # rest of this project's suites (mocked verify_payment(), real notify
        # endpoint), never a real payment provider call.
        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': tx.payment.reference}, format='json')
        return tx

    # Test 7 - Gateway non authentifié -> aucune tâche.
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_unauthenticated_poll_is_rejected(self, create_payment, _redis_lock):
        self._create_transaction(self.orange, create_payment)
        response = self.client.get(reverse('api_transaction_pending'))
        self.assertEqual(response.status_code, 401)

    # Test 8 - Gateway authentifié -> tâches autorisées (les siennes).
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_authenticated_gateway_sees_its_own_task(self, create_payment, _redis_lock):
        tx = self._create_transaction(self.orange, create_payment)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.orange_secret)
        response = self.client.get(reverse('api_transaction_pending'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['reference'], str(tx.reference))

    # Test 5 - Gateway MTN ne récupère jamais une transaction Orange.
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_mtn_gateway_never_sees_an_orange_transaction(self, create_payment, _redis_lock):
        self._create_transaction(self.orange, create_payment)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.mtn_secret)
        response = self.client.get(reverse('api_transaction_pending'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    # Test 6 - symétrique : Gateway Orange ne récupère jamais une transaction MTN.
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_orange_gateway_never_sees_an_mtn_transaction(self, create_payment, _redis_lock):
        self._create_transaction(self.mtn, create_payment)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.orange_secret)
        response = self.client.get(reverse('api_transaction_pending'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    # Test explicite d'usurpation via gateway_uuid dans l'URL (Partie 6) :
    # authentifié comme Orange, prétendre être le Gateway MTN dans le query
    # param doit être rejeté, pas juste ignoré.
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_claiming_a_different_gateway_uuid_than_the_authenticated_one_is_rejected(self, create_payment, _redis_lock):
        self._create_transaction(self.orange, create_payment)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.orange_secret)
        response = self.client.get(reverse('api_transaction_pending'), {'gateway_uuid': self.mtn_gw.host})
        self.assertEqual(response.status_code, 403)


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class TransactionResultAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Orange défaut',
            template='*456*{montant}#', is_active=True, is_default=True,
        )
        # The only eligible Orange gateway at creation time - Scheduler has
        # nothing else to pick, so tx.gateway_id is deterministically this one.
        self.gw_a = Gateway.objects.create(
            name='Orange - gwA', host='gw-a', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        self.sim_a = GatewaySim.objects.create(gateway=self.gw_a, operator=self.orange, slot=0, is_active=True)
        self.secret_a = self.gw_a.generate_secret()

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def _create_transaction_on_gw_a(self, create_payment):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})
        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': self.orange.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'},
            format='json',
        )
        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertEqual(tx.gateway_id, self.gw_a.id)
        return tx

    # Test 9 - Gateway B ne peut pas envoyer le résultat d'une tâche Gateway A.
    def test_a_different_gateway_cannot_report_a_result_for_this_task(self, _redis_lock):
        tx = self._create_transaction_on_gw_a()
        gw_b = Gateway.objects.create(
            name='Orange - gwB', host='gw-b', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        secret_b = gw_b.generate_secret()
        self.client.credentials(HTTP_X_GATEWAY_SECRET=secret_b)

        response = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': True, 'result': 'OK'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'pending', "an unrelated Gateway must never resolve someone else's task")
        self.sim_a.refresh_from_db()
        self.assertEqual(self.sim_a.success_count, 0, 'no side effect at all from the rejected report')

    # Test 10 - un résultat valide, envoyé par la bonne Gateway, est accepté.
    def test_valid_result_from_the_owning_gateway_is_accepted(self, _redis_lock):
        tx = self._create_transaction_on_gw_a()
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret_a)

        response = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': True, 'result': 'OK'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success')

    # Test 11 - le même résultat envoyé deux fois par la bonne Gateway reste
    # idempotent (comportement Phase D/3 préexistant, non régressé par l'auth).
    def test_the_same_result_reported_twice_by_the_owning_gateway_is_idempotent(self, _redis_lock):
        tx = self._create_transaction_on_gw_a()
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret_a)
        payload = {'transaction_reference': str(tx.reference), 'success': True, 'result': 'OK'}

        first = self.client.post(reverse('api_transaction_result'), payload, format='json')
        second = self.client.post(reverse('api_transaction_result'), payload, format='json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200, 'a duplicate report must never 500 nor be rejected as unauthorized')
        self.sim_a.refresh_from_db()
        self.assertEqual(self.sim_a.success_count, 1, 'never double-counted')
        self.assertEqual(TransactionAttempt.objects.filter(transaction=tx).count(), 1)


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class DoubleDispatchProtectionTests(TestCase):
    """Part 8/9 of the brief: the same TransactionAttempt must never be
    handed out to more than one poll - proved here by polling the SAME,
    legitimately authenticated Gateway twice, which is the realistic,
    deterministic version of the scenario (two DIFFERENT Gateways can no
    longer even reach the same task at all once identity is secret-based -
    see PendingTransactionsAuthTests - so the residual risk this protects
    against is the same credential being polled twice, e.g. two ticks
    racing, before a result has been reported)."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Orange défaut',
            template='*456*{montant}#', is_active=True, is_default=True,
        )
        self.gw = Gateway.objects.create(
            name='Orange - gw1', host='gw-1', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        GatewaySim.objects.create(gateway=self.gw, operator=self.orange, slot=0, is_active=True)
        self.secret = self.gw.generate_secret()

    # Test 12 - même TransactionAttempt, ne peut être dispatché deux fois.
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.verify_payment')
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_the_same_attempt_is_never_dispatched_twice(self, create_payment, verify_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult, PaymentStatusResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})
        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': self.orange.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'},
            format='json',
        )
        tx = Transaction.objects.get(reference=response.data['reference'])
        attempt = tx.attempts.get(attempt_number=1)
        self.assertEqual(attempt.status, 'assigned')
        # PendingTransactionsView only exposes a task once payment is
        # confirmed - see PendingTransactionsAuthTests._create_transaction's
        # doc for why.
        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': tx.payment.reference}, format='json')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret)

        first_poll = self.client.get(reverse('api_transaction_pending'))
        self.assertEqual(len(first_poll.data), 1)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'dispatched', 'claimed on first poll - assigned -> dispatched, no migration needed')
        self.assertIsNotNone(attempt.dispatched_at)

        second_poll = self.client.get(reverse('api_transaction_pending'))
        self.assertEqual(second_poll.data, [], 'a task already dispatched must never be handed out again')


class SecretHygieneTests(TestCase):
    """Test 14 - the raw secret must never appear in a log record. Uses the
    auth-failure path (see _authenticate_gateway's logger.warning calls),
    the one place most likely to be tempted to log the offending value for
    debugging - and proves it never does, on any of the three rejection
    branches."""

    def setUp(self):
        self.client = APIClient()
        self.gateway = Gateway.objects.create(name='Orange - gw1', host='')
        self.secret = self.gateway.generate_secret()

    def _assert_secret_absent_from(self, captured, secret):
        self.assertTrue(captured.records, 'expected at least one log record for this rejection')
        for record in captured.records:
            self.assertNotIn(secret, record.getMessage())
            self.assertNotIn(secret, str(record.args))

    def test_wrong_secret_never_appears_in_logs(self):
        wrong_secret = 'a-value-that-must-never-be-logged-verbatim'
        self.client.credentials(HTTP_X_GATEWAY_SECRET=wrong_secret)
        with self.assertLogs('apps.devices.views', level='WARNING') as captured:
            response = self.client.post(
                reverse('api_gateway_heartbeat_create'),
                {'status': 'online', 'gateway_uuid': 'gw-x', 'details': {'uuid': 'gw-x'}},
                format='json',
            )
        self.assertEqual(response.status_code, 401)
        self._assert_secret_absent_from(captured, wrong_secret)

    def test_a_missing_secret_is_rejected_and_still_logged_for_observability(self):
        # No secret exists in this scenario at all - nothing to leak - this
        # just confirms the rejection is itself observable (not silent),
        # complementing the "never leaks a real secret" tests above.
        with self.assertLogs('apps.devices.views', level='WARNING') as captured:
            response = self.client.post(
                reverse('api_gateway_heartbeat_create'),
                {'status': 'online', 'gateway_uuid': 'gw-x', 'details': {'uuid': 'gw-x'}},
                format='json',
            )
        self.assertEqual(response.status_code, 401)
        self.assertTrue(captured.records)

    def test_disabled_gateway_rejection_never_logs_the_valid_secret(self):
        self.gateway.is_active = False
        self.gateway.save(update_fields=['is_active'])
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret)
        with self.assertLogs('apps.devices.views', level='WARNING') as captured:
            response = self.client.post(
                reverse('api_gateway_heartbeat_create'),
                {'status': 'online', 'gateway_uuid': 'gw-x', 'details': {'uuid': 'gw-x'}},
                format='json',
            )
        self.assertEqual(response.status_code, 403)
        self._assert_secret_absent_from(captured, self.secret)

    def test_the_secret_never_appears_in_a_successful_response_body(self):
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret)
        response = self.client.post(
            reverse('api_gateway_heartbeat_create'),
            {'status': 'online', 'gateway_uuid': 'gw-x', 'details': {'uuid': 'gw-x'}},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.secret, response.content.decode())
