"""Unit tests for GatewayManager (B3) - exercised directly against the
service, not through the heartbeat view, per 'toute nouvelle fonctionnalité
doit être testable indépendamment'. View-level heartbeat behavior (including
backward compatibility) is covered in apps.devices.tests."""

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import Gateway, Operator, Transaction, Device, Service, TransactionAttempt
from apps.devices.models import GatewaySim
from apps.devices.services.gateway_manager import GatewayManager
from apps.devices.services.gateway_score import GatewayScoreService
from apps.devices.services.reservation_manager import ReservationManager
from apps.devices.services.scheduler import Scheduler

_GM_SETTINGS = {
    'LOW_BATTERY_THRESHOLD': 20, 'MAX_CONCURRENT_TASKS': 2, 'MAX_QUEUE': 20, 'HEARTBEAT_STALE_SECONDS': 90,
    'MAX_CONSECUTIVE_FAILURES': 5,
}
_TE_SETTINGS = {'MAX_RETRY': 3, 'TIMEOUT_SECONDS': 90, 'RETRY_BACKOFF': [30, 45, 60]}


class AvailableGatewaysTests(TestCase):
    def test_only_online_active_recently_seen_gateways_are_available(self):
        fresh = Gateway.objects.create(name='A', status='online', is_active=True, last_heartbeat=timezone.now())
        Gateway.objects.create(name='B', status='offline', is_active=True, last_heartbeat=timezone.now())
        Gateway.objects.create(name='C', status='online', is_active=False, last_heartbeat=timezone.now())
        stale = timezone.now() - timezone.timedelta(hours=1)
        Gateway.objects.create(name='D', status='online', is_active=True, last_heartbeat=stale)

        available = list(GatewayManager.available_gateways())
        self.assertEqual(available, [fresh])


class EligibleSimsTests(TestCase):
    """This is the exact contract the Scheduler (B4) will build on - see the
    Transaction Engine spec §3."""

    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')

    def _online_gateway(self, **kwargs):
        defaults = {'status': 'online', 'is_active': True, 'last_heartbeat': timezone.now()}
        defaults.update(kwargs)
        return Gateway.objects.create(name='GW', **defaults)

    def test_wrong_operator_is_excluded(self):
        gw = self._online_gateway()
        GatewaySim.objects.create(gateway=gw, operator=self.mtn)
        self.assertEqual(GatewayManager.eligible_sims(self.orange).count(), 0)

    def test_offline_gateway_is_excluded(self):
        gw = self._online_gateway(status='offline')
        GatewaySim.objects.create(gateway=gw, operator=self.orange)
        self.assertEqual(GatewayManager.eligible_sims(self.orange).count(), 0)

    def test_inactive_sim_is_excluded(self):
        gw = self._online_gateway()
        GatewaySim.objects.create(gateway=gw, operator=self.orange, is_active=False)
        self.assertEqual(GatewayManager.eligible_sims(self.orange).count(), 0)

    @override_settings(GATEWAY_MANAGER={
        'LOW_BATTERY_THRESHOLD': 20, 'MAX_CONCURRENT_TASKS': 2, 'MAX_QUEUE': 20, 'HEARTBEAT_STALE_SECONDS': 90,
    })
    def test_low_battery_gateway_is_excluded(self):
        gw = self._online_gateway(battery_level=5)
        GatewaySim.objects.create(gateway=gw, operator=self.orange)
        self.assertEqual(GatewayManager.eligible_sims(self.orange).count(), 0)

    @override_settings(GATEWAY_MANAGER={
        'LOW_BATTERY_THRESHOLD': 20, 'MAX_CONCURRENT_TASKS': 2, 'MAX_QUEUE': 20, 'HEARTBEAT_STALE_SECONDS': 90,
    })
    def test_unknown_battery_is_not_excluded(self):
        """An older mobile app build that has never reported battery must
        not be silently dropped from the whole pool - see B2's rollout note."""
        gw = self._online_gateway(battery_level=None)
        GatewaySim.objects.create(gateway=gw, operator=self.orange)
        self.assertEqual(GatewayManager.eligible_sims(self.orange).count(), 1)

    @override_settings(GATEWAY_MANAGER={
        'LOW_BATTERY_THRESHOLD': 20, 'MAX_CONCURRENT_TASKS': 2, 'MAX_QUEUE': 1, 'HEARTBEAT_STALE_SECONDS': 90,
    })
    def test_backlog_at_or_above_max_queue_is_excluded(self):
        gw = self._online_gateway()
        sim = GatewaySim.objects.create(gateway=gw, operator=self.orange)
        device = Device.objects.create(uid='client-app', primary_phone='0700000000')
        service = Service.objects.create(name='Internet', code='subscription')
        tx = Transaction.objects.create(device=device, service=service, operator=self.orange, phone_number='0700000000', amount=1000)
        TransactionAttempt.objects.create(transaction=tx, attempt_number=1, gateway_sim=sim, status='dispatched')

        self.assertEqual(GatewayManager.eligible_sims(self.orange).count(), 0)

    def test_excluded_sim_ids_are_honored(self):
        gw = self._online_gateway()
        sim = GatewaySim.objects.create(gateway=gw, operator=self.orange)
        self.assertEqual(GatewayManager.eligible_sims(self.orange, exclude_sim_ids=[sim.id]).count(), 0)


