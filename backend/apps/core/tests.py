import importlib
import os
from unittest.mock import patch

from django.db import IntegrityError, transaction as db_transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.locks import redis_lock
from apps.core.models import (
    Device, Gateway, Operator, Payment, Refund, Service, Transaction, TransactionAttempt, TransactionEvent,
    UssdCode, UssdCodeNotConfigured, UssdCodeRenderError,
)
from apps.core.serializers import build_ussd_code, gateway_task_payload, resolve_ussd_code, transaction_payload
from apps.core.services.retry_manager import NON_RETRYABLE_FAILURE_REASONS, RetryManager
from apps.core.services.transaction_state_machine import InvalidTransitionError, TransactionStateMachine
from apps.devices.models import GatewaySim


class AllowedHostsSettingsTests(TestCase):
    def test_blank_django_allowed_hosts_keeps_localhost_access(self):
        import transfer_on_line.settings as settings_module

        with patch.dict(os.environ, {'DJANGO_ALLOWED_HOSTS': ''}, clear=False):
            reloaded = importlib.reload(settings_module)
            self.assertIn('127.0.0.1', reloaded.ALLOWED_HOSTS)
            self.assertIn('localhost', reloaded.ALLOWED_HOSTS)

        importlib.reload(settings_module)


class GatewayB1FieldsTests(TestCase):
    """B1 - Gateway.max_concurrent_tasks/battery_level are plain new fields,
    not yet read by any service (that's B3/B4) - tested at the model level
    only, per the 'no business logic in B1' constraint."""

    def test_max_concurrent_tasks_defaults_from_settings(self):
        with override_settings(GATEWAY_MANAGER={'MAX_CONCURRENT_TASKS': 7}):
            gateway = Gateway.objects.create(name='Orange - 0700000000')
        self.assertEqual(gateway.max_concurrent_tasks, 7)

    def test_battery_level_is_optional(self):
        gateway = Gateway.objects.create(name='Orange - 0700000000')
        self.assertIsNone(gateway.battery_level)


class TransactionAttemptModelTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(uid='client-app', primary_phone='0700000001')
        self.service = Service.objects.create(name='Internet', code='subscription')
        self.operator = Operator.objects.create(name='Orange', code='orange')
        self.tx = Transaction.objects.create(
            device=self.device, service=self.service, operator=self.operator,
            phone_number='0700000001', amount=1000,
        )

    def test_defaults(self):
        attempt = TransactionAttempt.objects.create(transaction=self.tx, attempt_number=1)
        self.assertEqual(attempt.status, 'assigned')
        self.assertEqual(attempt.gateway_sim, None)
        self.assertEqual(list(self.tx.attempts.all()), [attempt])

    def test_a_transaction_cannot_have_two_attempts_with_the_same_number(self):
        TransactionAttempt.objects.create(transaction=self.tx, attempt_number=1)
        with self.assertRaises(IntegrityError), db_transaction.atomic():
            TransactionAttempt.objects.create(transaction=self.tx, attempt_number=1)

    def test_deleting_gateway_sim_keeps_the_attempt_for_audit(self):
        from apps.devices.models import GatewaySim
        gateway = Gateway.objects.create(name='Orange - 0700000000')
        sim = GatewaySim.objects.create(gateway=gateway, operator=self.operator)
        attempt = TransactionAttempt.objects.create(transaction=self.tx, attempt_number=1, gateway_sim=sim)
        sim.delete()
        attempt.refresh_from_db()
        self.assertIsNone(attempt.gateway_sim)  # SET_NULL: the attempt row survives as an audit trail


class RefundB1FieldsTests(TestCase):
    def test_new_fields_are_optional_and_do_not_break_existing_refund_creation(self):
        device = Device.objects.create(uid='client-app', primary_phone='0700000001')
        service = Service.objects.create(name='Internet', code='subscription')
        operator = Operator.objects.create(name='Orange', code='orange')
        tx = Transaction.objects.create(
            device=device, service=service, operator=operator, phone_number='0700000001', amount=1000,
        )
        refund = Refund.objects.create(transaction=tx, reason='USSD failed')
        self.assertEqual(refund.method, '')
        self.assertIsNone(refund.processed_by)
        self.assertIsNone(refund.processed_at)


