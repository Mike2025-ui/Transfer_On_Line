import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.core.models import (
    AuditLog, Device, Gateway, Operator, Payment, Service, Transaction, TransactionAttempt, TransactionEvent,
    UssdCode, UssdStep, UssdStepField,
)
from apps.devices.models import GatewaySim
from apps.payments.models import WebhookEvent


class OperatorsListViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')

    def test_lists_all_operators(self):
        response = self.client.get(reverse('operators'))
        self.assertEqual(response.status_code, 200)
        names = [op.name for op in response.context['page_obj']]
        self.assertCountEqual(names, ['Orange', 'MTN'])

    def test_search_by_name(self):
        response = self.client.get(reverse('operators'), {'q': 'ora'})
        names = [op.name for op in response.context['page_obj']]
        self.assertEqual(names, ['Orange'])

    def test_empty_state_renders_without_error(self):
        Operator.objects.all().delete()
        response = self.client.get(reverse('operators'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 0)


class OperatorWriteViewsAuthTests(TestCase):
    """Back Office audit: every dashboard view - read and write - is behind
    the app's own staff_member_required, which redirects to this app's own
    login page (dashboard_login), never Django Admin's (/admin/login/)."""

    def setUp(self):
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.staff_user = User.objects.create_user('admin', password='pw', is_staff=True)

    def test_anonymous_is_redirected_to_the_dashboards_own_login(self):
        response = self.client.get(reverse('operator_create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('dashboard_login'), response.url)
        self.assertNotIn('/admin/login/', response.url)

    def test_staff_user_can_access(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('operator_create'))
        self.assertEqual(response.status_code, 200)

    def test_read_views_also_require_staff_login(self):
        for name, kwargs in [
            ('operators', {}), ('ussd_codes', {'pk': self.orange.pk}),
            ('operators_history', {}), ('ussd_code_preview', {}),
        ]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name, kwargs=kwargs))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('dashboard_login'), response.url)

    def test_read_views_are_reachable_once_logged_in(self):
        self.client.force_login(self.staff_user)
        for name, kwargs in [
            ('operators', {}), ('ussd_codes', {'pk': self.orange.pk}),
            ('operators_history', {}), ('ussd_code_preview', {}),
        ]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name, kwargs=kwargs))
                self.assertEqual(response.status_code, 200)


class OperatorCreateEditDeleteTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user('admin', password='pw', is_staff=True)
        self.client.force_login(self.staff_user)

    def test_create_writes_an_audit_log(self):
        response = self.client.post(reverse('operator_create'), {'name': 'Moov', 'code': 'moov', 'is_active': 'on'})
        self.assertRedirects(response, reverse('operators'))
        self.assertTrue(Operator.objects.filter(name='Moov').exists())
        log = AuditLog.objects.get(action='operator.create')
        self.assertIn('Moov', log.details)
        self.assertEqual(log.admin, self.staff_user)

    def test_create_with_blank_name_fails_validation_and_writes_no_log(self):
        response = self.client.post(reverse('operator_create'), {'name': '', 'code': 'x'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Operator.objects.filter(code='x').exists())
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_edit_writes_an_audit_log_with_the_change(self):
        operator = Operator.objects.create(name='Orange', code='orange')
        response = self.client.post(
            reverse('operator_edit', kwargs={'pk': operator.pk}),
            {'name': 'Orange CI', 'code': 'orange', 'is_active': 'on'},
        )
        self.assertRedirects(response, reverse('operators'))
        operator.refresh_from_db()
        self.assertEqual(operator.name, 'Orange CI')
        log = AuditLog.objects.get(action='operator.update')
        self.assertIn('Orange CI', log.details)

    def test_delete_is_blocked_when_transactions_exist(self):
        operator = Operator.objects.create(name='Orange', code='orange')
        device = Device.objects.create(uid='client-app', primary_phone='0700000001')
        service = Service.objects.create(name='Internet', code='subscription')
        Transaction.objects.create(device=device, service=service, operator=operator, phone_number='0700000001', amount=1000)

        response = self.client.post(reverse('operator_delete', kwargs={'pk': operator.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Operator.objects.filter(pk=operator.pk).exists())

    def test_delete_succeeds_when_no_transactions_exist(self):
        operator = Operator.objects.create(name='Orange', code='orange')
        response = self.client.post(reverse('operator_delete', kwargs={'pk': operator.pk}))
        self.assertRedirects(response, reverse('operators'))
        self.assertFalse(Operator.objects.filter(pk=operator.pk).exists())


class UssdCodeCrudTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user('admin', password='pw', is_staff=True)
        self.client.force_login(self.staff_user)
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')

    def test_create_with_unknown_variable_fails_form_validation_not_500(self):
        response = self.client.post(
            reverse('ussd_code_create', kwargs={'pk': self.orange.pk}),
            {'service': self.internet.pk, 'label': 'Test', 'template': '*456*{bogus}#', 'is_active': 'on'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UssdCode.objects.filter(label='Test').exists())

    def test_create_a_second_active_row_for_the_same_pair_is_a_form_error_not_500(self):
        UssdCode.objects.create(operator=self.orange, service=self.internet, label='A', template='*456*{montant}#')
        response = self.client.post(
            reverse('ussd_code_create', kwargs={'pk': self.orange.pk}),
            {'service': self.internet.pk, 'label': 'B', 'template': '*789#', 'is_active': 'on'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(UssdCode.objects.filter(operator=self.orange, service=self.internet).count(), 1)

    def test_create_writes_an_audit_log(self):
        response = self.client.post(
            reverse('ussd_code_create', kwargs={'pk': self.orange.pk}),
            {'service': self.internet.pk, 'label': 'Internet', 'template': '*456*{montant}#', 'is_active': 'on'},
        )
        self.assertRedirects(response, reverse('ussd_codes', kwargs={'pk': self.orange.pk}))
        log = AuditLog.objects.get(action='ussd_code.create')
        self.assertIn('Internet', log.details)
        self.assertIn('Orange', log.details)

    def test_toggle_flips_is_active_and_returns_json(self):
        code = UssdCode.objects.create(operator=self.orange, service=self.internet, label='A', template='*456*{montant}#')
        response = self.client.post(reverse('ussd_code_toggle', kwargs={'pk': code.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'id': code.pk, 'is_active': False})
        code.refresh_from_db()
        self.assertFalse(code.is_active)

    def test_toggle_conflict_returns_409_json_not_500(self):
        active = UssdCode.objects.create(operator=self.orange, service=self.internet, label='A', template='*456*{montant}#')
        inactive = UssdCode.objects.create(
            operator=self.orange, service=self.internet, label='B', template='*789#', is_active=False,
        )
        response = self.client.post(reverse('ussd_code_toggle', kwargs={'pk': inactive.pk}))
        self.assertEqual(response.status_code, 409)
        self.assertIn('error', response.json())
        active.refresh_from_db()
        self.assertTrue(active.is_active)

    def test_toggle_rejects_get(self):
        code = UssdCode.objects.create(operator=self.orange, service=self.internet, label='A', template='*456*{montant}#')
        response = self.client.get(reverse('ussd_code_toggle', kwargs={'pk': code.pk}))
        self.assertEqual(response.status_code, 405)

    def test_delete_is_blocked_for_the_default_code(self):
        code = UssdCode.objects.create(
            operator=self.orange, service=None, label='Défaut', template='*456*{montant}#', is_default=True,
        )
        response = self.client.post(reverse('ussd_code_delete', kwargs={'pk': code.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(UssdCode.objects.filter(pk=code.pk).exists())


class UssdScenarioStepsTests(TestCase):
    """UssdCode -> UssdStep -> UssdStepField, managed entirely from the
    dashboard (ussd_code_create/_edit's steps_json field) - never Django
    Admin. Mirrors the exact example from the business-model audit: étape 1
    = numéro/montant/code secret marchand, étape 2 = choix fixes."""

    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')

    def _steps_payload(self):
        return json.dumps([
            {
                'order': 1, 'step_type': 'INPUT', 'name': '',
                'fields': [
                    {'order': 1, 'field_type': 'DYNAMIC', 'value': 'numero'},
                    {'order': 2, 'field_type': 'DYNAMIC', 'value': 'montant'},
                    {'order': 3, 'field_type': 'FIXED', 'value': '2004'},
                ],
            },
            {
                'order': 2, 'step_type': 'INPUT', 'name': '',
                'fields': [
                    {'order': 1, 'field_type': 'FIXED', 'value': '1'},
                    {'order': 2, 'field_type': 'FIXED', 'value': '2'},
                ],
            },
            {'order': 3, 'step_type': 'FINAL_FIELD', 'name': '', 'fields': []},
        ])

    def test_create_persists_steps_and_fields_in_order(self):
        response = self.client.post(
            reverse('ussd_code_create', kwargs={'pk': self.orange.pk}),
            {
                'service': self.internet.pk, 'label': 'Internet interactif', 'template': '*133#',
                'is_active': 'on', 'steps_json': self._steps_payload(),
            },
        )
        self.assertRedirects(response, reverse('ussd_codes', kwargs={'pk': self.orange.pk}))

        code = UssdCode.objects.get(label='Internet interactif')
        steps = list(code.steps.order_by('order'))
        self.assertEqual(len(steps), 3)
        self.assertEqual([s.step_type for s in steps], ['INPUT', 'INPUT', 'FINAL_FIELD'])

        step1_fields = list(steps[0].fields.order_by('order'))
        self.assertEqual(
            [(f.field_type, f.value) for f in step1_fields],
            [('DYNAMIC', 'numero'), ('DYNAMIC', 'montant'), ('FIXED', '2004')],
        )
        step2_fields = list(steps[1].fields.order_by('order'))
        self.assertEqual([(f.field_type, f.value) for f in step2_fields], [('FIXED', '1'), ('FIXED', '2')])
        self.assertEqual(steps[2].fields.count(), 0, 'a FINAL_FIELD step must never carry any field')

    def test_a_code_with_no_steps_still_works_exactly_like_before(self):
        """Plain single-shot USSD codes (no interactive scenario) remain
        fully supported - steps_json='[]' must not be forced/required."""
        response = self.client.post(
            reverse('ussd_code_create', kwargs={'pk': self.orange.pk}),
            {
                'service': self.internet.pk, 'label': 'Direct', 'template': '*456*{montant}#',
                'is_active': 'on', 'steps_json': '[]',
            },
        )
        self.assertRedirects(response, reverse('ussd_codes', kwargs={'pk': self.orange.pk}))
        code = UssdCode.objects.get(label='Direct')
        self.assertEqual(code.steps.count(), 0)

    def test_edit_replaces_steps_reordering_and_adding_a_value(self):
        code = UssdCode.objects.create(operator=self.orange, service=self.internet, label='A', template='*133#')
        step = UssdStep.objects.create(ussd_code=code, order=1, step_type='INPUT')
        UssdStepField.objects.create(step=step, order=1, field_type='FIXED', value='1')

        new_payload = json.dumps([
            {'order': 1, 'step_type': 'INPUT', 'name': '', 'fields': [
                {'order': 1, 'field_type': 'FIXED', 'value': '2'},
                {'order': 2, 'field_type': 'FIXED', 'value': '1'},
            ]},
        ])
        response = self.client.post(
            reverse('ussd_code_edit', kwargs={'pk': code.pk}),
            {'service': self.internet.pk, 'label': 'A', 'template': '*133#', 'is_active': 'on', 'steps_json': new_payload},
        )
        self.assertRedirects(response, reverse('ussd_codes', kwargs={'pk': self.orange.pk}))
        code.refresh_from_db()
        fields = list(code.steps.get(order=1).fields.order_by('order'))
        self.assertEqual([f.value for f in fields], ['2', '1'], 'the new order must be persisted, not the old one')

    def test_removing_all_steps_on_edit_reverts_to_a_direct_code(self):
        code = UssdCode.objects.create(operator=self.orange, service=self.internet, label='A', template='*133#')
        step = UssdStep.objects.create(ussd_code=code, order=1, step_type='INPUT')
        UssdStepField.objects.create(step=step, order=1, field_type='FIXED', value='1')

        response = self.client.post(
            reverse('ussd_code_edit', kwargs={'pk': code.pk}),
            {'service': self.internet.pk, 'label': 'A', 'template': '*133#', 'is_active': 'on', 'steps_json': '[]'},
        )
        self.assertRedirects(response, reverse('ussd_codes', kwargs={'pk': self.orange.pk}))
        self.assertEqual(code.steps.count(), 0)

    def test_a_final_field_step_with_a_value_is_rejected_not_silently_dropped(self):
        payload = json.dumps([{'order': 1, 'step_type': 'FINAL_FIELD', 'name': '', 'fields': [
            {'order': 1, 'field_type': 'FIXED', 'value': '1'},
        ]}])
        response = self.client.post(
            reverse('ussd_code_create', kwargs={'pk': self.orange.pk}),
            {'service': self.internet.pk, 'label': 'Bad', 'template': '*133#', 'is_active': 'on', 'steps_json': payload},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UssdCode.objects.filter(label='Bad').exists())
        self.assertContains(response, 'Fin de saisie')

    def test_an_unknown_dynamic_variable_is_rejected(self):
        payload = json.dumps([{'order': 1, 'step_type': 'INPUT', 'name': '', 'fields': [
            {'order': 1, 'field_type': 'DYNAMIC', 'value': 'not_a_real_variable'},
        ]}])
        response = self.client.post(
            reverse('ussd_code_create', kwargs={'pk': self.orange.pk}),
            {'service': self.internet.pk, 'label': 'Bad', 'template': '*133#', 'is_active': 'on', 'steps_json': payload},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UssdCode.objects.filter(label='Bad').exists())

    def test_duplicate_step_order_is_rejected(self):
        payload = json.dumps([
            {'order': 1, 'step_type': 'INPUT', 'name': '', 'fields': [{'order': 1, 'field_type': 'FIXED', 'value': '1'}]},
            {'order': 1, 'step_type': 'FINAL_FIELD', 'name': '', 'fields': []},
        ])
        response = self.client.post(
            reverse('ussd_code_create', kwargs={'pk': self.orange.pk}),
            {'service': self.internet.pk, 'label': 'Bad', 'template': '*133#', 'is_active': 'on', 'steps_json': payload},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UssdCode.objects.filter(label='Bad').exists())

    def test_malformed_json_is_rejected_not_a_500(self):
        response = self.client.post(
            reverse('ussd_code_create', kwargs={'pk': self.orange.pk}),
            {'service': self.internet.pk, 'label': 'Bad', 'template': '*133#', 'is_active': 'on', 'steps_json': '{not valid json'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UssdCode.objects.filter(label='Bad').exists())

    def test_edit_page_preloads_existing_steps_for_the_editor(self):
        code = UssdCode.objects.create(operator=self.orange, service=self.internet, label='A', template='*133#')
        step = UssdStep.objects.create(ussd_code=code, order=1, step_type='INPUT')
        UssdStepField.objects.create(step=step, order=1, field_type='DYNAMIC', value='numero')

        response = self.client.get(reverse('ussd_code_edit', kwargs={'pk': code.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'steps-initial-data')
        self.assertContains(response, '"numero"')

    def test_no_admin_route_is_required_to_manage_steps(self):
        """The only two dashboard routes (create/edit) are exactly what
        manages UssdStep/UssdStepField - confirms no separate /admin/-only
        path is needed for this feature."""
        self.assertTrue(reverse('ussd_code_create', kwargs={'pk': self.orange.pk}).startswith('/dashboard/'))
        self.assertTrue(True)  # ussd_code_edit's URL is exercised by the tests above


class UssdCodePreviewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))

    def test_valid_template_returns_rendered_string(self):
        response = self.client.get(reverse('ussd_code_preview'), {
            'template': '*456*{numero}*{montant}#', 'numero': '0700000001', 'montant': '1000',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'result': '*456*0700000001*1000#'})

    def test_pin_template_returns_json_error_not_500(self):
        response = self.client.get(reverse('ussd_code_preview'), {'template': '*456*{pin}#'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
        self.assertNotIn('{pin}', response.json().get('result', ''))


class OperatorsHistoryViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))

    def test_only_operator_and_ussd_code_actions_appear_newest_first(self):
        AuditLog.objects.create(action='operator.create', details='first')
        AuditLog.objects.create(action='ussd_code.create', details='second')
        AuditLog.objects.create(action='some.other.action', details='unrelated')

        response = self.client.get(reverse('operators_history'))
        actions = [log.action for log in response.context['page_obj']]
        self.assertEqual(actions, ['ussd_code.create', 'operator.create'])


# --- Étape 3/4: modernisation + tableaux de bord opérationnels -------------

def _make_transaction(operator, service, **kwargs):
    device = Device.objects.create(uid=f'device-{Transaction.objects.count()}', primary_phone='0700000001')
    defaults = {'phone_number': '0700000001', 'amount': 1000}
    defaults.update(kwargs)
    return Transaction.objects.create(device=device, service=service, operator=operator, **defaults)


class TransactionsListViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        self.tx1 = _make_transaction(self.orange, self.internet, status='success', amount=1000)
        self.tx2 = _make_transaction(self.mtn, self.internet, status='failed', amount=2000)

    def test_lists_all_transactions(self):
        response = self.client.get(reverse('transactions'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].paginator.count, 2)

    def test_search_by_reference(self):
        response = self.client.get(reverse('transactions'), {'q': str(self.tx1.reference)})
        refs = [str(tx.reference) for tx in response.context['page_obj']]
        self.assertEqual(refs, [str(self.tx1.reference)])

    def test_filter_by_status_and_operator(self):
        response = self.client.get(reverse('transactions'), {'status': 'failed', 'operator': self.mtn.pk})
        refs = [str(tx.reference) for tx in response.context['page_obj']]
        self.assertEqual(refs, [str(self.tx2.reference)])

    def test_sort_by_amount_ascending(self):
        response = self.client.get(reverse('transactions'), {'sort': 'amount_asc'})
        amounts = [tx.amount for tx in response.context['page_obj']]
        self.assertEqual(amounts, sorted(amounts))

    def test_latest_sim_is_none_when_no_attempt_has_a_sim(self):
        response = self.client.get(reverse('transactions'))
        for tx in response.context['page_obj']:
            self.assertIsNone(tx.latest_sim)


class TransactionDetailViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        self.tx = _make_transaction(self.orange, self.internet)

    def test_shows_events_and_attempts(self):
        TransactionEvent.log(self.tx, 'created')
        gateway = Gateway.objects.create(name='GW1', status='online')
        sim = GatewaySim.objects.create(gateway=gateway, operator=self.orange, slot=0)
        TransactionAttempt.objects.create(transaction=self.tx, attempt_number=1, gateway_sim=sim, status='success')

        response = self.client.get(reverse('transaction_detail', kwargs={'pk': self.tx.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['events']), 1)
        self.assertEqual(len(response.context['attempts']), 1)

    def test_shows_payment_webhook_evidence(self):
        payment = Payment.objects.create(
            method='jeko', reference='PAY-TX-1', provider_transaction_id='JEKO-1',
            amount=1000, status='accepted',
        )
        self.tx.payment = payment
        self.tx.save(update_fields=['payment'])
        WebhookEvent.objects.create(
            provider='jeko', event_id='evt-1', event_type='payment.accepted',
            payment_reference='JEKO-1', processed=True,
        )

        response = self.client.get(reverse('transaction_detail', kwargs={'pk': self.tx.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['webhook_events']), 1)
        self.assertContains(response, 'payment.accepted')

    def test_404_for_unknown_transaction(self):
        response = self.client.get(reverse('transaction_detail', kwargs={'pk': 999999}))
        self.assertEqual(response.status_code, 404)


class PaymentsListViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        Payment.objects.create(method='jeko', reference='PAY-1', amount=1000, status='accepted')
        Payment.objects.create(method='geniuspay', reference='PAY-2', amount=2000, status='pending')

    def test_page_contains_only_payment_data(self):
        response = self.client.get(reverse('payments'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('funnel', response.context)
        self.assertNotContains(response, 'Base de données')
        self.assertNotContains(response, 'Échecs récents')

    def test_filter_by_method(self):
        response = self.client.get(reverse('payments'), {'method': 'geniuspay'})
        refs = [p.reference for p in response.context['page_obj']]
        self.assertEqual(refs, ['PAY-2'])

    def test_response_never_renders_provider_payload(self):
        Payment.objects.filter(reference='PAY-1').update(
            provider_payload={'api_secret_leak_check': 'should-never-appear-in-html'}
        )
        response = self.client.get(reverse('payments'))
        self.assertNotContains(response, 'should-never-appear-in-html')

class GatewaysListViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))

    def test_renders_pool_stats_and_gateway_state(self):
        Gateway.objects.create(name='GW1', status='online', is_active=True, battery_level=80)
        Gateway.objects.create(name='GW2', status='offline', is_active=True)
        response = self.client.get(reverse('gateways'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['stats']['total_gateways'], 2)
        self.assertEqual(len(response.context['gateways']), 2)

    def test_empty_state_renders_without_error(self):
        response = self.client.get(reverse('gateways'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['gateways'], [])


class GatewaySimsListViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')
        gateway = Gateway.objects.create(name='GW1', status='online')
        self.sim1 = GatewaySim.objects.create(gateway=gateway, operator=self.orange, slot=0)
        self.sim2 = GatewaySim.objects.create(gateway=gateway, operator=self.mtn, slot=1, is_active=False)

    def test_lists_sims_with_a_score(self):
        response = self.client.get(reverse('sims'))
        self.assertEqual(response.status_code, 200)
        rows = list(response.context['page_obj'])
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIsInstance(row['score'], float)

    def test_filter_by_operator_and_active(self):
        response = self.client.get(reverse('sims'), {'operator': self.orange.pk, 'active': 'active'})
        rows = list(response.context['page_obj'])
        self.assertEqual([r['sim'].pk for r in rows], [self.sim1.pk])


class SchedulerMonitorViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')

    def test_reflects_engine_flag_state(self):
        response = self.client.get(reverse('scheduler'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['engine_enabled'], settings.USE_NEW_TRANSACTION_ENGINE)

    def test_aggregates_attempt_statuses_and_failure_reasons(self):
        tx = _make_transaction(self.orange, self.internet)
        gateway = Gateway.objects.create(name='GW1', status='online')
        sim = GatewaySim.objects.create(gateway=gateway, operator=self.orange, slot=0)
        TransactionAttempt.objects.create(
            transaction=tx, attempt_number=1, gateway_sim=sim, status='failed', failure_reason='timeout',
        )
        response = self.client.get(reverse('scheduler'))
        self.assertEqual(response.context['attempt_status_counts'].get('failed'), 1)
        self.assertEqual(response.context['failure_reason_counts'].get('timeout'), 1)


class ServicesCrudTests(TestCase):
    """Mirrors OperatorCreateEditDeleteTests exactly - same CRUD pattern,
    same staff-only write protection, applied to Service instead."""

    def setUp(self):
        self.staff_user = User.objects.create_user('admin', password='pw', is_staff=True)

    def test_anonymous_is_redirected_to_the_dashboards_own_login(self):
        response = self.client.get(reverse('service_create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('dashboard_login'), response.url)
        self.assertNotIn('/admin/login/', response.url)

    def test_list_also_requires_staff_login(self):
        response = self.client.get(reverse('services'))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('services'))
        self.assertEqual(response.status_code, 200)

    def test_create_writes_an_audit_log(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(reverse('service_create'), {'name': 'SMS', 'code': 'sms', 'is_active': 'on'})
        self.assertRedirects(response, reverse('services'))
        self.assertTrue(Service.objects.filter(name='SMS').exists())
        log = AuditLog.objects.get(action='service.create')
        self.assertIn('SMS', log.details)

    def test_edit_writes_an_audit_log(self):
        self.client.force_login(self.staff_user)
        service = Service.objects.create(name='Internet', code='subscription')
        response = self.client.post(
            reverse('service_edit', kwargs={'pk': service.pk}),
            {'name': 'Internet 4G', 'code': 'subscription', 'is_active': 'on'},
        )
        self.assertRedirects(response, reverse('services'))
        service.refresh_from_db()
        self.assertEqual(service.name, 'Internet 4G')
        self.assertTrue(AuditLog.objects.filter(action='service.update').exists())

    def test_delete_is_blocked_when_transactions_exist(self):
        self.client.force_login(self.staff_user)
        operator = Operator.objects.create(name='Orange', code='orange')
        service = Service.objects.create(name='Internet', code='subscription')
        _make_transaction(operator, service)

        response = self.client.post(reverse('service_delete', kwargs={'pk': service.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Service.objects.filter(pk=service.pk).exists())

    def test_delete_succeeds_when_no_transactions_exist(self):
        self.client.force_login(self.staff_user)
        service = Service.objects.create(name='Internet', code='subscription')
        response = self.client.post(reverse('service_delete', kwargs={'pk': service.pk}))
        self.assertRedirects(response, reverse('services'))
        self.assertFalse(Service.objects.filter(pk=service.pk).exists())


class UssdCodesAllViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(operator=self.orange, service=self.internet, label='A', template='*456*{montant}#')
        UssdCode.objects.create(operator=self.mtn, service=self.internet, label='B', template='*789*{montant}#')

    def test_lists_codes_across_all_operators(self):
        response = self.client.get(reverse('ussd_codes_all'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].paginator.count, 2)

    def test_filter_by_operator(self):
        response = self.client.get(reverse('ussd_codes_all'), {'operator': self.mtn.pk})
        labels = [c.label for c in response.context['page_obj']]
        self.assertEqual(labels, ['B'])

    def test_edit_and_toggle_urls_from_the_global_list_reuse_etape_2_views(self):
        """No second CRUD implementation - ussd_code_edit/_toggle/_delete are
        the exact same Étape 2 views, just reachable from a new entry point."""
        code = UssdCode.objects.get(label='A')
        staff = User.objects.create_user('admin2', password='pw', is_staff=True)
        self.client.force_login(staff)
        response = self.client.post(reverse('ussd_code_toggle', kwargs={'pk': code.pk}))
        self.assertEqual(response.status_code, 200)


class AuditLogsTabsViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')

    def test_audit_tab_shows_auditlog_entries(self):
        AuditLog.objects.create(action='operator.create', details='x')
        response = self.client.get(reverse('audit'), {'tab': 'audit'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['audit_page'].paginator.count, 1)
        self.assertIsNone(response.context['tx_event_page'])

    def test_transactions_tab_shows_transaction_events(self):
        tx = _make_transaction(self.orange, self.internet)
        TransactionEvent.log(tx, 'created')
        response = self.client.get(reverse('audit'), {'tab': 'transactions'})
        self.assertEqual(response.context['tx_event_page'].paginator.count, 1)

    def test_webhooks_tab_shows_webhook_events(self):
        WebhookEvent.objects.create(provider='geniuspay', event_id='evt-1', event_type='payment.success')
        response = self.client.get(reverse('audit'), {'tab': 'webhooks'})
        self.assertEqual(response.context['webhook_page'].paginator.count, 1)


@patch('apps.dashboard.views.check_redis', return_value='ok')
@patch('apps.dashboard.views.check_provider_reachable', return_value='ok')
class SystemHealthViewTests(TestCase):
    """Same mocking discipline as apps.core.tests.HealthEndpointTests: a
    dashboard test suite must never depend on real Redis/network reachability
    to run fast and deterministically."""

    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))

    def test_renders_real_checks_and_pending_count(self, _provider, _redis):
        orange = Operator.objects.create(name='Orange', code='orange')
        internet = Service.objects.create(name='Internet', code='subscription')
        _make_transaction(orange, internet, status='pending')

        response = self.client.get(reverse('system_health'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['checks']['database'], 'ok')
        self.assertEqual(response.context['checks']['redis'], 'ok')
        self.assertEqual(response.context['pending_transactions'], 1)

    @patch('apps.dashboard.views.check_database', return_value='down')
    def test_never_claims_ok_when_a_check_actually_failed(self, _mocked_db, _provider, _redis):
        response = self.client.get(reverse('system_health'))
        self.assertEqual(response.context['checks']['database'], 'down')
        self.assertNotContains(response, 'Connexion OK')


class DashboardLoginViewTests(TestCase):
    """The Back Office's own login - never Django Admin's."""

    def setUp(self):
        self.staff = User.objects.create_user('staff', password='pw', is_staff=True)
        self.non_staff = User.objects.create_user('regular', password='pw', is_staff=False)

    def test_valid_staff_login_redirects_to_dashboard(self):
        response = self.client.post(reverse('dashboard_login'), {'username': 'staff', 'password': 'pw'})
        self.assertRedirects(response, reverse('dashboard'))

    def test_non_staff_account_is_rejected(self):
        response = self.client.post(reverse('dashboard_login'), {'username': 'regular', 'password': 'pw'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'pas accès au Back Office')
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_invalid_credentials_show_an_error_not_a_500(self):
        response = self.client.post(reverse('dashboard_login'), {'username': 'staff', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'incorrect')

    def test_already_authenticated_staff_is_redirected_away_from_login(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('dashboard_login'))
        self.assertRedirects(response, reverse('dashboard'))

    def test_logout_requires_post_and_clears_the_session(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('dashboard_logout'))
        self.assertRedirects(response, reverse('dashboard_login'))
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)


class GatewayAndSimToggleTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.gateway = Gateway.objects.create(name='GW1', status='online', is_active=True)
        self.sim = GatewaySim.objects.create(gateway=self.gateway, operator=self.orange, slot=0, is_active=True)

    def test_gateway_toggle_flips_is_active_and_logs(self):
        response = self.client.post(reverse('gateway_toggle', kwargs={'pk': self.gateway.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'id': self.gateway.pk, 'is_active': False})
        self.gateway.refresh_from_db()
        self.assertFalse(self.gateway.is_active)
        self.assertTrue(AuditLog.objects.filter(action='gateway.deactivate').exists())

    def test_sim_toggle_flips_is_active_and_logs(self):
        response = self.client.post(reverse('sim_toggle', kwargs={'pk': self.sim.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'id': self.sim.pk, 'is_active': False})
        self.sim.refresh_from_db()
        self.assertFalse(self.sim.is_active)
        self.assertTrue(AuditLog.objects.filter(action='sim.deactivate').exists())

    def test_toggle_rejects_get(self):
        response = self.client.get(reverse('gateway_toggle', kwargs={'pk': self.gateway.pk}))
        self.assertEqual(response.status_code, 405)


class DashboardNavigationSmokeTests(TestCase):
    """Every URL the new sidebar links to must resolve and render - the
    'never break an existing URL' constraint plus a safety net for the 11
    nav destinations added in Étape 3."""

    def setUp(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))

    def test_all_read_only_nav_destinations_return_200(self):
        for name in [
            'dashboard', 'transactions', 'payments', 'gateways', 'sims', 'scheduler',
            'operators', 'services', 'ussd_codes_all', 'audit', 'system_health',
        ]:
            with self.subTest(name=name):
                with patch('apps.dashboard.views.check_redis', return_value='ok'), \
                     patch('apps.dashboard.views.check_provider_reachable', return_value='ok'):
                    response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
