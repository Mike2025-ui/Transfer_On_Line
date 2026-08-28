"""Business-model audit, Phase 7.3 - real PostgreSQL concurrency proof for
the assigned -> dispatched claim in PendingTransactionsView.

IMPORTANT ARCHITECTURAL NUANCE (found during this audit, reported precisely
rather than glossed over): PendingTransactionsView does not implement a
shared job-pool where several eligible Gateways race to "claim" an
unclaimed task. Transaction.gateway is already fixed at Scheduler/
ReservationManager time (creation, or a later retry) - the view's query is
scoped by `gateway_id=<authenticated Gateway>.id`. So two *different*
Gateways (even same operator, even both genuinely online and eligible) can
never both see the same Transaction at all: their WHERE clauses target
different gateway_id values. That part of "two Gateways never both get the
same task" is not a live MVCC race - it is a deterministic consequence of
who initially got reserved. This suite proves it anyway, repeatedly, under
real concurrency, since it is exactly what the brief describes as the
"Gateway A / Gateway B" scenario and it deserves an empirical answer, not
just an assurance.

The genuine race - the one the `assigned -> dispatched` conditional UPDATE
(`apps/devices/views.py::PendingTransactionsView.get()`) actually exists to
arbitrate - is TWO CONCURRENT CONNECTIONS AUTHENTICATED AS THE SAME GATEWAY
polling while the attempt is still 'assigned' (a cloned/shared secret used
on two devices, or two near-simultaneous ticks from the same phone hitting
two different backend workers). That is the scenario stress-tested with
real repetition here (test_same_gateway_identity_*).

Real PostgreSQL (confirmed: this project's DATABASE_URL points at a real
Postgres instance, never SQLite - see settings.py/.env), real OS threads,
real separate connections per thread (`connections.close_all()` in each
worker's `finally`, TransactionTestCase not TestCase) - same pattern this
codebase already validated for the idempotency-key race in
tests_idempotency.py::ConcurrentIdempotentRequestTests. A plain TestCase
wraps the whole test body in one uncommitted transaction a second thread's
own connection would never see."""

import threading
import uuid
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.db import connections
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Device, Gateway, Operator, Payment, Service, Transaction, TransactionAttempt, UssdCode
from apps.devices.models import GatewaySim


