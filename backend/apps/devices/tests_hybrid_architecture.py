from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import (
    Device, Gateway, Operator, Payment, Service, Transaction, TransactionAttempt,
    UssdCode, UssdStep, UssdStepField,
)
from apps.core.serializers import gateway_task_payload, serialize_scenario_for_sync


class HybridArchitectureBackendTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = Operator.objects.create(name='Orange CI', code='orange_ci')
        self.service = Service.objects.create(name='Pass Internet', code='pass_internet')
        self.ussd_code = UssdCode.objects.create(
            operator=self.operator,
            service=self.service,
            label='Souscription Forfait Data',
            template='*133#',
            version=1,
        )
        # Step 1: Input amount
        self.step1 = UssdStep.objects.create(
            ussd_code=self.ussd_code,
            order=1,
            step_type='INPUT',
            name='Choix option',
        )
        UssdStepField.objects.create(
            step=self.step1,
            order=1,
            field_type='FIXED',
            value='1',
        )
        # Step 2: Agent Auth (CODE_DISTRIBUTEUR - secret local)
        self.step2 = UssdStep.objects.create(
            ussd_code=self.ussd_code,
            order=2,
            step_type='AGENT_AUTH',
            name='Authentification Agent Distributeur',
        )
        # Step 3: Final confirmation
        self.step3 = UssdStep.objects.create(
            ussd_code=self.ussd_code,
            order=3,
            step_type='FINAL_FIELD',
            name='Attente confirmation opérateur',
        )

        self.device = Device.objects.create(uid='dev-123', primary_phone='0700000000')
        self.gateway = Gateway.objects.create(name='GW_Test_1', status='online', is_active=True)

    def test_agent_auth_step_validation(self):
        """AGENT_AUTH steps must never have fields (secret is strictly local to Gateway)."""
        from django.core.exceptions import ValidationError
        field = UssdStepField(step=self.step2, order=1, field_type='FIXED', value='1234')
        with self.assertRaises(ValidationError):
            field.clean()

    def test_serialize_scenario_for_sync_zero_knowledge(self):
        """Serialization for Gateway sync must expose structure, version and AGENT_AUTH, with zero secrets."""
        data = serialize_scenario_for_sync(self.ussd_code)
        self.assertEqual(data['id'], self.ussd_code.id)
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['operator'], 'Orange CI')
        self.assertEqual(data['template'], '*133#')
        self.assertEqual(len(data['steps']), 3)

        # Check step types
        self.assertEqual(data['steps'][0]['step_type'], 'INPUT')
        self.assertEqual(data['steps'][0]['fields'][0]['value'], '1')

        self.assertEqual(data['steps'][1]['step_type'], 'AGENT_AUTH')
        self.assertEqual(len(data['steps'][1]['fields']), 0)

        self.assertEqual(data['steps'][2]['step_type'], 'FINAL_FIELD')
        self.assertEqual(len(data['steps'][2]['fields']), 0)

        # Zero PIN/secret
        self.assertNotIn('pin', str(data).lower())
        self.assertNotIn('code_distributeur', str(data).lower())

    def test_scenario_sync_endpoint(self):
        """GET /api/scenarios/sync/ returns versioned active scenarios."""
        response = self.client.get(reverse('api_scenarios_sync'))
        self.assertEqual(response.status_code, 200)
        res_json = response.json()
        self.assertIn('scenarios', res_json)
        self.assertGreaterEqual(res_json['count'], 1)

        synced_scenario = next(s for s in res_json['scenarios'] if s['id'] == self.ussd_code.id)
        self.assertEqual(synced_scenario['version'], 1)
        self.assertEqual(synced_scenario['steps'][1]['step_type'], 'AGENT_AUTH')

    def test_scenario_sync_filter_by_id(self):
        """GET /api/scenarios/sync/?scenario_id=X filters by scenario ID."""
        response = self.client.get(reverse('api_scenarios_sync') + f'?scenario_id={self.ussd_code.id}')
        self.assertEqual(response.status_code, 200)
        res_json = response.json()
        self.assertEqual(res_json['count'], 1)
        self.assertEqual(res_json['scenarios'][0]['id'], self.ussd_code.id)

    def test_gateway_task_payload_includes_scenario_version(self):
        """gateway_task_payload includes scenario_id and scenario_version."""
        tx = Transaction.objects.create(
            device=self.device,
            service=self.service,
            operator=self.operator,
            phone_number='0708091011',
            amount=1000,
            ussd_code_used=self.ussd_code,
            status='pending',
            gateway=self.gateway,
        )
        payload = gateway_task_payload(tx)
        self.assertEqual(payload['scenario_id'], self.ussd_code.id)
        self.assertEqual(payload['scenario_version'], 1)