@patch('apps.core.views.check_redis', return_value='ok')
@patch('apps.core.views.check_provider_reachable', return_value='ok')
class HealthEndpointTests(TestCase):
    """check_redis / check_provider_reachable are mocked at the class level
    everywhere except where a test is specifically about their failure mode -
    a health check test suite must never depend on real network/Redis
    reachability to run fast and deterministically in CI."""

    def test_liveness_is_always_ok_and_never_touches_the_database(self, _provider, _redis):
        with patch('apps.core.views.check_database') as mocked_db:
            response = self.client.get(reverse('api_health_live'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        mocked_db.assert_not_called()

    def test_readiness_is_ok_when_database_is_up(self, _provider, _redis):
        response = self.client.get(reverse('api_health_ready'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['database'], 'ok')

    @patch('apps.core.views.check_database', return_value='down')
    def test_readiness_returns_503_when_database_is_down(self, _mocked_db, _provider, _redis):
        response = self.client.get(reverse('api_health_ready'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['status'], 'unavailable')

    def test_health_stays_ok_even_when_both_payment_providers_are_down(self, mocked_provider, _redis):
        """A provider outage must never take the whole service out of a load
        balancer's rotation - only the database gates overall status."""
        mocked_provider.return_value = 'down'
        response = self.client.get(reverse('api_health'))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['geniuspay'], 'down')
        self.assertEqual(body['jeko'], 'down')

    @patch('apps.core.views.check_database', return_value='down')
    def test_health_reports_degraded_when_database_is_down(self, _mocked_db, _provider, _redis):
        response = self.client.get(reverse('api_health'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['status'], 'degraded')

    def test_readiness_reports_but_does_not_fail_on_redis_down(self, _provider, mocked_redis):
        mocked_redis.return_value = 'down'
        response = self.client.get(reverse('api_health_ready'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redis'], 'down')


def _make_transaction(status='pending'):
    device = Device.objects.create(uid='client-app', primary_phone='0700000000')
    service = Service.objects.create(name='Internet', code='subscription')
    operator = Operator.objects.create(name='Orange', code='orange')
    return Transaction.objects.create(
        device=device, service=service, operator=operator,
        phone_number='0700000000', amount=1000, status=status,
    )


class TransactionStateMachineTests(TestCase):
    def test_allowed_transition_updates_status_and_logs_an_event(self):
        tx = _make_transaction('pending')
        TransactionStateMachine.transition(tx, 'success', reason='ussd_result_reported')
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success')

        event = TransactionEvent.objects.get(transaction=tx)
        self.assertEqual(event.event_type, 'status_changed')
        self.assertEqual(event.metadata['from_status'], 'pending')
        self.assertEqual(event.metadata['to_status'], 'success')
        self.assertEqual(event.metadata['reason'], 'ussd_result_reported')

    def test_reflexive_transition_is_allowed_and_still_logged(self):
        """sync_from_payment() re-affirms 'pending' every time it runs even
        when nothing actually changed - must not raise."""
        tx = _make_transaction('pending')
        TransactionStateMachine.transition(tx, 'pending', reason='payment_status_synced')
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'pending')
        self.assertEqual(TransactionEvent.objects.filter(transaction=tx).count(), 1)

    def test_transition_from_a_terminal_status_is_rejected(self):
        tx = _make_transaction('success')
        with self.assertRaises(InvalidTransitionError):
            TransactionStateMachine.transition(tx, 'failed')
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success', 'a rejected transition must not partially apply')

    def test_invalid_transition_does_not_create_an_event(self):
        tx = _make_transaction('cancelled')
        with self.assertRaises(InvalidTransitionError):
            TransactionStateMachine.transition(tx, 'pending')
        self.assertEqual(TransactionEvent.objects.filter(transaction=tx).count(), 0)

    def test_pending_to_processing_to_success_is_allowed(self):
        tx = _make_transaction('pending')
        TransactionStateMachine.transition(tx, 'processing')
        TransactionStateMachine.transition(tx, 'success')
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success')


class TransactionSyncFromPaymentTests(TestCase):
    """Phase D audit (Critique n°1): an accepted payment must never leave the
    transaction permanently stuck in the terminal 'failed' status just
    because no Gateway was assigned yet - see Transaction.sync_from_payment()."""

    def _accepted_payment(self):
        return Payment.objects.create(method='jeko', reference='PAY-1', amount=1000, status='accepted')

    def test_accepted_payment_with_no_gateway_stays_pending_not_failed(self):
        tx = _make_transaction('pending')
        tx.payment = self._accepted_payment()
        tx.save(update_fields=['payment'])
        self.assertIsNone(tx.gateway)

        tx.sync_from_payment()

        tx.refresh_from_db()
        self.assertEqual(tx.status, 'pending', 'an accepted payment must never resolve to a terminal failed status')

    def test_accepted_payment_with_a_gateway_stays_pending(self):
        tx = _make_transaction('pending')
        tx.gateway = Gateway.objects.create(name='GW1', status='online')
        tx.payment = self._accepted_payment()
        tx.save(update_fields=['gateway', 'payment'])

        tx.sync_from_payment()

        tx.refresh_from_db()
        self.assertEqual(tx.status, 'pending')

    def test_non_accepted_payment_still_fails_the_transaction(self):
        tx = _make_transaction('pending')
        tx.payment = Payment.objects.create(method='jeko', reference='PAY-2', amount=1000, status='refused')
        tx.save(update_fields=['payment'])

        tx.sync_from_payment()

        tx.refresh_from_db()
        self.assertEqual(tx.status, 'failed')


class TransactionEventTests(TestCase):
    def test_log_stores_arbitrary_metadata(self):
        tx = _make_transaction()
        TransactionEvent.log(tx, 'custom_event', foo='bar', count=3)
        event = TransactionEvent.objects.get(transaction=tx, event_type='custom_event')
        self.assertEqual(event.metadata, {'foo': 'bar', 'count': 3})

    def test_events_are_ordered_chronologically(self):
        tx = _make_transaction()
        TransactionEvent.log(tx, 'first')
        TransactionEvent.log(tx, 'second')
        self.assertEqual([e.event_type for e in tx.events.all()], ['first', 'second'])


_TE_SETTINGS = {'MAX_RETRY': 3, 'TIMEOUT_SECONDS': 90, 'RETRY_BACKOFF': [30, 45, 60]}


@override_settings(TRANSACTION_ENGINE=_TE_SETTINGS, USE_NEW_TRANSACTION_ENGINE=True)
class RetryManagerTests(TestCase):
    """USE_NEW_TRANSACTION_ENGINE=True pinned explicitly (business-model audit
    Phase 7.2): dispatch_due_retries() now branches on this flag - these
    tests are specifically about the Scheduler.select()-based branch (SIM
    exclusion, TransactionAttempt creation), which only exists on that side,
    so relying on the ambient/.env value would make them environment-
    dependent instead of deterministic."""
    def _attempt(self, tx, number, failure_reason='network_error'):
        return TransactionAttempt.objects.create(
            transaction=tx, attempt_number=number, status='failed', failure_reason=failure_reason,
        )

    def test_should_retry_true_below_max_retry(self):
        tx = _make_transaction()
        self._attempt(tx, 1)
        self.assertTrue(RetryManager.should_retry(tx, 'network_error'))

    def test_should_retry_false_at_max_retry(self):
        tx = _make_transaction()
        for i in range(1, 4):
            self._attempt(tx, i)
        self.assertFalse(RetryManager.should_retry(tx, 'network_error'))

    def test_should_retry_false_for_non_retryable_reason(self):
        tx = _make_transaction()
        self.assertIn('invalid_number', NON_RETRYABLE_FAILURE_REASONS)
        self.assertFalse(RetryManager.should_retry(tx, 'invalid_number'))

    def test_next_delay_seconds_follows_backoff_list_then_reuses_last(self):
        tx = _make_transaction()
        self._attempt(tx, 1)
        self.assertEqual(RetryManager.next_delay_seconds(tx), 30)
        self._attempt(tx, 2)
        self.assertEqual(RetryManager.next_delay_seconds(tx), 45)
        self._attempt(tx, 3)
        self.assertEqual(RetryManager.next_delay_seconds(tx), 60)
        self._attempt(tx, 4)
        self.assertEqual(RetryManager.next_delay_seconds(tx), 60, 'must reuse the last configured delay, not error')

    def test_handle_failed_attempt_schedules_next_retry_at(self):
        tx = _make_transaction()
        attempt = self._attempt(tx, 1)
        retry_at = RetryManager.handle_failed_attempt(tx, attempt)
        tx.refresh_from_db()
        self.assertIsNotNone(retry_at)
        self.assertEqual(tx.next_retry_at, retry_at)
        event = TransactionEvent.objects.get(transaction=tx, event_type='retry_scheduled')
        self.assertEqual(event.metadata['delay_seconds'], 30)

    def test_handle_failed_attempt_exhausted_clears_next_retry_at(self):
        tx = _make_transaction()
        for i in range(1, 4):
            attempt = self._attempt(tx, i)
        result = RetryManager.handle_failed_attempt(tx, attempt)
        tx.refresh_from_db()
        self.assertIsNone(result)
        self.assertIsNone(tx.next_retry_at)
        self.assertTrue(TransactionEvent.objects.filter(transaction=tx, event_type='retry_exhausted').exists())

    def test_dispatch_due_retries_uses_the_scheduler_and_excludes_tried_sims(self):
        tx = _make_transaction()
        gw1 = Gateway.objects.create(name='GW1', status='online', is_active=True, last_heartbeat=timezone.now())
        tried_sim = GatewaySim.objects.create(gateway=gw1, operator=tx.operator)
        gw2 = Gateway.objects.create(name='GW2', status='online', is_active=True, last_heartbeat=timezone.now())
        fresh_sim = GatewaySim.objects.create(gateway=gw2, operator=tx.operator)

        TransactionAttempt.objects.create(
            transaction=tx, attempt_number=1, gateway_sim=tried_sim,
            status='failed', failure_reason='network_error',
        )
        tx.next_retry_at = timezone.now() - timezone.timedelta(seconds=1)  # already due
        tx.save(update_fields=['next_retry_at'])

        results = RetryManager.dispatch_due_retries()
        tx.refresh_from_db()
        self.assertIsNone(tx.next_retry_at, 'must be cleared once processed')
        attempt = results[tx.pk]
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.gateway_sim_id, fresh_sim.pk)
        self.assertTrue(TransactionEvent.objects.filter(transaction=tx, event_type='retry_dispatched').exists())

    def test_dispatch_due_retries_logs_when_no_gateway_is_available(self):
        tx = _make_transaction()
        tx.next_retry_at = timezone.now() - timezone.timedelta(seconds=1)
        tx.save(update_fields=['next_retry_at'])

        results = RetryManager.dispatch_due_retries()
        self.assertIsNone(results[tx.pk])
        self.assertTrue(TransactionEvent.objects.filter(transaction=tx, event_type='retry_no_gateway_available').exists())


@override_settings(REDIS_URL='redis://localhost:1/0')  # nothing listens here: guaranteed-fast connection refusal
class RedisLockDegradationTests(TestCase):
    def test_degrades_to_a_no_op_when_redis_is_unreachable(self):
        """The whole point of this lock is defense-in-depth on top of
        select_for_update() - it must never turn a Redis outage into a hard
        failure for payment processing."""
        entered = False
        with redis_lock('some-key', wait_timeout=0.2):
            entered = True
        self.assertTrue(entered, 'the protected block must still run even without Redis')


class UssdCodeModelTests(TestCase):
    """Gestion des opérateurs: UssdCode.render() is the substitution engine
    behind build_ussd_code() - tested in isolation from any Transaction."""

    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')

    def test_render_substitutes_known_variables(self):
        code = UssdCode.objects.create(
            operator=self.orange, service=self.internet, label='Internet',
            template='*456*{numero}*{montant}*{forfait}#',
        )
        result = code.render({'numero': '0700000001', 'montant': 1000, 'forfait': 'Internet'})
        self.assertEqual(result, '*456*0700000001*1000*Internet#')

    def test_render_raises_ussd_code_render_error_for_a_variable_the_context_lacks(self):
        code = UssdCode.objects.create(
            operator=self.orange, service=self.internet, label='Recharge PIN',
            template='*456*{pin}#',
        )
        with self.assertRaises(UssdCodeRenderError):
            code.render({'numero': '0700000001', 'montant': 1000, 'forfait': 'Internet'})

    def test_render_raises_value_error_for_an_unknown_variable_name(self):
        code = UssdCode.objects.create(
            operator=self.orange, service=self.internet, label='Typo',
            template='*456*{montnat}#',
        )
        with self.assertRaises(ValueError):
            code.render({'montnat': 1000})

    def test_unique_active_constraint_blocks_two_active_rows_for_the_same_operator_service(self):
        UssdCode.objects.create(operator=self.orange, service=self.internet, label='A', template='*456*{montant}#')
        with self.assertRaises(IntegrityError), db_transaction.atomic():
            UssdCode.objects.create(operator=self.orange, service=self.internet, label='B', template='*789#')

    def test_an_active_and_an_inactive_row_can_coexist_for_the_same_operator_service(self):
        UssdCode.objects.create(operator=self.orange, service=self.internet, label='A', template='*456*{montant}#')
        # Must not raise - the conditional UniqueConstraint only applies to
        # is_active=True rows, which is what lets "deactivate the old one,
        # keep it for history" work.
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, label='B (ancien)',
            template='*789#', is_active=False,
        )


class BuildUssdCodeTests(TestCase):
    """Gestion des opérateurs: build_ussd_code()/resolve_ussd_code() replace
    the old hardcoded formulas - exact-match, operator-default fallback, and
    the loud-failure case, plus the pre-existing ussd_code= override seam."""

    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        self.device = Device.objects.create(uid='client-app', primary_phone='0700000001')

    def _tx(self, operator=None, service=None, amount=1000):
        return Transaction.objects.create(
            device=self.device, service=service or self.internet, operator=operator or self.orange,
            phone_number='0700000001', amount=amount,
        )

    def test_exact_operator_service_match_wins_over_the_operator_default(self):
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Défaut',
            template='*456*{montant}#', is_default=True,
        )
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, label='Internet exact',
            template='*111*{montant}#',
        )
        tx = self._tx(amount=500)
        self.assertEqual(build_ussd_code(tx), '*111*500#')

    def test_falls_back_to_operator_default_when_no_exact_match(self):
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Défaut',
            template='*456*{montant}#', is_default=True,
        )
        tx = self._tx(amount=750)
        self.assertEqual(build_ussd_code(tx), '*456*750#')

    def test_raises_ussd_code_not_configured_when_nothing_matches(self):
        tx = self._tx()
        self.assertIsNone(resolve_ussd_code(self.orange, self.internet))
        with self.assertRaises(UssdCodeNotConfigured):
            build_ussd_code(tx)

    def test_ussd_code_override_still_bypasses_resolution(self):
        # No UssdCode configured at all for this operator/service - proves
        # the pre-existing `ussd_code=` seam on transaction_payload()/
        # gateway_task_payload() still short-circuits build_ussd_code()
        # entirely, unaffected by this refactor.
        tx = self._tx()
        payload = transaction_payload(tx, ussd_code='*999#')
        self.assertEqual(payload['ussd_code'], '*999#')
        payload = gateway_task_payload(tx, ussd_code='*999#')
        self.assertEqual(payload['ussd_code'], '*999#')