class _ConcurrentPendingPollMixin:

    def _poll_concurrently(self, secrets):
        """Launches one real thread per secret, all released at the same
        instant via a Barrier, each with its own APIClient/DB connection.
        Returns the HTTP responses in the same order as `secrets`."""
        n = len(secrets)
        barrier = threading.Barrier(n)
        results = [None] * n
        errors = [None] * n

        def worker(index):
            try:
                barrier.wait(timeout=5)
                client = APIClient()
                client.credentials(HTTP_X_GATEWAY_SECRET=secrets[index])
                results[index] = client.get(reverse('api_transaction_pending'))
            except Exception as exc:  # surfaced in the main thread below
                errors[index] = exc
            finally:
                # This thread never goes through Django's request/response
                # cycle machinery that normally closes connections - without
                # this, the connection stays attached to the test database
                # and teardown fails with "database is being accessed by
                # other users".
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        for exc in errors:
            if exc is not None:
                raise exc
        return results

    @staticmethod
    def _has_reference(response, reference):
        return any(item.get('reference') == reference for item in response.data)


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
class DoubleDispatchConcurrencyTests(_ConcurrentPendingPollMixin, TransactionTestCase):

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

        self.gw_a = Gateway.objects.create(
            name='Orange - gwA', host='gw-a', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        self.sim_a = GatewaySim.objects.create(gateway=self.gw_a, operator=self.orange, slot=0, is_active=True)
        self.secret_a = self.gw_a.generate_secret()

        self.gw_b = Gateway.objects.create(
            name='Orange - gwB', host='gw-b', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        self.sim_b = GatewaySim.objects.create(gateway=self.gw_b, operator=self.orange, slot=0, is_active=True)
        self.secret_b = self.gw_b.generate_secret()

        self.mtn_gw = Gateway.objects.create(
            name='MTN - gw1', host='gw-mtn', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        self.mtn_sim = GatewaySim.objects.create(gateway=self.mtn_gw, operator=self.mtn, slot=0, is_active=True)
        self.mtn_secret = self.mtn_gw.generate_secret()

    def _make_transaction_with_assigned_attempt(self, operator, gateway, sim, amount=1000):
        device = Device.objects.create(uid=f'dev-{uuid.uuid4()}', primary_phone='0700000001')
        payment = Payment.objects.create(
            method='cinetpay', reference=f'PAY-{uuid.uuid4()}', amount=amount, status='accepted',
        )
        tx = Transaction.objects.create(
            device=device, service=self.internet, operator=operator, gateway=gateway,
            phone_number='0700000001', amount=amount, status='pending',
            payment=payment, payment_method='cinetpay',
        )
        attempt = TransactionAttempt.objects.create(
            transaction=tx, gateway_sim=sim, attempt_number=1, status='assigned',
        )
        return tx, attempt

    # ------------------------------------------------------------------
    # THE real race: same Gateway identity, two concurrent connections.
    # Sections 2, 4, 5 of the brief.
    # ------------------------------------------------------------------

    def test_same_gateway_identity_100_concurrent_polls_never_double_dispatch(self):
        races = 100
        left_wins = right_wins = double_dispatch = zero_result = 0
        for i in range(races):
            tx, attempt = self._make_transaction_with_assigned_attempt(self.orange, self.gw_a, self.sim_a)
            left, right = self._poll_concurrently([self.secret_a, self.secret_a])
            ref = str(tx.reference)
            left_has = self._has_reference(left, ref)
            right_has = self._has_reference(right, ref)
            if left_has and right_has:
                double_dispatch += 1
            elif left_has:
                left_wins += 1
            elif right_has:
                right_wins += 1
            else:
                zero_result += 1

            attempt.refresh_from_db()
            if not (left_has and right_has):
                self.assertEqual(
                    attempt.status, 'dispatched',
                    f'race {i}: attempt must be claimed (assigned -> dispatched) by whichever side won',
                )
                self.assertIsNotNone(attempt.dispatched_at)
            tx.delete()

        print(
            f'\n[Phase 7.3] same-identity race: {races} races - '
            f'left_wins={left_wins} right_wins={right_wins} '
            f'double_dispatch={double_dispatch} zero_result={zero_result}'
        )
        self.assertEqual(double_dispatch, 0, f'{double_dispatch}/{races} races produced a double dispatch')
        self.assertEqual(zero_result, 0, f'{zero_result}/{races} races produced neither side receiving the task')
        self.assertEqual(left_wins + right_wins, races)

    # ------------------------------------------------------------------
    # Structural check (not a true MVCC race - see module docstring):
    # two DIFFERENT Gateways, same operator. Sections 3, 6 of the brief.
    # ------------------------------------------------------------------

    def test_two_different_orange_gateways_owner_always_wins_other_always_zero(self):
        races = 100
        double_dispatch = owner_wins = other_zero = 0
        for i in range(races):
            tx, attempt = self._make_transaction_with_assigned_attempt(self.orange, self.gw_a, self.sim_a)
            owner_resp, other_resp = self._poll_concurrently([self.secret_a, self.secret_b])
            ref = str(tx.reference)
            owner_has = self._has_reference(owner_resp, ref)
            other_has = self._has_reference(other_resp, ref)
            if owner_has and other_has:
                double_dispatch += 1
            if owner_has:
                owner_wins += 1
            if not other_has:
                other_zero += 1
            tx.delete()

        print(
            f'\n[Phase 7.3] cross-gateway (same operator) race: {races} races - '
            f'owner_wins={owner_wins} other_zero={other_zero} double_dispatch={double_dispatch}'
        )
        self.assertEqual(double_dispatch, 0)
        self.assertEqual(owner_wins, races, 'le Gateway propriétaire doit toujours recevoir sa propre tâche')
        self.assertEqual(other_zero, races, "l'autre Gateway (même opérateur, non-propriétaire) ne doit jamais la recevoir")

    # ------------------------------------------------------------------
    # Section 7 - cross-operator, under real concurrency.
    # ------------------------------------------------------------------

    def test_cross_operator_race_mtn_never_receives_orange_transaction(self):
        races = 30
        for i in range(races):
            tx, attempt = self._make_transaction_with_assigned_attempt(self.orange, self.gw_a, self.sim_a)
            orange_resp, mtn_resp = self._poll_concurrently([self.secret_a, self.mtn_secret])
            ref = str(tx.reference)
            self.assertTrue(self._has_reference(orange_resp, ref), f'race {i}: Orange Gateway should receive its own task')
            self.assertFalse(self._has_reference(mtn_resp, ref), f'race {i}: MTN must never receive an Orange transaction')
            tx.delete()

    # ------------------------------------------------------------------
    # Section 8 - deux transactions, deux Gateways.
    # ------------------------------------------------------------------

    def test_two_transactions_two_gateways_no_transaction_served_to_the_wrong_side(self):
        races = 50
        for i in range(races):
            tx_x, _ = self._make_transaction_with_assigned_attempt(self.orange, self.gw_a, self.sim_a)
            tx_y, _ = self._make_transaction_with_assigned_attempt(self.orange, self.gw_b, self.sim_b)
            resp_a, resp_b = self._poll_concurrently([self.secret_a, self.secret_b])
            refs_a = {item['reference'] for item in resp_a.data}
            refs_b = {item['reference'] for item in resp_b.data}
            self.assertEqual(refs_a & refs_b, set(), f'race {i}: no reference must ever appear in both responses')
            self.assertEqual(refs_a, {str(tx_x.reference)}, f'race {i}: Gateway A must only ever see X')
            self.assertEqual(refs_b, {str(tx_y.reference)}, f'race {i}: Gateway B must only ever see Y')
            tx_x.delete()
            tx_y.delete()

    # ------------------------------------------------------------------
    # Section 9 - plusieurs transactions, plusieurs Gateways.
    # ------------------------------------------------------------------

    def test_ten_transactions_three_gateways_each_attempt_dispatched_at_most_once(self):
        gw_c = Gateway.objects.create(
            name='Orange - gwC', host='gw-c', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        sim_c = GatewaySim.objects.create(gateway=gw_c, operator=self.orange, slot=0, is_active=True)
        secret_c = gw_c.generate_secret()
        owners = [(self.gw_a, self.sim_a, self.secret_a), (self.gw_b, self.sim_b, self.secret_b), (gw_c, sim_c, secret_c)]

        rounds = 20
        for r in range(rounds):
            txs = []
            for i in range(10):
                owner_gw, owner_sim, _ = owners[i % 3]
                tx, attempt = self._make_transaction_with_assigned_attempt(self.orange, owner_gw, owner_sim)
                txs.append((tx, attempt))

            responses = self._poll_concurrently([self.secret_a, self.secret_b, secret_c])

            seen = {}
            for resp in responses:
                for item in resp.data:
                    seen[item['reference']] = seen.get(item['reference'], 0) + 1
            for ref, count in seen.items():
                self.assertLessEqual(count, 1, f'round {r}: {ref} appeared {count} times across combined responses')

            for tx, attempt in txs:
                attempt.refresh_from_db()
                self.assertEqual(attempt.status, 'dispatched', f'round {r}: {tx.reference} attempt never claimed')
                tx.delete()

    # ------------------------------------------------------------------
    # Section 10 - même Gateway, polls séquentiels rapides.
    # ------------------------------------------------------------------

    def test_same_gateway_repeated_sequential_polls_never_return_a_claimed_attempt_twice(self):
        tx, attempt = self._make_transaction_with_assigned_attempt(self.orange, self.gw_a, self.sim_a)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret_a)
        ref = str(tx.reference)

        first = self.client.get(reverse('api_transaction_pending'))
        second = self.client.get(reverse('api_transaction_pending'))
        third = self.client.get(reverse('api_transaction_pending'))

        self.assertTrue(self._has_reference(first, ref))
        self.assertFalse(self._has_reference(second, ref))
        self.assertFalse(self._has_reference(third, ref))

    # ------------------------------------------------------------------
    # Section 11 - dispatched puis executing bloquent tous les deux.
    # ------------------------------------------------------------------

    def test_dispatched_and_executing_attempts_are_both_excluded_from_pending(self):
        tx, attempt = self._make_transaction_with_assigned_attempt(self.orange, self.gw_a, self.sim_a)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret_a)
        ref = str(tx.reference)

        first = self.client.get(reverse('api_transaction_pending'))
        self.assertTrue(self._has_reference(first, ref))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'dispatched')

        after_dispatch = self.client.get(reverse('api_transaction_pending'))
        self.assertFalse(self._has_reference(after_dispatch, ref))

        attempt.status = 'executing'
        attempt.save(update_fields=['status'])
        after_executing = self.client.get(reverse('api_transaction_pending'))
        self.assertFalse(self._has_reference(after_executing, ref))

    # ------------------------------------------------------------------
    # Section 12 - après succès.
    # ------------------------------------------------------------------

    def test_after_success_transaction_never_reappears_in_pending(self):
        tx, attempt = self._make_transaction_with_assigned_attempt(self.orange, self.gw_a, self.sim_a)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret_a)
        ref = str(tx.reference)

        self.client.get(reverse('api_transaction_pending'))  # claims it
        result = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': ref, 'success': True, 'result': 'OK'},
            format='json',
        )
        self.assertEqual(result.status_code, 200)

        after = self.client.get(reverse('api_transaction_pending'))
        self.assertFalse(self._has_reference(after, ref))
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success')

    # ------------------------------------------------------------------
    # Sections 13 & 14 - après échec réseau, retry, puis concurrence sur
    # la NOUVELLE tentative (l'ancienne ne doit jamais revenir).
    # ------------------------------------------------------------------

    def test_after_network_failure_retry_dispatches_the_new_attempt_at_most_once(self):
        tx, attempt1 = self._make_transaction_with_assigned_attempt(self.orange, self.gw_a, self.sim_a)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.secret_a)
        ref = str(tx.reference)

        self.client.get(reverse('api_transaction_pending'))  # claims attempt #1
        result = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': ref, 'success': False, 'result': 'network error'},
            format='json',
        )
        self.assertEqual(result.status_code, 200)
        attempt1.refresh_from_db()
        self.assertEqual(attempt1.status, 'failed')
        tx.refresh_from_db()
        self.assertIsNotNone(tx.next_retry_at, 'network_error must schedule a retry')

        tx.next_retry_at = timezone.now() - timedelta(seconds=1)
        tx.save(update_fields=['next_retry_at'])
        call_command('dispatch_due_transaction_retries', stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.attempts.count(), 2)
        attempt2 = tx.attempts.get(attempt_number=2)
        self.assertEqual(attempt2.status, 'assigned')
        self.assertNotEqual(attempt2.gateway_sim_id, attempt1.gateway_sim_id, 'la SIM déjà tentée doit être exclue')

        # Concurrence réelle sur la nouvelle tentative, avec l'identité du
        # NOUVEAU Gateway propriétaire (peut différer de gw_a - sim_a est exclue).
        new_secret = tx.gateway.generate_secret()
        left, right = self._poll_concurrently([new_secret, new_secret])
        left_has = self._has_reference(left, ref)
        right_has = self._has_reference(right, ref)

        self.assertFalse(left_has and right_has, 'attempt #2 must never be dispatched to both concurrent pollers')
        self.assertTrue(left_has or right_has, 'attempt #2 must be dispatched to exactly one poller')

        attempt2.refresh_from_db()
        self.assertEqual(attempt2.status, 'dispatched')
        attempt1.refresh_from_db()
        self.assertEqual(attempt1.status, 'failed', "l'ancienne attempt #1 ne doit jamais redevenir active ni être renvoyée")