class PoolStatsAndGatewayStateTests(TestCase):
    def test_pool_stats_counts_online_and_offline(self):
        Gateway.objects.create(name='A', status='online', is_active=True, last_heartbeat=timezone.now())
        Gateway.objects.create(name='B', status='offline', is_active=True)
        stats = GatewayManager.pool_stats()
        self.assertEqual(stats['total_gateways'], 2)
        self.assertEqual(stats['online_gateways'], 1)
        self.assertEqual(stats['offline_gateways'], 1)

    def test_gateway_state_reports_sims_and_load(self):
        gw = Gateway.objects.create(name='A', status='online', is_active=True, last_heartbeat=timezone.now())
        orange = Operator.objects.create(name='Orange', code='orange')
        GatewaySim.objects.create(gateway=gw, operator=orange, slot=0)
        state = GatewayManager.gateway_state(gw)
        self.assertTrue(state['is_online'])
        self.assertEqual(state['in_flight'], 0)
        self.assertEqual(len(state['sims']), 1)
        self.assertEqual(state['sims'][0]['operator'], 'Orange')


class RecordAttemptOutcomeTests(TestCase):
    def setUp(self):
        gw = Gateway.objects.create(name='A', status='online', is_active=True)
        orange = Operator.objects.create(name='Orange', code='orange')
        self.sim = GatewaySim.objects.create(gateway=gw, operator=orange)

    def test_success_resets_consecutive_failures(self):
        self.sim.consecutive_failures = 3
        self.sim.save(update_fields=['consecutive_failures'])
        GatewayManager.record_attempt_outcome(self.sim, success=True)
        self.sim.refresh_from_db()
        self.assertEqual(self.sim.success_count, 1)
        self.assertEqual(self.sim.consecutive_failures, 0)

    def test_failure_increments_both_counters(self):
        GatewayManager.record_attempt_outcome(self.sim, success=False)
        GatewayManager.record_attempt_outcome(self.sim, success=False)
        self.sim.refresh_from_db()
        self.assertEqual(self.sim.failure_count, 2)
        self.assertEqual(self.sim.consecutive_failures, 2)