class UssdCodeAmountResolutionTests(TestCase):
    """Business-model audit (Operator -> Service -> Amount -> UssdCode):
    amount is a 3rd, optional resolution key on top of the pre-existing
    (operator, service) pair - these tests exercise the full 3-level
    cascade and the corrected uniqueness constraint."""

    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        self.device = Device.objects.create(uid='client-app', primary_phone='0700000001')

    def _tx(self, amount):
        return Transaction.objects.create(
            device=self.device, service=self.internet, operator=self.orange,
            phone_number='0700000001', amount=amount,
        )

    def test_amount_defaults_to_null_meaning_generic(self):
        code = UssdCode.objects.create(
            operator=self.orange, service=self.internet, label='Générique', template='*456*{montant}#',
        )
        self.assertIsNone(code.amount)

    def test_amount_can_be_set_to_a_specific_value(self):
        code = UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500, label='500F',
            template='*456*4*1#',
        )
        self.assertEqual(code.amount, 500)

    def test_level_1_exact_amount_match_wins_over_generic(self):
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=None, label='Générique',
            template='*456*{montant}#',
        )
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500, label='500F',
            template='*456*4*1#',
        )
        self.assertEqual(resolve_ussd_code(self.orange, self.internet, 500).label, '500F')
        self.assertEqual(build_ussd_code(self._tx(500)), '*456*4*1#')

    def test_level_2_falls_back_to_generic_amount_when_specific_amount_missing(self):
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=None, label='Générique',
            template='*456*{montant}#',
        )
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500, label='500F',
            template='*456*4*1#',
        )
        # amount=1000 has no dedicated row - must use the generic (amount=NULL) one.
        self.assertEqual(resolve_ussd_code(self.orange, self.internet, 1000).label, 'Générique')
        self.assertEqual(build_ussd_code(self._tx(1000)), '*456*1000#')

    def test_level_3_falls_back_to_operator_default_when_no_service_row_at_all(self):
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Défaut opérateur', template='*789*{montant}#',
            is_default=True,
        )
        self.assertEqual(resolve_ussd_code(self.orange, self.internet, 500).label, 'Défaut opérateur')
        self.assertEqual(build_ussd_code(self._tx(500)), '*789*500#')

    def test_no_configuration_at_all_resolves_to_none(self):
        self.assertIsNone(resolve_ussd_code(self.orange, self.internet, 500))
        with self.assertRaises(UssdCodeNotConfigured):
            build_ussd_code(self._tx(500))

    def test_resolve_ussd_code_without_an_amount_argument_behaves_exactly_as_before(self):
        """Pre-existing 2-argument callers (only ExecuteTransactionView's old
        preflight check, before Phase 3) must keep matching only the generic
        (amount=NULL) row - never an amount-specific one, since they have no
        amount to disambiguate with."""
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500, label='500F',
            template='*456*4*1#',
        )
        self.assertIsNone(resolve_ussd_code(self.orange, self.internet))

    def test_duplicate_active_specific_amount_is_rejected(self):
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500, label='A', template='*456*4*1#',
        )
        with self.assertRaises(IntegrityError), db_transaction.atomic():
            UssdCode.objects.create(
                operator=self.orange, service=self.internet, amount=500, label='B', template='*456*4*2#',
            )

    def test_duplicate_active_generic_rows_are_rejected(self):
        """The bug found during the architecture audit: NULL amount (and
        NULL service) must not let two active 'generic' rows coexist for the
        same operator - requires nulls_distinct=False on the constraint,
        confirmed supported by this project's Postgres connection."""
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=None, label='A', template='*456*{montant}#',
        )
        with self.assertRaises(IntegrityError), db_transaction.atomic():
            UssdCode.objects.create(
                operator=self.orange, service=self.internet, amount=None, label='B', template='*789*{montant}#',
            )

    def test_different_amounts_for_the_same_operator_service_can_coexist(self):
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500, label='500F', template='*456*4*1#',
        )
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=1000, label='1000F', template='*456*4*2#',
        )
        self.assertEqual(UssdCode.objects.filter(operator=self.orange, service=self.internet).count(), 2)


