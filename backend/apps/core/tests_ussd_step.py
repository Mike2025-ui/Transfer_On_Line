"""Phase A (moteur USSD interactif) - UssdStep/UssdStepField.

Covers: creation, ordering, FIXED/DYNAMIC/FINAL_FIELD, multiple fields per
step, unknown-variable rejection, DB-level ordering constraints, and the
Admin formset guard that blocks FINAL_FIELD + a field in the same
submission (the model's own clean() cannot catch that case, since a new
step and its new inline fields are submitted together before either has
a pk to query by).
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from apps.core.models import Operator, Service, UssdCode, UssdStep, UssdStepField


class UssdStepModelTests(TestCase):
    def setUp(self):
        self.operator = Operator.objects.create(name='MTN', code='mtn')
        self.service = Service.objects.create(name='Transfert', code='transfert')
        self.ussd_code = UssdCode.objects.create(
            operator=self.operator, service=self.service, label='Transfert MTN', template='*133#',
        )

    def test_create_step_and_field(self):
        step = UssdStep.objects.create(ussd_code=self.ussd_code, order=1, step_type='INPUT', name='Menu principal')
        field = UssdStepField.objects.create(step=step, order=1, field_type='FIXED', value='6')
        self.assertEqual(step.fields.count(), 1)
        self.assertEqual(field.value, '6')

    def test_multiple_fields_same_step_ordered(self):
        step = UssdStep.objects.create(ussd_code=self.ussd_code, order=4, step_type='INPUT')
        UssdStepField.objects.create(step=step, order=1, field_type='DYNAMIC', value='numero')
        UssdStepField.objects.create(step=step, order=2, field_type='DYNAMIC', value='montant')
        UssdStepField.objects.create(step=step, order=3, field_type='FIXED', value='1')
        self.assertEqual(list(step.fields.values_list('value', flat=True)), ['numero', 'montant', '1'])

    def test_final_field_step_with_no_fields_is_valid(self):
        step = UssdStep(ussd_code=self.ussd_code, order=5, step_type='FINAL_FIELD')
        step.full_clean()
        step.save()

    def test_final_field_step_with_existing_field_rejected_by_clean(self):
        step = UssdStep.objects.create(ussd_code=self.ussd_code, order=5, step_type='FINAL_FIELD')
        UssdStepField.objects.create(step=step, order=1, field_type='FIXED', value='1')
        with self.assertRaises(ValidationError):
            step.full_clean()

    def test_dynamic_field_unknown_variable_rejected(self):
        step = UssdStep.objects.create(ussd_code=self.ussd_code, order=3, step_type='INPUT')
        field = UssdStepField(step=step, order=1, field_type='DYNAMIC', value='numero_client')
        with self.assertRaises(ValidationError):
            field.full_clean()

    def test_dynamic_field_known_variables_accepted(self):
        step = UssdStep.objects.create(ussd_code=self.ussd_code, order=3, step_type='INPUT')
        for variable in ('numero', 'montant', 'forfait', 'pin'):
            UssdStepField(step=step, order=1, field_type='DYNAMIC', value=variable).full_clean()

    def test_fixed_field_empty_value_rejected(self):
        step = UssdStep.objects.create(ussd_code=self.ussd_code, order=1, step_type='INPUT')
        field = UssdStepField(step=step, order=1, field_type='FIXED', value='   ')
        with self.assertRaises(ValidationError):
            field.full_clean()

    def test_field_on_final_field_step_rejected_by_clean(self):
        step = UssdStep.objects.create(ussd_code=self.ussd_code, order=5, step_type='FINAL_FIELD')
        field = UssdStepField(step=step, order=1, field_type='FIXED', value='1')
        with self.assertRaises(ValidationError):
            field.full_clean()

    def test_duplicate_step_order_rejected_by_db_constraint(self):
        UssdStep.objects.create(ussd_code=self.ussd_code, order=1, step_type='INPUT')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UssdStep.objects.create(ussd_code=self.ussd_code, order=1, step_type='INPUT')

    def test_duplicate_field_order_rejected_by_db_constraint(self):
        step = UssdStep.objects.create(ussd_code=self.ussd_code, order=1, step_type='INPUT')
        UssdStepField.objects.create(step=step, order=1, field_type='FIXED', value='6')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UssdStepField.objects.create(step=step, order=1, field_type='FIXED', value='7')

    def test_steps_ordered_by_order_field(self):
        UssdStep.objects.create(ussd_code=self.ussd_code, order=2, step_type='INPUT')
        UssdStep.objects.create(ussd_code=self.ussd_code, order=1, step_type='INPUT')
        self.assertEqual(list(self.ussd_code.steps.values_list('order', flat=True)), [1, 2])

    def test_full_mtn_scenario_example(self):
        scenario = [
            (1, 'INPUT', [('FIXED', '6')]),
            (2, 'INPUT', [('FIXED', '2')]),
            (3, 'INPUT', [('DYNAMIC', 'numero')]),
            (4, 'INPUT', [('DYNAMIC', 'montant')]),
            (5, 'FINAL_FIELD', []),
        ]
        for order, step_type, fields in scenario:
            step = UssdStep.objects.create(ussd_code=self.ussd_code, order=order, step_type=step_type)
            for field_order, (field_type, value) in enumerate(fields, start=1):
                UssdStepField.objects.create(step=step, order=field_order, field_type=field_type, value=value)
        self.assertEqual(self.ussd_code.steps.count(), 5)
        self.assertEqual(self.ussd_code.steps.get(order=5).fields.count(), 0)


class UssdStepAdminFormsetTests(TestCase):
    def setUp(self):
        self.operator = Operator.objects.create(name='MTN', code='mtn')
        self.ussd_code = UssdCode.objects.create(operator=self.operator, label='Transfert', template='*133#')
        self.step = UssdStep.objects.create(ussd_code=self.ussd_code, order=1, step_type='FINAL_FIELD')
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(username='admin_test_ussd_step', email='a@example.com', password='x')
        self.client = Client()
        self.client.force_login(self.admin_user)

    def _post_data(self, extra_field_forms=0):
        data = {
            'ussd_code': self.ussd_code.pk,
            'order': 1,
            'step_type': 'FINAL_FIELD',
            'name': '',
            'fields-TOTAL_FORMS': str(extra_field_forms),
            'fields-INITIAL_FORMS': '0',
            'fields-MIN_NUM_FORMS': '0',
            'fields-MAX_NUM_FORMS': '1000',
        }
        for i in range(extra_field_forms):
            data[f'fields-{i}-step'] = self.step.pk
            data[f'fields-{i}-order'] = str(i + 1)
            data[f'fields-{i}-field_type'] = 'FIXED'
            data[f'fields-{i}-value'] = '1'
        return data

    def test_final_field_plus_field_rejected_by_admin_formset(self):
        url = reverse('admin:core_ussdstep_change', args=[self.step.pk])
        response = self.client.post(url, self._post_data(extra_field_forms=1))
        self.assertEqual(response.status_code, 200)  # re-renders with errors, no redirect on failure
        self.assertEqual(UssdStepField.objects.filter(step=self.step).count(), 0)

    def test_final_field_with_no_fields_saves_successfully(self):
        url = reverse('admin:core_ussdstep_change', args=[self.step.pk])
        response = self.client.post(url, self._post_data(extra_field_forms=0))
        self.assertEqual(response.status_code, 302)  # redirect = success
