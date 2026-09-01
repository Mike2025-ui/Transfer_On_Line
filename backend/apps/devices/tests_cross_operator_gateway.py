"""Business-model audit, Phase 7.2 - structural cross-operator safety.

Root cause fixed (see the approved plan): ExecuteTransactionView's legacy
branch (USE_NEW_TRANSACTION_ENGINE=false) used to call _select_gateway(),
"any online gateway, ignoring operator/SIM/capacity entirely" - an Orange
transaction could be assigned to, and retrieved by, an MTN-only Gateway.
PendingTransactionsView's own operator/SIM cross-check was also gated
behind the same flag, so even that defense-in-depth was inactive.

Fixed by making both engines share one source of truth:
GatewayManager.select_operator_gateway() (legacy) reuses the exact same
eligible_sims()/GatewayScoreService chain Scheduler.select() (new engine)
already used - Transaction.operator -> GatewaySim.operator -> Gateway is
now the only trusted path to an assignment, regardless of which engine is
active. PendingTransactionsView's operator/SIM filter is now unconditional
(the "second barrier"). RetryManager.dispatch_due_retries() branches the
same way, so a legacy transaction queued for lack of an eligible Gateway
recovers automatically once one appears - without ever re-triggering the
already-accepted payment.

Every test here drives the real HTTP endpoints
(POST /transactions/execute/, GET /transactions/pending/,
dispatch_due_transaction_retries) with a real Gateway secret (Phase 7) -
no real USSD, no real payment provider (JekoProvider.create_payment stays
mocked, same as the rest of this project's suite). Each scenario is
run under BOTH engines (Tests 13/14 of the brief) via a private
_xxx() implementation method (carries its own @patch stack) plus one thin
test_..._new_engine/_legacy wrapper per engine that just picks the flag -
this keeps the @patch/@override_settings bookkeeping in one place per
scenario instead of duplicating full test bodies."""

from contextlib import nullcontext
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Device, Gateway, Operator, Payment, Service, Transaction, UssdCode
from apps.devices.models import GatewaySim
from apps.payments.services.payment_service import PaymentService

_REDIS_LOCK = 'apps.payments.services.payment_service.redis_lock'
_CREATE_PAYMENT = 'apps.payments.providers.jeko.JekoProvider.create_payment'
_VERIFY_PAYMENT = 'apps.payments.providers.jeko.JekoProvider.verify_payment'


def _mocked_payment():
    from apps.payments.providers.base import PaymentInitResult
    return PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})