@override_settings(GATEWAY_MANAGER=_GM_SETTINGS)
class GatewayScoreServiceTests(TestCase):
    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self._now = timezone.now()

    def _sim(self, last_heartbeat=None, **gateway_kwargs):
        # Shared default timestamp (not a fresh timezone.now() per call): two
        # gateways created microseconds apart would otherwise never score
        # exactly equal on recency, which defeats any test that wants a
        # genuine tie (see test_repeated_calls_against_unchanged_data_agree).
        gw = Gateway.objects.create(
            name='GW', status='online', is_active=True,
            last_heartbeat=last_heartbeat or self._now, **gateway_kwargs,
        )
        return GatewaySim.objects.create(gateway=gw, operator=self.orange)

    def test_missing_data_scores_neutral_not_zero(self):
        sim = self._sim()  # no battery, no signal reported
        candidates = GatewayManager.eligible_sims(self.orange)
        annotated_sim = candidates.get(pk=sim.pk)
        score = GatewayScoreService.score(annotated_sim)
        self.assertGreater(score, 0.3)  # would be near 0 if missing data was punished as worst-case

    def test_better_battery_scores_higher_all_else_equal(self):
        # both above LOW_BATTERY_THRESHOLD=20, or eligible_sims() would drop
        # the low one entirely - this test is about scoring, not eligibility
        low = self._sim(battery_level=25)
        high = self._sim(battery_level=95)
        candidates = {c.pk: c for c in GatewayManager.eligible_sims(self.orange)}
        self.assertGreater(
            GatewayScoreService.score(candidates[high.pk]),
            GatewayScoreService.score(candidates[low.pk]),
        )

    def test_rank_orders_best_first(self):
        worse = self._sim(battery_level=25, signal_strength=-110)
        better = self._sim(battery_level=100, signal_strength=-55)
        ranked = GatewayScoreService.rank(GatewayManager.eligible_sims(self.orange))
        self.assertEqual([sim.pk for sim in ranked], [better.pk, worse.pk])

    def test_fewer_consecutive_failures_scores_higher(self):
        reliable = self._sim()
        flaky = self._sim()
        flaky.consecutive_failures = 4
        flaky.save(update_fields=['consecutive_failures'])
        candidates = {c.pk: c for c in GatewayManager.eligible_sims(self.orange)}
        self.assertGreater(
            GatewayScoreService.score(candidates[reliable.pk]),
            GatewayScoreService.score(candidates[flaky.pk]),
        )

    def test_repeated_calls_against_unchanged_data_agree(self):
        """Regression test: eligible_sims() previously had no base ordering
        at all, so a tie in GatewayScoreService's score resolved to whatever
        arbitrary row order the database happened to return - irreproducible
        from one call to the next. It is now always ordered by
        (last_used_at, pk), so repeated calls against the same data always
        agree with each other, regardless of which candidate wins. Both
        SIMs share self._now as their gateway's last_heartbeat (see _sim()),
        or the recency component alone would break the tie non-deterministically."""
        self._sim()
        self._sim()  # a second, equally-scored (all fields unset) candidate
        ranked_once = [s.pk for s in GatewayScoreService.rank(GatewayManager.eligible_sims(self.orange))]
        ranked_again = [s.pk for s in GatewayScoreService.rank(GatewayManager.eligible_sims(self.orange))]
        self.assertEqual(ranked_once, ranked_again)

    def test_least_recently_used_sim_wins_a_tie(self):
        """Pins down the actual tiebreak rule with unambiguous input
        (explicit, distinct GatewaySim.last_used_at values, same
        gateway.last_heartbeat for both so recency doesn't also move)."""
        older = self._sim()
        newer = self._sim()
        GatewaySim.objects.filter(pk=older.pk).update(last_used_at=self._now - timezone.timedelta(hours=1))
        GatewaySim.objects.filter(pk=newer.pk).update(last_used_at=self._now)

        ranked = GatewayScoreService.rank(GatewayManager.eligible_sims(self.orange))
        self.assertEqual([s.pk for s in ranked], [older.pk, newer.pk])