class UssdCodeSnapshotTests(TestCase):
    """Business-model audit, Phase 1: once a transaction has a
    ussd_code_used, build_ussd_code() must render from that frozen row for
    the rest of the transaction's life - never re-resolve, even if an admin
    later deactivates/replaces the configuration. Covers the real dashboard
    workflow (deactivate old, activate new - the UI itself enforces this
    order, see ussd_code_create's IntegrityError message), not an in-place
    edit of the same row's template (a different guarantee, out of scope)."""

    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        self.device = Device.objects.create(uid='client-app', primary_phone='0700000001')
        self.code_a = UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500,
            label='A', template='*111*{montant}#', is_active=True,
        )

    def _tx_created_like_execute_transaction_view(self):
        """Mirrors what ExecuteTransactionView actually does: resolve once,
        store the result on ussd_code_used at creation time."""
        resolved = resolve_ussd_code(self.orange, self.internet, 500)
        return Transaction.objects.create(
            device=self.device, service=self.internet, operator=self.orange,
            phone_number='0700000001', amount=500, ussd_code_used=resolved,
        )

    def test_build_ussd_code_still_uses_code_a_after_it_is_replaced_by_code_b(self):
        tx = self._tx_created_like_execute_transaction_view()
        self.assertEqual(build_ussd_code(tx), '*111*500#')

        # The real dashboard workflow: deactivate A, then activate B for the
        # exact same (operator, service, amount).
        self.code_a.is_active = False
        self.code_a.save(update_fields=['is_active'])
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500,
            label='B', template='*222*{montant}#', is_active=True,
        )

        # Sanity check: a *fresh* resolution (what used to happen on every
        # call) would now pick B - proving the scenario actually changed.
        self.assertEqual(resolve_ussd_code(self.orange, self.internet, 500).label, 'B')

        # But the transaction created while A was active must still render A.
        self.assertEqual(build_ussd_code(tx), '*111*500#')

    def test_gateway_task_payload_uses_the_exact_same_frozen_code(self):
        tx = self._tx_created_like_execute_transaction_view()
        self.code_a.is_active = False
        self.code_a.save(update_fields=['is_active'])
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500,
            label='B', template='*222*{montant}#', is_active=True,
        )

        payload = gateway_task_payload(tx)

        self.assertEqual(payload['ussd_code'], '*111*500#')

    def test_a_transaction_without_ussd_code_used_falls_back_to_fresh_resolution(self):
        """Historical transactions created before this field existed
        (nullable) must keep working exactly as before."""
        tx = Transaction.objects.create(
            device=self.device, service=self.internet, operator=self.orange,
            phone_number='0700000001', amount=500, ussd_code_used=None,
        )
        self.assertEqual(build_ussd_code(tx), '*111*500#')