class CrossOperatorGatewayTests(TestCase):

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

    def _gateway(self, name, host, **kwargs):
        defaults = {'status': 'online', 'is_active': True, 'last_heartbeat': timezone.now()}
        defaults.update(kwargs)
        return Gateway.objects.create(name=name, host=host, **defaults)

    def _sim(self, gateway, operator, slot=0):
        return GatewaySim.objects.create(gateway=gateway, operator=operator, slot=slot, is_active=True)

    def _execute(self, operator):
        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator_id': operator.id, 'service_id': self.internet.id, 'amount': 1000, 'recipient_phone': '0700000001'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        return Transaction.objects.get(reference=response.data['reference'])

    def _authenticated_pending(self, gateway):
        secret = gateway.generate_secret()
        client = APIClient()
        client.credentials(HTTP_X_GATEWAY_SECRET=secret)
        return client.get(reverse('api_transaction_pending'))

    # ------------------------------------------------------------------
    # Tests 1-3 - assignation de base, un seul Gateway disponible
    # ------------------------------------------------------------------

    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def _orange_with_orange_gateway_is_accepted(self, _redis_lock, create_payment):
        create_payment.return_value = _mocked_payment()
        gw = self._gateway('Orange - gw1', 'gw-orange')
        self._sim(gw, self.orange)
        tx = self._execute(self.orange)
        self.assertEqual(tx.gateway_id, gw.id, 'Test 1 - Orange + Gateway Orange -> accepté, assigné à Orange')

    def test_1_orange_with_orange_gateway_is_accepted_new_engine(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=True):
            self._orange_with_orange_gateway_is_accepted()

    def test_1_orange_with_orange_gateway_is_accepted_legacy(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=False):
            self._orange_with_orange_gateway_is_accepted()

    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def _orange_with_only_mtn_gateway_is_queued_not_assigned(self, _redis_lock, create_payment):
        create_payment.return_value = _mocked_payment()
        mtn_gw = self._gateway('MTN - gw1', 'gw-mtn')
        self._sim(mtn_gw, self.mtn)
        tx = self._execute(self.orange)
        self.assertIsNone(tx.gateway_id, 'Test 2 - Orange + Gateway MTN uniquement -> jamais assigné à MTN')
        self.assertEqual(tx.status, 'pending')
        self.assertIsNotNone(tx.next_retry_at, 'mis en attente via le mécanisme de retry existant')

    def test_2_orange_with_only_mtn_gateway_is_queued_new_engine(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=True):
            self._orange_with_only_mtn_gateway_is_queued_not_assigned()

    def test_2_orange_with_only_mtn_gateway_is_queued_legacy(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=False):
            self._orange_with_only_mtn_gateway_is_queued_not_assigned()

    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def _mtn_with_only_orange_gateway_is_queued_not_assigned(self, _redis_lock, create_payment):
        create_payment.return_value = _mocked_payment()
        orange_gw = self._gateway('Orange - gw1', 'gw-orange')
        self._sim(orange_gw, self.orange)
        tx = self._execute(self.mtn)
        self.assertIsNone(tx.gateway_id, 'Test 3 - MTN + Gateway Orange uniquement -> jamais assigné à Orange')
        self.assertEqual(tx.status, 'pending')
        self.assertIsNotNone(tx.next_retry_at)

    def test_3_mtn_with_only_orange_gateway_is_queued_new_engine(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=True):
            self._mtn_with_only_orange_gateway_is_queued_not_assigned()

    def test_3_mtn_with_only_orange_gateway_is_queued_legacy(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=False):
            self._mtn_with_only_orange_gateway_is_queued_not_assigned()

    # ------------------------------------------------------------------
    # Tests 4-5 - les deux Gateways existent, le bon est choisi
    # ------------------------------------------------------------------

    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def _orange_and_mtn_gateways_orange_tx_picks_orange(self, _redis_lock, create_payment):
        create_payment.return_value = _mocked_payment()
        orange_gw = self._gateway('Orange - gw1', 'gw-orange')
        self._sim(orange_gw, self.orange)
        mtn_gw = self._gateway('MTN - gw1', 'gw-mtn')
        self._sim(mtn_gw, self.mtn)
        tx = self._execute(self.orange)
        self.assertEqual(tx.gateway_id, orange_gw.id, 'Test 4 - Orange + (Orange, MTN) -> Orange sélectionné')

    def test_4_orange_and_mtn_gateways_orange_tx_picks_orange_new_engine(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=True):
            self._orange_and_mtn_gateways_orange_tx_picks_orange()

    def test_4_orange_and_mtn_gateways_orange_tx_picks_orange_legacy(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=False):
            self._orange_and_mtn_gateways_orange_tx_picks_orange()

    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def _orange_and_mtn_gateways_mtn_tx_picks_mtn(self, _redis_lock, create_payment):
        create_payment.return_value = _mocked_payment()
        orange_gw = self._gateway('Orange - gw1', 'gw-orange')
        self._sim(orange_gw, self.orange)
        mtn_gw = self._gateway('MTN - gw1', 'gw-mtn')
        self._sim(mtn_gw, self.mtn)
        tx = self._execute(self.mtn)
        self.assertEqual(tx.gateway_id, mtn_gw.id, 'Test 5 - MTN + (Orange, MTN) -> MTN sélectionné')

    def test_5_orange_and_mtn_gateways_mtn_tx_picks_mtn_new_engine(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=True):
            self._orange_and_mtn_gateways_mtn_tx_picks_mtn()

    def test_5_orange_and_mtn_gateways_mtn_tx_picks_mtn_legacy(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=False):
            self._orange_and_mtn_gateways_mtn_tx_picks_mtn()

    # ------------------------------------------------------------------
    # Test 6 - un Gateway avec deux SIM (Orange + MTN)
    # ------------------------------------------------------------------

    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def _dual_sim_gateway_uses_the_matching_sim_per_operator(self, _redis_lock, create_payment):
        create_payment.return_value = _mocked_payment()
        gw = self._gateway('Dual - gw1', 'gw-dual')
        orange_sim = self._sim(gw, self.orange, slot=0)
        mtn_sim = self._sim(gw, self.mtn, slot=1)

        orange_tx = self._execute(self.orange)
        self.assertEqual(orange_tx.gateway_id, gw.id)

        mtn_tx = self._execute(self.mtn)
        self.assertEqual(mtn_tx.gateway_id, gw.id)

        return orange_tx, orange_sim, mtn_tx, mtn_sim

    @override_settings(USE_NEW_TRANSACTION_ENGINE=True)
    def test_6_dual_sim_gateway_new_engine_uses_the_correct_sim_per_operator(self):
        orange_tx, orange_sim, mtn_tx, mtn_sim = self._dual_sim_gateway_uses_the_matching_sim_per_operator()
        # Only the new engine creates a TransactionAttempt with a specific SIM.
        self.assertEqual(orange_tx.attempts.get(attempt_number=1).gateway_sim_id, orange_sim.id)
        self.assertEqual(mtn_tx.attempts.get(attempt_number=1).gateway_sim_id, mtn_sim.id)

    @override_settings(USE_NEW_TRANSACTION_ENGINE=False)
    def test_6_dual_sim_gateway_legacy_assigns_the_gateway_for_both_operators(self):
        # Legacy never creates a TransactionAttempt/reservation - the
        # per-operator SIM-matching guarantee is on the Gateway assignment
        # itself (Test 6's core claim), not on a specific SIM row.
        self._dual_sim_gateway_uses_the_matching_sim_per_operator()

    # ------------------------------------------------------------------
    # Test 7 - aucun Gateway disponible du tout
    # ------------------------------------------------------------------

    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def _no_gateway_at_all_leaves_transaction_pending_no_wrong_assignment(self, _redis_lock, create_payment):
        create_payment.return_value = _mocked_payment()
        tx = self._execute(self.orange)
        self.assertIsNone(tx.gateway_id, 'Test 7 - aucun Gateway -> en attente, jamais un Gateway incorrect')
        self.assertEqual(tx.status, 'pending')
        self.assertIsNotNone(tx.next_retry_at)
        self.assertEqual(Gateway.objects.count(), 0, 'jamais de création automatique de Gateway')

    def test_7_no_gateway_at_all_new_engine(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=True):
            self._no_gateway_at_all_leaves_transaction_pending_no_wrong_assignment()

    def test_7_no_gateway_at_all_legacy(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=False):
            self._no_gateway_at_all_leaves_transaction_pending_no_wrong_assignment()

    # ------------------------------------------------------------------
    # Tests 8-9 - indisponibilité temporaire puis retour en ligne
    # ------------------------------------------------------------------

    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def _orange_offline_mtn_online_then_orange_recovers(self, _redis_lock, create_payment):
        create_payment.return_value = _mocked_payment()
        orange_gw = self._gateway('Orange - gw1', 'gw-orange', status='offline')
        orange_sim = self._sim(orange_gw, self.orange)
        mtn_gw = self._gateway('MTN - gw1', 'gw-mtn')
        self._sim(mtn_gw, self.mtn)

        tx = self._execute(self.orange)
        # Test 8
        self.assertIsNone(tx.gateway_id, 'Test 8 - Orange offline + MTN online -> Orange reste en attente')
        self.assertNotEqual(tx.gateway_id, mtn_gw.id)
        self.assertIsNotNone(tx.next_retry_at)

        # Orange revient en ligne.
        orange_gw.status = 'online'
        orange_gw.last_heartbeat = timezone.now()
        orange_gw.save(update_fields=['status', 'last_heartbeat'])
        tx.next_retry_at = timezone.now() - timedelta(seconds=1)
        tx.save(update_fields=['next_retry_at'])

        out = StringIO()
        call_command('dispatch_due_transaction_retries', stdout=out)

        tx.refresh_from_db()
        # Test 9
        self.assertEqual(tx.gateway_id, orange_gw.id, 'Test 9 - le retry récupère la transaction sur Orange')
        self.assertIsNone(tx.next_retry_at)
        return tx, orange_sim

    @override_settings(USE_NEW_TRANSACTION_ENGINE=True)
    def test_8_9_orange_offline_then_recovers_new_engine(self):
        tx, orange_sim = self._orange_offline_mtn_online_then_orange_recovers()
        self.assertEqual(tx.attempts.get(attempt_number=1).gateway_sim_id, orange_sim.id)

    @override_settings(USE_NEW_TRANSACTION_ENGINE=False)
    def test_8_9_orange_offline_then_recovers_legacy(self):
        self._orange_offline_mtn_online_then_orange_recovers()

    # ------------------------------------------------------------------
    # Test 10 - un retry ne peut sélectionner que le bon opérateur
    # ------------------------------------------------------------------

    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def _retry_of_an_orange_transaction_only_ever_considers_orange(self, _redis_lock, create_payment):
        create_payment.return_value = _mocked_payment()
        # No Orange Gateway exists yet - transaction queues.
        tx = self._execute(self.orange)
        self.assertIsNone(tx.gateway_id)

        # An MTN Gateway shows up while queued - a due retry must not touch it.
        mtn_gw = self._gateway('MTN - gw1', 'gw-mtn')
        self._sim(mtn_gw, self.mtn)
        tx.next_retry_at = timezone.now() - timedelta(seconds=1)
        tx.save(update_fields=['next_retry_at'])
        call_command('dispatch_due_transaction_retries', stdout=StringIO())
        tx.refresh_from_db()
        self.assertIsNone(tx.gateway_id, 'Test 10 - un retry Orange ne doit jamais choisir MTN, même seul disponible')
        self.assertIsNotNone(tx.next_retry_at, 'reste en attente - toujours pas de Gateway Orange')

        # Now a real Orange Gateway appears.
        orange_gw = self._gateway('Orange - gw1', 'gw-orange')
        self._sim(orange_gw, self.orange)
        tx.next_retry_at = timezone.now() - timedelta(seconds=1)
        tx.save(update_fields=['next_retry_at'])
        call_command('dispatch_due_transaction_retries', stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.gateway_id, orange_gw.id, "le retry choisit bien Orange dès qu'il existe")

    def test_10_retry_only_considers_matching_operator_new_engine(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=True):
            self._retry_of_an_orange_transaction_only_ever_considers_orange()

    def test_10_retry_only_considers_matching_operator_legacy(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=False):
            self._retry_of_an_orange_transaction_only_ever_considers_orange()

    # ------------------------------------------------------------------
    # Test 11 - deux Gateways concurrents, seul le bon peut revendiquer
    # ------------------------------------------------------------------

    @patch(_VERIFY_PAYMENT)
    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def _only_the_orange_gateway_can_claim_an_orange_transaction(self, _redis_lock, create_payment, verify_payment):
        from apps.payments.providers.base import PaymentStatusResult
        create_payment.return_value = _mocked_payment()
        orange_gw = self._gateway('Orange - gw1', 'gw-orange')
        self._sim(orange_gw, self.orange)
        mtn_gw = self._gateway('MTN - gw1', 'gw-mtn')
        self._sim(mtn_gw, self.mtn)

        tx = self._execute(self.orange)

        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        PaymentService.verify(tx.payment)

        mtn_pending = self._authenticated_pending(mtn_gw)
        self.assertEqual(mtn_pending.data, [], 'Test 11 - le Gateway MTN concurrent ne peut jamais revendiquer la tâche Orange')

        orange_pending = self._authenticated_pending(orange_gw)
        self.assertEqual(len(orange_pending.data), 1)
        self.assertEqual(orange_pending.data[0]['reference'], str(tx.reference))

    def test_11_only_matching_gateway_can_claim_new_engine(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=True):
            self._only_the_orange_gateway_can_claim_an_orange_transaction()

    def test_11_only_matching_gateway_can_claim_legacy(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=False):
            self._only_the_orange_gateway_can_claim_an_orange_transaction()

    # ------------------------------------------------------------------
    # Test 12 - PendingTransactionsView ne renvoie jamais une transaction
    # Orange à un Gateway MTN, même si un bug l'avait mal assignée.
    # ------------------------------------------------------------------

    def _pending_view_never_serves_a_mismatched_transaction_even_if_misassigned(self):
        """Defense-in-depth check: simulate a hypothetical bug that slipped a
        mismatched Gateway onto a Transaction directly (bypassing selection
        entirely) - the second barrier in PendingTransactionsView must still
        refuse to serve it. No payment/create_payment mocking needed - this
        Transaction is built directly via the ORM, never through
        /transactions/execute/."""
        mtn_gw = self._gateway('MTN - gw1', 'gw-mtn')
        self._sim(mtn_gw, self.mtn)
        device = Device.objects.create(uid='client-app-test', primary_phone='0700000001')
        payment = Payment.objects.create(method='jeko', reference='PAY-MISMATCH', amount=1000, status='accepted')
        mismatched_tx = Transaction.objects.create(
            device=device, service=self.internet, operator=self.orange,
            gateway=mtn_gw,  # deliberately mismatched, bypassing any selector
            phone_number='0700000001', amount=1000, status='pending',
            payment=payment, payment_method='jeko',
        )
        response = self._authenticated_pending(mtn_gw)
        self.assertEqual(response.status_code, 200)
        references = [item['reference'] for item in response.data]
        self.assertNotIn(
            str(mismatched_tx.reference), references,
            'Test 12 - la deuxième barrière doit refuser une transaction mal assignée, même directement en base',
        )

    def test_12_pending_view_second_barrier_new_engine(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=True):
            self._pending_view_never_serves_a_mismatched_transaction_even_if_misassigned()

    def test_12_pending_view_second_barrier_legacy(self):
        with override_settings(USE_NEW_TRANSACTION_ENGINE=False):
            self._pending_view_never_serves_a_mismatched_transaction_even_if_misassigned()

    # ------------------------------------------------------------------
    # Test 15 - l'ancien _select_gateway() ne peut plus être contourné,
    # puisqu'il n'existe plus du tout.
    # ------------------------------------------------------------------

    def test_15_the_old_naive_selector_no_longer_exists_at_all(self):
        import apps.devices.views as devices_views
        self.assertFalse(
            hasattr(devices_views, '_select_gateway'),
            'la fonction opérateur-aveugle a été supprimée, pas juste contournée',
        )

    @patch(_CREATE_PAYMENT)
    @patch(_REDIS_LOCK, return_value=nullcontext())
    def test_15_legacy_path_never_reaches_a_wrong_operator_even_with_many_gateways(self, _redis_lock, create_payment):
        """Belt-and-suspenders: several online Gateways of the WRONG operator
        plus none of the right one - if any code path still fell back to
        "any online gateway", this would catch it."""
        create_payment.return_value = _mocked_payment()
        for i in range(5):
            gw = self._gateway(f'MTN - gw{i}', f'gw-mtn-{i}')
            self._sim(gw, self.mtn)
        with override_settings(USE_NEW_TRANSACTION_ENGINE=False):
            tx = self._execute(self.orange)
        self.assertIsNone(tx.gateway_id)
        self.assertNotIn(tx.gateway_id, [g.id for g in Gateway.objects.all()])