@override_settings(GATEWAY_MANAGER=_GM_SETTINGS, TRANSACTION_ENGINE=_TE_SETTINGS)
class ReservationManagerTests(TestCase):
    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.gateway = Gateway.objects.create(
            name='GW', status='online', is_active=True, last_heartbeat=timezone.now(), max_concurrent_tasks=1,
        )
        self.sim = GatewaySim.objects.create(gateway=self.gateway, operator=self.orange)
        device = Device.objects.create(uid='client-app', primary_phone='0700000000')
        service = Service.objects.create(name='Internet', code='subscription')
        self.tx = Transaction.objects.create(
            device=device, service=service, operator=self.orange, phone_number='0700000000', amount=1000,
        )

    def test_reserve_creates_an_assigned_attempt(self):
        attempt = ReservationManager.reserve(self.tx, self.sim)
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.status, 'assigned')
        self.assertEqual(attempt.gateway_sim_id, self.sim.pk)
        self.assertEqual(attempt.attempt_number, 1)

    def test_reserve_refuses_an_inactive_sim(self):
        self.sim.is_active = False
        self.sim.save(update_fields=['is_active'])
        self.assertIsNone(ReservationManager.reserve(self.tx, self.sim))

    def test_reserve_refuses_when_gateway_is_at_capacity(self):
        ReservationManager.reserve(self.tx, self.sim)  # fills the gateway's max_concurrent_tasks=1
        second_tx = Transaction.objects.create(
            device=self.tx.device, service=self.tx.service, operator=self.orange,
            phone_number='0700000001', amount=500,
        )
        self.assertIsNone(ReservationManager.reserve(second_tx, self.sim))

    def test_release_marks_terminal_status_and_updates_sim_counters(self):
        attempt = ReservationManager.reserve(self.tx, self.sim)
        ReservationManager.release(attempt, 'success')
        attempt.refresh_from_db()
        self.sim.refresh_from_db()
        self.assertEqual(attempt.status, 'success')
        self.assertIsNotNone(attempt.completed_at)
        self.assertEqual(self.sim.success_count, 1)

    def test_release_expired_frees_up_capacity(self):
        attempt = ReservationManager.reserve(self.tx, self.sim)
        TransactionAttempt.objects.filter(pk=attempt.pk).update(
            created_at=timezone.now() - timezone.timedelta(seconds=200),  # older than TIMEOUT_SECONDS=90
        )
        released = ReservationManager.release_expired()
        self.assertEqual(released, 1)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'expired')
        # capacity is free again
        self.assertIsNotNone(ReservationManager.reserve(self.tx, self.sim))


@override_settings(GATEWAY_MANAGER=_GM_SETTINGS, TRANSACTION_ENGINE=_TE_SETTINGS)
class SchedulerTests(TestCase):
    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')
        device = Device.objects.create(uid='client-app', primary_phone='0700000000')
        service = Service.objects.create(name='Internet', code='subscription')
        self.tx = Transaction.objects.create(
            device=device, service=service, operator=self.orange, phone_number='0700000000', amount=1000,
        )

    def _sim(self, operator, **gateway_kwargs):
        gw = Gateway.objects.create(name='GW', status='online', is_active=True, last_heartbeat=timezone.now(), **gateway_kwargs)
        return GatewaySim.objects.create(gateway=gw, operator=operator)

    def test_select_returns_none_when_nothing_is_eligible(self):
        self._sim(self.mtn)  # wrong operator for self.tx
        self.assertIsNone(Scheduler.select(self.tx, self.orange))

    def test_select_reserves_the_highest_scored_candidate(self):
        worse = self._sim(self.orange, battery_level=5)
        better = self._sim(self.orange, battery_level=100)
        attempt = Scheduler.select(self.tx, self.orange)
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.gateway_sim_id, better.pk)

    def test_select_excludes_sims_already_tried_for_this_transaction(self):
        only_sim = self._sim(self.orange)
        first_attempt = Scheduler.select(self.tx, self.orange)
        self.assertEqual(first_attempt.gateway_sim_id, only_sim.pk)

        # simulate a failed first attempt and a retry: the only SIM was
        # already tried for this transaction, so no second reservation exists
        ReservationManager.release(first_attempt, 'failed')
        self.assertIsNone(Scheduler.select(self.tx, self.orange))

    def test_select_falls_back_to_a_different_sim_on_retry(self):
        first_sim = self._sim(self.orange)
        second_sim = self._sim(self.orange)
        first_attempt = Scheduler.select(self.tx, self.orange)
        self.assertIsNotNone(first_attempt)
        tried_sim_id = first_attempt.gateway_sim_id
        remaining_sim_id = second_sim.pk if tried_sim_id == first_sim.pk else first_sim.pk

        ReservationManager.release(first_attempt, 'failed')
        second_attempt = Scheduler.select(self.tx, self.orange)
        self.assertIsNotNone(second_attempt)
        self.assertEqual(second_attempt.gateway_sim_id, remaining_sim_id)
        self.assertNotEqual(second_attempt.gateway_sim_id, tried_sim_id)