class UssdCodeMigrationSeedTests(TestCase):
    """Gestion des opérateurs: proves migrations 0011/0012 reproduce the old
    hardcoded build_ussd_code() output byte-for-byte for every (operator,
    service) combination that would have existed pre-migration. _old_build_
    ussd_code is a frozen copy of the function as it existed before this
    module - do not update it to match new behavior, that would defeat the
    point of this test."""

    @staticmethod
    def _old_build_ussd_code(tx):
        amount = int(tx.amount)
        phone = tx.phone_number
        service_code = (tx.service.code or tx.service.name).lower()
        if 'transfer' in service_code or 'transfert' in service_code:
            return f'*123*{phone}*{amount}#'
        return f'*456*{amount}#'

    def setUp(self):
        self.device = Device.objects.create(uid='client-app', primary_phone='0700000001')

    def _seed_like_the_migration(self, operator, service):
        """Mirrors 0012_seed_ussd_codes.py's seed_ussd_codes() exactly, for
        an operator/service pair created at test-runtime (the migration
        itself only ever saw whatever existed in the DB at migration time,
        which is empty for a fresh test DB) - this is what proves the seed
        LOGIC is correct, independently of migration test infrastructure."""
        service_code = (service.code or service.name).lower()
        is_transfer_like = 'transfer' in service_code or 'transfert' in service_code
        template = '*123*{numero}*{montant}#' if is_transfer_like else '*456*{montant}#'
        label = 'Transfert' if is_transfer_like else 'Autre / Général'
        UssdCode.objects.get_or_create(
            operator=operator, service=service,
            defaults={'label': label, 'template': template, 'is_active': True},
        )

    def _assert_matches_old_behavior(self, operator, service, amount=1000):
        tx = Transaction.objects.create(
            device=self.device, service=service, operator=operator,
            phone_number='0700000001', amount=amount,
        )
        self._seed_like_the_migration(operator, service)
        self.assertEqual(build_ussd_code(tx), self._old_build_ussd_code(tx))

    def test_orange_subscription_matches_old_output(self):
        orange = Operator.objects.create(name='Orange', code='orange')
        internet = Service.objects.create(name='Internet', code='subscription')
        self._assert_matches_old_behavior(orange, internet, amount=1000)

    def test_mtn_subscription_matches_old_output(self):
        mtn = Operator.objects.create(name='MTN', code='mtn')
        internet = Service.objects.create(name='Internet', code='subscription')
        self._assert_matches_old_behavior(mtn, internet, amount=2500)

    def test_service_code_containing_transfert_matches_old_output(self):
        orange = Operator.objects.create(name='Orange', code='orange')
        transfert = Service.objects.create(name='Transfert crédit', code='transfert')
        self._assert_matches_old_behavior(orange, transfert, amount=3000)

    def test_service_code_containing_transfer_matches_old_output(self):
        orange = Operator.objects.create(name='Orange', code='orange')
        transfer = Service.objects.create(name='Credit Transfer', code='transfer')
        self._assert_matches_old_behavior(orange, transfer, amount=1500)

    def test_service_with_blank_code_falls_back_to_name(self):
        orange = Operator.objects.create(name='Orange', code='orange')
        blank_code = Service.objects.create(name='Transfert direct', code='')
        self._assert_matches_old_behavior(orange, blank_code, amount=4000)