@override_settings(USE_NEW_TRANSACTION_ENGINE=False)
class LegacyEngineConcurrencyTests(_ConcurrentPendingPollMixin, TransactionTestCase):
    """Section 15 of the brief: USE_NEW_TRANSACTION_ENGINE=false. No
    TransactionAttempt/claim exists at all here (business-model audit
    Phase 7.2 - the legacy path never creates one) - so there is no
    assigned -> dispatched race to stress-test. The relevant safety property
    is purely the gateway_id + operator/SIM filter holding under real
    concurrency, which this repeats explicitly under the legacy flag."""

    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Orange défaut',
            template='*456*{montant}#', is_active=True, is_default=True,
        )
        self.gw_a = Gateway.objects.create(
            name='Orange - gwA', host='gw-a', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        GatewaySim.objects.create(gateway=self.gw_a, operator=self.orange, slot=0, is_active=True)
        self.secret_a = self.gw_a.generate_secret()

        self.gw_b = Gateway.objects.create(
            name='Orange - gwB', host='gw-b', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        GatewaySim.objects.create(gateway=self.gw_b, operator=self.orange, slot=0, is_active=True)
        self.secret_b = self.gw_b.generate_secret()

        self.mtn_gw = Gateway.objects.create(
            name='MTN - gw1', host='gw-mtn', status='online', is_active=True, last_heartbeat=timezone.now(),
        )
        GatewaySim.objects.create(gateway=self.mtn_gw, operator=self.mtn, slot=0, is_active=True)
        self.mtn_secret = self.mtn_gw.generate_secret()

    def _make_legacy_transaction(self, operator, gateway, amount=1000):
        device = Device.objects.create(uid=f'dev-{uuid.uuid4()}', primary_phone='0700000001')
        payment = Payment.objects.create(
            method='cinetpay', reference=f'PAY-{uuid.uuid4()}', amount=amount, status='accepted',
        )
        return Transaction.objects.create(
            device=device, service=self.internet, operator=operator, gateway=gateway,
            phone_number='0700000001', amount=amount, status='pending',
            payment=payment, payment_method='cinetpay',
        )

    def test_legacy_cross_operator_and_wrong_gateway_never_receive_transaction_under_concurrency(self):
        races = 50
        for i in range(races):
            tx = self._make_legacy_transaction(self.orange, self.gw_a)
            responses = self._poll_concurrently([self.secret_a, self.secret_b, self.mtn_secret])
            ref = str(tx.reference)
            has = [self._has_reference(r, ref) for r in responses]
            self.assertEqual(has, [True, False, False], f'race {i}: only the owning Gateway (index 0) may ever receive it')
            tx.delete()

    def test_legacy_same_gateway_identity_concurrent_polls_both_see_it_no_claim_mechanism(self):
        """Documented, not a bug: legacy transactions have no TransactionAttempt
        to claim, so - unlike the new engine - the SAME still-pending
        transaction is expected to reappear on every poll from its owning
        Gateway until a result is posted. This is pre-existing, unchanged
        behavior (Phase 7 audit already noted it), verified here so it is
        never silently assumed to behave like the new engine's claim."""
        tx = self._make_legacy_transaction(self.orange, self.gw_a)
        left, right = self._poll_concurrently([self.secret_a, self.secret_a])
        ref = str(tx.reference)
        self.assertTrue(self._has_reference(left, ref))
        self.assertTrue(self._has_reference(right, ref))
