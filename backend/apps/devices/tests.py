from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction as db_transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Device, Gateway, Operator, Payment, Service, Transaction, TransactionAttempt, UssdCode
from apps.core.services.retry_manager import RetryManager
from apps.devices.models import GatewaySim
from apps.devices.services.gateway_manager import GatewayManager
from apps.devices.services.reservation_manager import ReservationManager


class GatewaySimModelTests(TestCase):
    """B1 - model-level only: no service exists yet to exercise these
    through, per the 'no business logic in B1' constraint."""

    def setUp(self):
        self.gateway = Gateway.objects.create(name='Orange - 0700000000', host='gateway-1')
        self.orange = Operator.objects.create(name='Orange', code='orange')

    def test_defaults(self):
        sim = GatewaySim.objects.create(gateway=self.gateway, operator=self.orange, msisdn='0700000000')
        self.assertTrue(sim.is_active)
        self.assertEqual(sim.slot, 0)
        self.assertEqual(sim.success_count, 0)
        self.assertEqual(sim.failure_count, 0)
        self.assertEqual(sim.consecutive_failures, 0)

    def test_a_gateway_cannot_have_two_sims_in_the_same_slot(self):
        GatewaySim.objects.create(gateway=self.gateway, operator=self.orange, slot=0)
        with self.assertRaises(IntegrityError), db_transaction.atomic():
            GatewaySim.objects.create(gateway=self.gateway, operator=self.orange, slot=0)

    def test_a_gateway_can_have_two_sims_in_different_slots(self):
        mtn = Operator.objects.create(name='MTN', code='mtn')
        GatewaySim.objects.create(gateway=self.gateway, operator=self.orange, slot=0)
        GatewaySim.objects.create(gateway=self.gateway, operator=mtn, slot=1)
        self.assertEqual(self.gateway.sims.count(), 2)

    def test_deleting_gateway_cascades_to_its_sims(self):
        GatewaySim.objects.create(gateway=self.gateway, operator=self.orange, slot=0)
        self.gateway.delete()
        self.assertEqual(GatewaySim.objects.count(), 0)


class HeartbeatBackwardCompatibilityTests(TestCase):
    """B2: an older mobile app build sends only what GatewayHeartbeatView
    already accepted before B2 - none of the new telemetry keys, no `sims`.
    This must keep behaving exactly as it did before B2.

    Business-model audit Phase 7: `gateway_uuid`/`details.uuid` no longer
    select OR create a Gateway row - only the authenticated identity does
    (see _authenticate_gateway) - so every test here now pre-provisions its
    Gateway + secret and asserts the heartbeat updates THAT row, not that an
    unknown uuid conjures a new one."""

    def setUp(self):
        self.client = APIClient()
        self.gateway = Gateway.objects.create(name='Legacy Gateway', host='')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.gateway.generate_secret())

    def test_legacy_payload_shape_still_updates_the_authenticated_gateway(self):
        response = self.client.post(
            reverse('api_gateway_heartbeat_create'),
            {
                'status': 'online',
                'gateway_uuid': 'legacy-device-1',
                'details': {
                    'uuid': 'legacy-device-1',
                    'phone_number': '0700000000',
                    'operator': 'Orange',
                    'device_model': 'Pixel 4',
                    'os_version': '13',
                },
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.gateway.refresh_from_db()
        self.assertEqual(self.gateway.host, 'legacy-device-1', 'details.uuid still updates host as telemetry')
        self.assertEqual(self.gateway.status, 'online')
        self.assertIsNone(self.gateway.battery_level)
        self.assertEqual(GatewaySim.objects.filter(gateway=self.gateway).count(), 0)
        self.assertEqual(Gateway.objects.count(), 1, 'never a second row for a self-declared uuid')

    def test_a_field_missing_from_a_later_heartbeat_does_not_erase_a_previously_reported_value(self):
        client_payload = lambda details: self.client.post(  # noqa: E731
            reverse('api_gateway_heartbeat_create'),
            {'status': 'online', 'gateway_uuid': 'device-2', 'details': details},
            format='json',
        )
        client_payload({'uuid': 'device-2', 'phone_number': '0700000001', 'battery_level': 88})
        gateway = Gateway.objects.get(host='device-2')
        self.assertEqual(gateway.battery_level, 88)

        # a later heartbeat from an older app build (or a dropped telemetry read) omits battery_level
        client_payload({'uuid': 'device-2', 'phone_number': '0700000001'})
        gateway.refresh_from_db()
        self.assertEqual(gateway.battery_level, 88, 'must not be reset to None just because this heartbeat omitted it')


class HeartbeatTelemetryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.gateway = Gateway.objects.create(name='Telemetry Gateway', host='')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.gateway.generate_secret())

    def test_extended_telemetry_is_stored(self):
        response = self.client.post(
            reverse('api_gateway_heartbeat_create'),
            {
                'status': 'online',
                'gateway_uuid': 'device-3',
                'details': {
                    'uuid': 'device-3', 'phone_number': '0700000002', 'operator': 'Orange',
                    'battery_level': 42, 'temperature': 33.5, 'ram_available_mb': 512,
                    'storage_available_mb': 4096, 'network_type': '4G', 'signal_strength': -70,
                    'ip_address': '192.168.1.50', 'app_version': '1.3.0',
                    'is_busy': 'false', 'current_task_count': 0,
                },
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        gateway = Gateway.objects.get(host='device-3')
        self.assertEqual(gateway.battery_level, 42)
        self.assertEqual(gateway.temperature, 33.5)
        self.assertEqual(gateway.ram_available_mb, 512)
        self.assertEqual(gateway.network_type, '4G')
        self.assertEqual(gateway.signal_strength, -70)
        self.assertEqual(gateway.ip_address, '192.168.1.50')
        self.assertEqual(gateway.app_version, '1.3.0')
        self.assertFalse(gateway.is_busy, '"false" the string must not be treated as truthy')
        self.assertEqual(gateway.reported_task_count, 0)

    def test_malformed_telemetry_value_is_ignored_not_a_500(self):
        response = self.client.post(
            reverse('api_gateway_heartbeat_create'),
            {
                'status': 'online',
                'gateway_uuid': 'device-4',
                'details': {'uuid': 'device-4', 'phone_number': '0700000003', 'battery_level': 'not-a-number'},
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        gateway = Gateway.objects.get(host='device-4')
        self.assertIsNone(gateway.battery_level)

    def test_sims_payload_upserts_gateway_sim_rows(self):
        payload = {
            'status': 'online',
            'gateway_uuid': 'device-5',
            'details': {
                'uuid': 'device-5', 'phone_number': '0700000004',
                'sims': [
                    {'slot': 0, 'operator': 'orange', 'msisdn': '0700000004'},
                    {'slot': 1, 'operator': 'mtn', 'msisdn': '0500000004'},
                ],
            },
        }
        self.client.post(reverse('api_gateway_heartbeat_create'), payload, format='json')
        gateway = Gateway.objects.get(host='device-5')
        sims = GatewaySim.objects.filter(gateway=gateway).order_by('slot')
        self.assertEqual(sims.count(), 2)
        self.assertEqual(sims[0].operator.name, 'Orange')
        self.assertEqual(sims[1].operator.name, 'Mtn')

        # re-sending the same slot updates in place rather than duplicating
        payload['details']['sims'] = [{'slot': 0, 'operator': 'orange', 'msisdn': '0700000099'}]
        self.client.post(reverse('api_gateway_heartbeat_create'), payload, format='json')
        self.assertEqual(GatewaySim.objects.filter(gateway=gateway).count(), 2)
        sims[0].refresh_from_db()
        self.assertEqual(sims[0].msisdn, '0700000099')


class RealisticMobileHeartbeatIntegrationTests(TestCase):
    """Mobile chantier, objectifs 3 & 4: a heartbeat shaped exactly like what
    the updated Flutter Mobile app now sends (see gateway_api.dart's
    DeviceSnapshot.toTelemetryJson() + main.dart's `details` assembly) must
    both populate Gateway/GatewaySim correctly AND leave GatewayManager
    able to actually select from the result - not just store inert fields."""

    def setUp(self):
        self.client = APIClient()
        self.gateway = Gateway.objects.create(name='Mobile Gateway', host='')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.gateway.generate_secret())

    def _mobile_heartbeat_payload(self, **overrides):
        payload = {
            'status': 'online',
            'gateway_uuid': 'mobile-device-9',
            'details': {
                'uuid': 'mobile-device-9',
                'phone_number': '0700000009',
                'operator': 'Orange',
                'device_model': 'Pixel 7',
                'os_version': '14',
                'app_version': '1.4.0',
                'battery_level': 76,
                'network_type': 'wifi',
                'signal_strength': 3,
                'ip_address': '192.168.1.42',
                'sims': [
                    {'slot': 0, 'operator': 'orange', 'msisdn': '0700000009'},
                    {'slot': 1, 'operator': 'mtn', 'msisdn': '0500000009'},
                ],
            },
        }
        payload['details'].update(overrides)
        return payload

    def test_full_mobile_payload_populates_gateway_and_both_sims(self):
        response = self.client.post(
            reverse('api_gateway_heartbeat_create'),
            self._mobile_heartbeat_payload(),
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        gateway = Gateway.objects.get(host='mobile-device-9')
        self.assertEqual(gateway.battery_level, 76)
        self.assertEqual(gateway.network_type, 'wifi')
        self.assertEqual(gateway.signal_strength, 3)
        self.assertEqual(gateway.ip_address, '192.168.1.42')
        self.assertEqual(gateway.app_version, '1.4.0')

        sims = GatewaySim.objects.filter(gateway=gateway).order_by('slot')
        self.assertEqual(sims.count(), 2)
        self.assertEqual(sims[0].operator.name, 'Orange')
        self.assertEqual(sims[0].msisdn, '0700000009')
        self.assertEqual(sims[1].operator.name, 'Mtn')
        self.assertEqual(sims[1].msisdn, '0500000009')

    def test_gateway_manager_can_actually_select_the_reported_sim(self):
        """Not just 'is it stored' - eligible_sims() must return it, because
        that is the only thing the Scheduler will ever call."""
        self.client.post(
            reverse('api_gateway_heartbeat_create'),
            self._mobile_heartbeat_payload(),
            format='json',
        )
        gateway = Gateway.objects.get(host='mobile-device-9')
        orange = Operator.objects.get(name='Orange')

        eligible = list(GatewayManager.eligible_sims(orange))
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0].gateway_id, gateway.id)
        self.assertEqual(eligible[0].msisdn, '0700000009')

        state = GatewayManager.gateway_state(gateway)
        self.assertEqual(state['battery_level'], 76)
        self.assertEqual(state['network_type'], 'wifi')
        self.assertEqual(state['signal_strength'], 3)
        self.assertEqual(len(state['sims']), 2)

    def test_low_battery_reported_by_mobile_app_excludes_it_from_selection(self):
        """battery_level actually reaching the DB from a real payload is not
        enough - it must flow through to the eligibility filter too."""
        self.client.post(
            reverse('api_gateway_heartbeat_create'),
            self._mobile_heartbeat_payload(battery_level=5),
            format='json',
        )
        orange = Operator.objects.get(name='Orange')
        self.assertEqual(list(GatewayManager.eligible_sims(orange)), [])


@override_settings(
    CINETPAY_API_KEY='api-key',
    CINETPAY_SITE_ID='site-id',
    CINETPAY_NOTIFY_URL='https://api.example.com/api/payments/cinetpay/notify/',
    CINETPAY_RETURN_URL='https://app.example.com/payment/success',
    # Business-model audit Phase 5: made explicit rather than relying on the
    # ambient default, which now depends on the local .env's dev/test
    # activation of USE_NEW_TRANSACTION_ENGINE - this class's assertions
    # (e.g. absence of `sim_slot`) specifically target the flag-off path.
    USE_NEW_TRANSACTION_ENGINE=False,
    # Same reasoning, for the same reason: this class's tests request
    # payment_method='auto' (the client default) and mock CinetPayProvider
    # specifically, so 'auto' must actually resolve to cinetpay regardless
    # of the ambient PAYMENT_PROVIDER_ORDER (which is feexpay,geniuspay in
    # this project's real/local .env) - otherwise 'auto' silently tries
    # feexpay/geniuspay for real instead of ever reaching the mock.
    PAYMENT_PROVIDER_ORDER='cinetpay',
)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class CinetPayFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.gateway = Gateway.objects.create(
            name='Orange - 0700000000',
            host='gateway-1',
            status='online',
        )
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.gateway.generate_secret())
        # Gestion des opérateurs / business-model audit: ExecuteTransactionView
        # no longer does get_or_create(name=...) for either Operator or
        # Service (Phase 3) - both must already exist and be active, so both
        # are pre-created here instead of relying on the view to spawn them.
        self.orange = Operator.objects.create(name='Orange', code='orange')
        Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Défaut test',
            template='*456*{montant}#', is_active=True, is_default=True,
        )
        # Business-model audit Phase 7.2: PendingTransactionsView's operator/
        # SIM cross-check is now unconditional - without a matching
        # GatewaySim, this class's hand-crafted Transaction(gateway=self.
        # gateway) would never be considered eligible for its own Gateway.
        GatewaySim.objects.create(gateway=self.gateway, operator=self.orange, slot=0, is_active=True)

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_execute_transaction_initializes_cinetpay_checkout(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult

        create_payment.return_value = PaymentInitResult(
            checkout_url='https://checkout.cinetpay.com/pay/token-123',
            provider_transaction_id='token-123',
            raw={
                'code': '201',
                'data': {
                    'payment_token': 'token-123',
                    'payment_url': 'https://checkout.cinetpay.com/pay/token-123',
                },
            },
        )

        response = self.client.post(
            reverse('api_transaction_execute'),
            {
                'operator': 'Orange',
                'service': 'Internet',
                'operation': 'subscription',
                'phone': '0700000001',
                'amount': 1000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['payment_method'], 'cinetpay')
        self.assertEqual(response.data['payment_status'], 'pending')
        self.assertEqual(response.data['checkout_url'], 'https://checkout.cinetpay.com/pay/token-123')
        self.assertTrue(Payment.objects.filter(method='cinetpay', amount=Decimal('1000')).exists())

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.verify_payment')
    def test_pending_transactions_are_exposed_only_after_accepted_payment(self, verify_payment, _redis_lock):
        payment = Payment.objects.create(method='cinetpay', reference='PAY-1', amount=1000)
        tx = Transaction.objects.create(
            device_id=self._device_id(),
            service_id=self._service_id(),
            operator_id=self._operator_id(),
            gateway=self.gateway,
            phone_number='0700000001',
            amount=1000,
            payment=payment,
            payment_method='cinetpay',
            payment_reference='PAY-1',
        )
        self.assertEqual(self.client.get(reverse('api_transaction_pending')).data, [])

        from apps.payments.providers.base import PaymentStatusResult

        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        notify = self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': 'PAY-1'}, format='json')
        self.assertEqual(notify.status_code, 200)

        pending = self.client.get(reverse('api_transaction_pending'))
        self.assertEqual(len(pending.data), 1)
        self.assertEqual(pending.data[0]['reference'], str(tx.reference))
        # The Android Gateway must never see which payment provider was used,
        # its reference/status, or the checkout URL - see gateway_task_payload().
        for leaked_field in ('payment_method', 'payment_reference', 'payment_status', 'checkout_url'):
            self.assertNotIn(leaked_field, pending.data[0])
        # USE_NEW_TRANSACTION_ENGINE defaults to False in this test - no
        # Scheduler ever ran, so there is no reserved SIM to report.
        self.assertNotIn('sim_slot', pending.data[0])

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.verify_payment')
    def test_notify_with_an_already_resolved_transaction_does_not_500(self, verify_payment, _redis_lock):
        """Phase D audit (Critique n°2): the transaction was already resolved
        to a different terminal status by the time this notify ping arrives
        (e.g. it was separately cancelled) - the notify view must degrade
        gracefully, never crash with an unhandled 500."""
        payment = Payment.objects.create(method='cinetpay', reference='PAY-2', amount=1000, status='pending')
        tx = Transaction.objects.create(
            device_id=self._device_id(), service_id=self._service_id(), operator_id=self._operator_id(),
            gateway=self.gateway, phone_number='0700000001', amount=1000,
            payment=payment, payment_method='cinetpay', payment_reference='PAY-2', status='cancelled',
        )

        from apps.payments.providers.base import PaymentStatusResult
        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})

        response = self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': 'PAY-2'}, format='json')

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending', 'the Payment write must be rolled back, never partially applied')
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'cancelled', 'the rejected transition must never apply')

    def _device_id(self):
        from apps.core.models import Device

        return Device.objects.create(uid='client-app', primary_phone='0700000001').id

    def _service_id(self):
        from apps.core.models import Service

        return Service.objects.create(name='Internet', code='subscription').id

    def _operator_id(self):
        # Reuses the operator created in setUp (already has a configured
        # UssdCode) rather than creating a second, unconfigured 'Orange' row.
        return self.orange.id


@override_settings(
    CINETPAY_API_KEY='api-key',
    CINETPAY_SITE_ID='site-id',
    CINETPAY_NOTIFY_URL='https://api.example.com/api/payments/cinetpay/notify/',
    CINETPAY_RETURN_URL='https://app.example.com/payment/success',
    USE_NEW_TRANSACTION_ENGINE=True,
    # This class's tests request payment_method='auto' and mock
    # CinetPayProvider specifically - 'auto' must actually resolve to
    # cinetpay regardless of the ambient PAYMENT_PROVIDER_ORDER (see the
    # identical note on CinetPayFlowTests above).
    PAYMENT_PROVIDER_ORDER='cinetpay',
)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class NewTransactionEngineIntegrationTests(TestCase):
    """Cutover objectifs 1-5: full cycle with USE_NEW_TRANSACTION_ENGINE=True
    - creation -> Scheduler selection -> ReservationManager reservation ->
    execution -> result -> TransactionStateMachine -> TransactionEvent ->
    RetryManager when applicable. The "no eligible SIM" case (flag on) is
    covered separately here; the flag-off path's own operator-safety is
    covered by apps/devices/tests_cross_operator_gateway.py (business-model
    audit Phase 7.2)."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        # Business-model audit Phase 3: ExecuteTransactionView no longer
        # get_or_create()s Service by name either - pre-create it so
        # _execute()'s 'service': 'Internet' resolves instead of 400ing.
        Service.objects.create(name='Internet', code='subscription')
        # Gestion des opérateurs: USSD codes are DB-driven now - without this,
        # _execute()'s ExecuteTransactionView call would 400 on the new
        # preflight check (no UssdCode configured for a freshly-created
        # test operator/service pair).
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Défaut test',
            template='*456*{montant}#', is_active=True, is_default=True,
        )

    def _online_gateway(self, host, **kwargs):
        defaults = {'status': 'online', 'is_active': True, 'last_heartbeat': timezone.now()}
        defaults.update(kwargs)
        return Gateway.objects.create(name=f'Orange - {host}', host=host, **defaults)

    def _execute(self):
        return self.client.post(
            reverse('api_transaction_execute'),
            {'operator': 'Orange', 'service': 'Internet', 'operation': 'subscription', 'phone': '0700000099', 'amount': 1000},
            format='json',
        )

    def _last_event(self, tx, event_type):
        return tx.events.filter(event_type=event_type).order_by('-created_at').first()

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_scheduler_picks_a_heartbeat_sourced_sim_over_the_legacy_selector(self, create_payment, _redis_lock):
        """Objectif 3: the eligible GatewaySim comes from a real heartbeat
        POST (not created directly via the ORM) - proves heartbeat ->
        GatewayManager -> Scheduler is genuinely connected end to end."""
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(
            checkout_url='https://checkout.cinetpay.com/pay/tok', provider_transaction_id='tok', raw={},
        )
        # Online but operator-mismatched - what the old, pre-Phase-7.2 legacy
        # _select_gateway() would have grabbed instead, since it ignored
        # operator entirely.
        self._online_gateway('legacy-gateway')

        # Business-model audit Phase 7: heartbeat no longer auto-provisions a
        # Gateway from an unknown uuid - pre-enroll it and authenticate as it.
        mobile_gateway = Gateway.objects.create(name='Orange - mobile-1', host='')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=mobile_gateway.generate_secret())
        heartbeat = self.client.post(
            reverse('api_gateway_heartbeat_create'),
            {
                'status': 'online', 'gateway_uuid': 'mobile-1',
                'details': {
                    'uuid': 'mobile-1', 'phone_number': '0700000010', 'operator': 'Orange',
                    'battery_level': 80,
                    'sims': [{'slot': 0, 'operator': 'orange', 'msisdn': '0700000010'}],
                },
            },
            format='json',
        )
        self.assertEqual(heartbeat.status_code, 200)
        mobile_gateway.refresh_from_db()

        response = self._execute()
        self.assertEqual(response.status_code, 201)
        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertEqual(tx.gateway_id, mobile_gateway.id)

        attempt = tx.attempts.get(attempt_number=1)
        self.assertEqual(attempt.status, 'assigned')
        self.assertEqual(attempt.gateway_sim.gateway_id, mobile_gateway.id)
        event = self._last_event(tx, 'gateway_assigned')
        self.assertIsNotNone(event)
        self.assertEqual(event.metadata.get('mechanism'), 'scheduler')

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.verify_payment')
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_pending_transactions_expose_sim_slot_when_the_engine_reserved_one(self, create_payment, verify_payment, _redis_lock):
        """Mobile Phase C needs sim_slot to dial on the right physical SIM
        (see gateway_task_payload) - it must reflect the SIM the Scheduler
        actually reserved, not just any SIM on that gateway."""
        from apps.payments.providers.base import PaymentInitResult, PaymentStatusResult
        create_payment.return_value = PaymentInitResult(
            checkout_url='https://checkout.cinetpay.com/pay/tok', provider_transaction_id='tok', raw={},
        )
        gw = self._online_gateway('mobile-2', battery_level=80)
        GatewaySim.objects.create(gateway=gw, operator=self.orange, slot=1, msisdn='0700000020')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=gw.generate_secret())

        response = self._execute()
        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertEqual(tx.attempts.get(attempt_number=1).gateway_sim.slot, 1)

        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': tx.payment.reference}, format='json')

        pending = self.client.get(reverse('api_transaction_pending'), {'gateway_uuid': gw.host})
        self.assertEqual(pending.data[0]['sim_slot'], 1)

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_never_falls_back_to_an_operator_mismatched_gateway_when_no_sim_is_eligible(self, create_payment, _redis_lock):
        """Business-model audit Phase 3 (Blocage 3): an Orange transaction
        must never be assigned to a Gateway that has no Orange SIM, even as
        a fallback - the old _select_gateway() fallback here (operator-blind)
        is gone. The transaction is queued (gateway unset, next_retry_at
        scheduled) instead, reusing the exact same retry mechanism a failed
        dial already uses - no new scheduling system."""
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(
            checkout_url='https://checkout.cinetpay.com/pay/tok', provider_transaction_id='tok', raw={},
        )
        self._online_gateway('legacy-only')  # online, but no GatewaySim at all - must never be picked

        response = self._execute()
        self.assertEqual(response.status_code, 201)
        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertIsNone(tx.gateway_id, 'no eligible Orange SIM exists - must never land on any other Gateway')
        self.assertEqual(tx.attempts.count(), 0)
        self.assertIsNotNone(tx.next_retry_at, 'must be queued for a retry once a matching Gateway/SIM appears')
        event = self._last_event(tx, 'no_gateway_available')
        self.assertIsNotNone(event)
        self.assertEqual(event.metadata.get('mechanism'), 'queued_for_retry')
        self.assertIsNone(event.metadata.get('gateway_id'))

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.verify_payment')
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_full_cycle_failed_attempt_retries_on_a_different_sim_then_succeeds(self, create_payment, verify_payment, _redis_lock):
        """The validation target for objectifs 4 & 5: creation -> selection
        -> reservation -> execution -> resultat (echec) -> retry programme
        SANS marquer 'failed' -> dispatch_due_retries choisit l'AUTRE SIM
        (la premiere est exclue) -> resultat (succes) -> TransactionStateMachine
        -> TransactionEvent."""
        from apps.payments.providers.base import PaymentInitResult, PaymentStatusResult
        create_payment.return_value = PaymentInitResult(
            checkout_url='https://checkout.cinetpay.com/pay/tok', provider_transaction_id='tok', raw={},
        )
        gw1 = self._online_gateway('mobile-1', battery_level=80)
        gw2 = self._online_gateway('mobile-2', battery_level=80)
        GatewaySim.objects.create(gateway=gw1, operator=self.orange, slot=0, msisdn='0700000010')
        GatewaySim.objects.create(gateway=gw2, operator=self.orange, slot=0, msisdn='0700000020')

        # 1. creation -> selection -> reservation
        exec_response = self._execute()
        self.assertEqual(exec_response.status_code, 201)
        tx = Transaction.objects.get(reference=exec_response.data['reference'])
        first_gateway_id = tx.gateway_id
        self.assertIn(first_gateway_id, [gw1.id, gw2.id])

        # payment accepted -> transaction becomes actionable
        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        notify = self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': tx.payment.reference}, format='json')
        self.assertEqual(notify.status_code, 200)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'pending')

        first_gateway = Gateway.objects.get(pk=first_gateway_id)
        self.client.credentials(HTTP_X_GATEWAY_SECRET=first_gateway.generate_secret())
        pending = self.client.get(reverse('api_transaction_pending'), {'gateway_uuid': first_gateway.host})
        self.assertEqual(len(pending.data), 1)
        self.assertEqual(pending.data[0]['reference'], str(tx.reference))

        # 2. resultat (echec) -> retry programme, PAS de transition vers 'failed'
        fail_result = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': False, 'result': 'timeout'},
            format='json',
        )
        self.assertEqual(fail_result.status_code, 200)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'pending', 'a retryable failure must not terminally fail the transaction')
        self.assertIsNotNone(tx.next_retry_at)
        first_attempt = tx.attempts.get(attempt_number=1)
        self.assertEqual(first_attempt.status, 'failed')
        self.assertIsNotNone(self._last_event(tx, 'retry_scheduled'))

        # 3. RetryManager redispatche sur l'AUTRE SIM (la premiere est exclue)
        tx.next_retry_at = timezone.now() - timedelta(seconds=1)
        tx.save(update_fields=['next_retry_at'])
        results = RetryManager.dispatch_due_retries()
        second_attempt = results.get(tx.pk)
        self.assertIsNotNone(second_attempt, 'the other SIM must still be eligible for the retry')
        self.assertEqual(second_attempt.attempt_number, 2)
        self.assertNotEqual(second_attempt.gateway_sim.gateway_id, first_gateway_id)

        tx.refresh_from_db()
        self.assertEqual(tx.gateway_id, second_attempt.gateway_sim.gateway_id)
        second_gateway = second_attempt.gateway_sim.gateway

        # the retry is now visible to the NEW gateway's poll, not the old one -
        # each poll authenticates as the Gateway it claims to be, matching
        # business-model audit Phase 7's identity-is-the-secret rule.
        self.assertEqual(self.client.get(reverse('api_transaction_pending'), {'gateway_uuid': first_gateway.host}).data, [])
        self.client.credentials(HTTP_X_GATEWAY_SECRET=second_gateway.generate_secret())
        retried_pending = self.client.get(reverse('api_transaction_pending'), {'gateway_uuid': second_gateway.host})
        self.assertEqual(len(retried_pending.data), 1)

        # 4. resultat (succes) -> TransactionStateMachine -> TransactionEvent
        success_result = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': True, 'result': 'OK'},
            format='json',
        )
        self.assertEqual(success_result.status_code, 200)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success')
        second_attempt.refresh_from_db()
        self.assertEqual(second_attempt.status, 'success')
        event = self._last_event(tx, 'status_changed')
        self.assertIsNotNone(event)
        self.assertEqual(event.metadata.get('to_status'), 'success')

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.verify_payment')
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_retry_exhaustion_after_max_retry_marks_transaction_failed(self, create_payment, verify_payment, _redis_lock):
        """TXN_MAX_RETRY defaults to 3: the 3rd consecutive failure (attempts
        count reaches 3) must stop retrying and finally transition to
        'failed' - proving the loop terminates instead of retrying forever."""
        from apps.payments.providers.base import PaymentInitResult, PaymentStatusResult
        create_payment.return_value = PaymentInitResult(
            checkout_url='https://checkout.cinetpay.com/pay/tok', provider_transaction_id='tok', raw={},
        )
        gateways = [self._online_gateway(f'mobile-{i}', battery_level=80) for i in range(3)]
        for i, gw in enumerate(gateways):
            GatewaySim.objects.create(gateway=gw, operator=self.orange, slot=0, msisdn=f'070000001{i}')

        exec_response = self._execute()
        tx = Transaction.objects.get(reference=exec_response.data['reference'])
        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': tx.payment.reference}, format='json')

        for attempt_number in range(1, 4):
            # Business-model audit Phase 7: authenticate as whichever Gateway
            # currently holds the task (it changes on every retry) - a report
            # is only ever accepted from that Gateway (see tx.gateway_id
            # check in TransactionResultView).
            tx.refresh_from_db()
            current_gateway = Gateway.objects.get(pk=tx.gateway_id)
            self.client.credentials(HTTP_X_GATEWAY_SECRET=current_gateway.generate_secret())
            self.client.post(
                reverse('api_transaction_result'),
                {'transaction_reference': str(tx.reference), 'success': False, 'result': 'timeout'},
                format='json',
            )
            tx.refresh_from_db()
            if attempt_number < 3:
                self.assertEqual(tx.status, 'pending')
                self.assertIsNotNone(tx.next_retry_at)
                tx.next_retry_at = timezone.now() - timedelta(seconds=1)
                tx.save(update_fields=['next_retry_at'])
                attempt = RetryManager.dispatch_due_retries()[tx.pk]
                self.assertIsNotNone(attempt)
                tx.refresh_from_db()

        self.assertEqual(tx.status, 'failed')
        self.assertIsNone(tx.next_retry_at)
        self.assertEqual(tx.attempts.count(), 3)
        self.assertIsNotNone(self._last_event(tx, 'retry_exhausted'))

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.verify_payment')
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_duplicate_result_report_does_not_double_count_sim_stats_or_double_log(self, create_payment, verify_payment, _redis_lock):
        """Phase D audit (Critique n°3): the same USSD result posted twice
        (a realistic duplicate delivery on an unreliable mobile network)
        must never double-release the same TransactionAttempt - confirmed
        broken before this fix: GatewaySim.success_count got incremented
        twice for one real outcome."""
        from apps.payments.providers.base import PaymentInitResult, PaymentStatusResult
        create_payment.return_value = PaymentInitResult(
            checkout_url='https://checkout.cinetpay.com/pay/tok', provider_transaction_id='tok', raw={},
        )
        gw = self._online_gateway('mobile-1', battery_level=80)
        sim = GatewaySim.objects.create(gateway=gw, operator=self.orange, slot=0, msisdn='0700000010')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=gw.generate_secret())

        exec_response = self._execute()
        tx = Transaction.objects.get(reference=exec_response.data['reference'])
        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': tx.payment.reference}, format='json')

        payload = {'transaction_reference': str(tx.reference), 'success': True, 'result': 'OK'}
        first = self.client.post(reverse('api_transaction_result'), payload, format='json')
        self.assertEqual(first.status_code, 200)

        sim.refresh_from_db()
        self.assertEqual(sim.success_count, 1)
        event_count_after_first = tx.events.filter(event_type='status_changed').count()

        # Exact same result, reported again - simulates a retried/duplicate
        # delivery from the Gateway phone.
        second = self.client.post(reverse('api_transaction_result'), payload, format='json')
        self.assertEqual(second.status_code, 200, 'a duplicate report must never 500')

        sim.refresh_from_db()
        self.assertEqual(sim.success_count, 1, 'the duplicate must never double-increment the SIM counter')
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success')
        self.assertEqual(
            tx.events.filter(event_type='status_changed').count(), event_count_after_first,
            'the duplicate must never write a second status_changed event',
        )

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.verify_payment')
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_duplicate_result_with_a_conflicting_outcome_is_ignored_not_raced(self, create_payment, verify_payment, _redis_lock):
        """A second, contradicting result (e.g. a stale retry from the
        Gateway arriving after the real outcome was already reported) must
        never overwrite an already-terminal Transaction.status."""
        from apps.payments.providers.base import PaymentInitResult, PaymentStatusResult
        create_payment.return_value = PaymentInitResult(
            checkout_url='https://checkout.cinetpay.com/pay/tok', provider_transaction_id='tok', raw={},
        )
        gw = self._online_gateway('mobile-1', battery_level=80)
        GatewaySim.objects.create(gateway=gw, operator=self.orange, slot=0, msisdn='0700000010')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=gw.generate_secret())

        exec_response = self._execute()
        tx = Transaction.objects.get(reference=exec_response.data['reference'])
        verify_payment.return_value = PaymentStatusResult(status='accepted', raw={'data': {'status': 'ACCEPTED'}})
        self.client.post(reverse('api_cinetpay_notify'), {'transaction_id': tx.payment.reference}, format='json')

        first = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': True, 'result': 'OK'},
            format='json',
        )
        self.assertEqual(first.status_code, 200)

        conflicting = self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(tx.reference), 'success': False, 'result': 'timeout'},
            format='json',
        )
        self.assertEqual(conflicting.status_code, 200, 'a stale conflicting report must be ignored, not crash')

        tx.refresh_from_db()
        self.assertEqual(tx.status, 'success', 'the real, already-committed outcome must never be overwritten')

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_reservation_is_released_when_payment_initiation_fails(self, create_payment, _redis_lock):
        """A Scheduler reservation must not be left dangling ('assigned'
        forever, silently eating that SIM's capacity) if PaymentService never
        actually gets to send anything - see the release() call added next
        to the existing PaymentProviderError handling in ExecuteTransactionView."""
        from apps.payments.providers.base import PaymentProviderError
        create_payment.side_effect = PaymentProviderError('sandbox unreachable')
        gw = self._online_gateway('mobile-1', battery_level=80)
        GatewaySim.objects.create(gateway=gw, operator=self.orange, slot=0, msisdn='0700000010')

        response = self._execute()
        self.assertEqual(response.status_code, 502)
        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertEqual(tx.status, 'failed')
        attempt = tx.attempts.get(attempt_number=1)
        self.assertEqual(attempt.status, 'failed')


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
class TransactionResultViewAttemptDataTests(TestCase):
    """Business-model audit, Phase 2: TransactionResultView must record what
    the Gateway actually reported on TransactionAttempt (raw_response,
    failure_reason) before releasing the reservation - RetryManager reads
    failure_reason right after release() to decide retry eligibility (see
    NON_RETRYABLE_FAILURE_REASONS), so it must already be set by then.

    USE_NEW_TRANSACTION_ENGINE=True here is a per-test Django settings
    override (same mechanism NewTransactionEngineIntegrationTests already
    uses) - it does not touch .env or the real running configuration, it is
    only how this code path (attempt is not None) becomes reachable to test
    it at all."""

    def setUp(self):
        self.client = APIClient()
        self.device = Device.objects.create(uid='client-app', primary_phone='0700000001')
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        self.gateway = Gateway.objects.create(name='Orange - mobile-1', host='mobile-1', status='online')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.gateway.generate_secret())
        self.sim = GatewaySim.objects.create(gateway=self.gateway, operator=self.orange, slot=0)
        self.tx = Transaction.objects.create(
            device=self.device, service=self.internet, operator=self.orange, gateway=self.gateway,
            phone_number='0700000001', amount=1000, status='pending',
        )
        self.attempt = TransactionAttempt.objects.create(
            transaction=self.tx, gateway_sim=self.sim, attempt_number=1, status='dispatched',
        )

    def _report(self, success, result):
        return self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(self.tx.reference), 'success': success, 'result': result},
            format='json',
        )

    def test_success_records_raw_response_and_leaves_failure_reason_blank(self):
        response = self._report(True, 'OK')
        self.assertEqual(response.status_code, 200)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.raw_response, 'OK')
        self.assertEqual(self.attempt.failure_reason, '')

    def test_failure_records_raw_response_and_classifies_it(self):
        response = self._report(False, 'Solde insuffisant')
        self.assertEqual(response.status_code, 200)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.raw_response, 'Solde insuffisant')
        self.assertEqual(self.attempt.failure_reason, 'insufficient_balance')

    def test_invalid_number_is_classified_correctly(self):
        self._report(False, 'Numero invalide')
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.failure_reason, 'invalid_number')

    def test_unrecognized_text_defaults_to_unknown_never_blank_on_failure(self):
        self._report(False, 'some unexpected native error string')
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.failure_reason, 'unknown')

    def test_a_retryable_failure_reason_still_allows_a_retry(self):
        self._report(False, 'network error')
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.failure_reason, 'network_error')
        self.tx.refresh_from_db()
        self.assertIsNotNone(self.tx.next_retry_at, 'network_error is retryable - a retry must be scheduled')

    def test_invalid_number_forbids_any_retry(self):
        self._report(False, 'Numero invalide')
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.failure_reason, 'invalid_number')
        self.tx.refresh_from_db()
        self.assertIsNone(self.tx.next_retry_at, 'invalid_number must never be retried')
        self.assertEqual(self.tx.status, 'failed')


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
class LateResultAfterExpiryTests(TestCase):
    """Business-model audit Phase 3 (Blocage 1): a Gateway that goes silent
    long enough for release_expired() to presume a timeout, but that later
    *does* report the real outcome, must never have that real result thrown
    away - and must never be double-counted or double-retried either."""

    def setUp(self):
        self.client = APIClient()
        self.device = Device.objects.create(uid='client-app', primary_phone='0700000001')
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        self.gateway = Gateway.objects.create(name='Orange - mobile-1', host='mobile-1', status='online')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.gateway.generate_secret())
        self.sim = GatewaySim.objects.create(gateway=self.gateway, operator=self.orange, slot=0)
        self.tx = Transaction.objects.create(
            device=self.device, service=self.internet, operator=self.orange, gateway=self.gateway,
            phone_number='0700000001', amount=1000, status='pending',
        )
        self.attempt = TransactionAttempt.objects.create(
            transaction=self.tx, gateway_sim=self.sim, attempt_number=1, status='dispatched',
        )
        # 1. TransactionAttempt created (setUp) - 2. render it expired:
        TransactionAttempt.objects.filter(pk=self.attempt.pk).update(
            created_at=timezone.now() - timedelta(seconds=99999),
        )

    def _report(self, success, result):
        return self.client.post(
            reverse('api_transaction_result'),
            {'transaction_reference': str(self.tx.reference), 'success': success, 'result': result},
            format='json',
        )

    def test_release_expired_classifies_as_timeout_and_schedules_a_retry(self):
        # 3. call release_expired()
        released = ReservationManager.release_expired()
        self.assertEqual(released, 1)

        self.attempt.refresh_from_db()
        self.tx.refresh_from_db()
        # 4. state of the transaction
        self.assertEqual(self.attempt.status, 'expired')
        self.assertEqual(self.attempt.failure_reason, 'timeout')
        self.assertEqual(self.tx.status, 'pending', 'a mere timeout must never terminally fail the transaction')
        # 5. next_retry_at
        self.assertIsNotNone(self.tx.next_retry_at, 'a retryable timeout must get a retry scheduled immediately')

    def test_late_success_is_accepted_and_resolves_the_transaction(self):
        ReservationManager.release_expired()

        # 6. send a late result (the real outcome: it actually succeeded)
        response = self._report(True, 'OK')

        # 7. correctly processed per the idempotency rule - a late success
        # for a transaction not yet resolved by anything else is accepted.
        self.assertEqual(response.status_code, 200)
        self.tx.refresh_from_db()
        self.attempt.refresh_from_db()
        self.assertEqual(self.tx.status, 'success')
        self.assertIsNone(self.tx.next_retry_at, 'the retry scheduled at expiry time must be cancelled')
        self.assertEqual(self.attempt.status, 'success')
        self.assertEqual(self.attempt.raw_response, 'OK')
        self.sim.refresh_from_db()
        # Never double-counted: release_expired() already counted one
        # failure on this SIM when it presumed a timeout - the late success
        # correction does not call ReservationManager.release() again, so it
        # adds no second increment (a known, documented trade-off: the SIM's
        # score reflects one stale failure rather than the true success).
        self.assertEqual(self.sim.success_count, 0)
        self.assertEqual(self.sim.failure_count, 1)

    def test_a_second_late_report_after_success_is_fully_idempotent(self):
        ReservationManager.release_expired()
        self._report(True, 'OK')
        self.sim.refresh_from_db()
        failure_count_after_first = self.sim.failure_count
        success_count_after_first = self.sim.success_count

        # 8. no double processing - a second, duplicate late report for an
        # already-resolved transaction must change nothing.
        second = self._report(True, 'OK')

        self.assertEqual(second.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'success')
        self.sim.refresh_from_db()
        self.assertEqual(self.sim.failure_count, failure_count_after_first)
        self.assertEqual(self.sim.success_count, success_count_after_first)

    def test_late_failure_corrects_the_record_without_scheduling_a_second_retry(self):
        ReservationManager.release_expired()
        self.tx.refresh_from_db()
        retry_at_from_expiry = self.tx.next_retry_at
        self.assertIsNotNone(retry_at_from_expiry)

        response = self._report(False, 'Numero invalide')

        self.assertEqual(response.status_code, 200)
        self.attempt.refresh_from_db()
        self.tx.refresh_from_db()
        self.assertEqual(self.attempt.status, 'failed')
        self.assertEqual(self.attempt.failure_reason, 'invalid_number')
        # The transaction stays 'pending' with the retry already scheduled
        # at expiry time - never a second retry_scheduled decision here.
        self.assertEqual(self.tx.status, 'pending')
        self.assertEqual(self.tx.next_retry_at, retry_at_from_expiry)
        self.assertEqual(
            self.tx.events.filter(event_type='retry_scheduled').count(), 1,
            'exactly one retry decision must exist - the one made at expiry time',
        )
        self.assertEqual(self.tx.events.filter(event_type='late_result_after_expiry').count(), 1)


@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class ExecuteTransactionViewUssdPreflightTests(TestCase):
    """Gestion des opérateurs: proves the preflight check in
    ExecuteTransactionView actually prevents the regression identified while
    planning this module - build_ussd_code() now raises when nothing is
    configured, but by the time it used to be called (inside
    transaction_payload(), after PaymentService.initiate() already talked to
    CinetPay) that would have orphaned a real payment session. The check
    must reject the request BEFORE any provider call happens."""

    def setUp(self):
        self.client = APIClient()

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_unconfigured_operator_service_is_rejected_before_any_payment_call(self, create_payment, _redis_lock):
        response = self.client.post(
            reverse('api_transaction_execute'),
            {
                # Short names: ExecuteTransactionView derives Operator.code
                # from this string (max_length=10) when it doesn't exist yet.
                'operator': 'Zorro',
                'service': 'Nouveau',
                'operation': 'subscription',
                'phone': '0700000001',
                'amount': 1000,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        create_payment.assert_not_called()
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    # 'auto' (the client default) must actually resolve to cinetpay here,
    # regardless of the ambient PAYMENT_PROVIDER_ORDER - see the identical
    # note on CinetPayFlowTests above.
    @override_settings(PAYMENT_PROVIDER_ORDER='cinetpay')
    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_configured_operator_service_still_succeeds(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(
            checkout_url='https://checkout.cinetpay.com/pay/tok', provider_transaction_id='tok', raw={},
        )
        orange = Operator.objects.create(name='Orange', code='orange')
        # Business-model audit Phase 3: no more get_or_create(name=...) for
        # Service either - pre-create it so this "already configured" case
        # actually resolves instead of 400ing on an unknown service name.
        Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=orange, service=None, label='Défaut test',
            template='*456*{montant}#', is_active=True, is_default=True,
        )

        response = self.client.post(
            reverse('api_transaction_execute'),
            {'operator': 'Orange', 'service': 'Internet', 'operation': 'subscription', 'phone': '0700000001', 'amount': 1000},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        create_payment.assert_called_once()


class TransactionStatusViewTests(TestCase):
    """P0-2: the only channel the Flutter Client has to learn what actually
    happened to a transaction after opening the payment checkout URL."""

    def setUp(self):
        self.client = APIClient()
        self.device = Device.objects.create(uid='client-app', primary_phone='0700000001')
        self.operator = Operator.objects.create(name='Orange', code='orange')
        self.service = Service.objects.create(name='Internet', code='internet')

    def _transaction(self, status, payment_status='accepted'):
        payment = Payment.objects.create(method='cinetpay', reference=f'PAY-{status}', amount=1000, status=payment_status)
        return Transaction.objects.create(
            device=self.device, service=self.service, operator=self.operator,
            phone_number='0700000001', amount=1000, status=status,
            payment=payment, payment_method='cinetpay', payment_reference=payment.reference,
        )

    def test_pending_transaction(self):
        tx = self._transaction('pending', payment_status='pending')
        response = self.client.get(reverse('api_transaction_status', args=[tx.reference]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'pending')
        self.assertEqual(response.data['reference'], str(tx.reference))
        self.assertTrue(response.data['is_pending'])
        self.assertFalse(response.data['is_success'])
        self.assertFalse(response.data['is_failed'])
        self.assertFalse(response.data['is_cancelled'])

    def test_processing_transaction_is_still_pending(self):
        tx = self._transaction('processing')
        response = self.client.get(reverse('api_transaction_status', args=[tx.reference]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_pending'], 'processing is not yet resolved - still "in flight" to the client')

    def test_success_transaction(self):
        tx = self._transaction('success')
        response = self.client.get(reverse('api_transaction_status', args=[tx.reference]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_success'])
        self.assertFalse(response.data['is_pending'])
        self.assertFalse(response.data['is_failed'])
        self.assertFalse(response.data['is_cancelled'])

    def test_failed_transaction(self):
        tx = self._transaction('failed')
        response = self.client.get(reverse('api_transaction_status', args=[tx.reference]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_failed'])
        self.assertFalse(response.data['is_pending'])
        self.assertFalse(response.data['is_success'])

    def test_cancelled_transaction(self):
        tx = self._transaction('cancelled')
        response = self.client.get(reverse('api_transaction_status', args=[tx.reference]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_cancelled'])
        self.assertFalse(response.data['is_pending'])

    def test_unknown_reference_returns_404(self):
        response = self.client.get(reverse('api_transaction_status', args=['does-not-exist']))
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', response.data)

    def test_response_reuses_the_same_fields_as_transaction_payload(self):
        tx = self._transaction('success')
        response = self.client.get(reverse('api_transaction_status', args=[tx.reference]))
        for field in ('id', 'reference', 'operator', 'service', 'amount', 'payment_method', 'checkout_url'):
            self.assertIn(field, response.data)

    def test_also_reachable_under_the_gateway_prefix(self):
        # apps.devices.urls is mounted at both /api/ and /api/gateway/ -
        # confirm this new route follows the same existing convention as
        # every other route in this file, not a new inconsistency.
        tx = self._transaction('success')
        response = self.client.get(f'/api/gateway/transactions/{tx.reference}/status/')
        self.assertEqual(response.status_code, 200)


class OperatorServiceListViewTests(TestCase):
    """P1: the Flutter Client's operator/service pickers must reflect the
    dashboard's is_active toggle instead of a hardcoded list."""

    def setUp(self):
        self.client = APIClient()

    def test_only_active_operators_are_listed(self):
        Operator.objects.create(name='Orange', code='orange', is_active=True)
        Operator.objects.create(name='Camtel', code='camtel', is_active=False)
        response = self.client.get(reverse('api_operators'))
        self.assertEqual(response.status_code, 200)
        names = [item['name'] for item in response.data]
        self.assertIn('Orange', names)
        self.assertNotIn('Camtel', names)

    def test_operator_fields(self):
        operator = Operator.objects.create(name='Orange', code='orange', is_active=True)
        response = self.client.get(reverse('api_operators'))
        self.assertEqual(response.data, [{'id': operator.id, 'name': 'Orange', 'code': 'orange'}])

    def test_no_active_operators_returns_empty_list(self):
        Operator.objects.create(name='Orange', code='orange', is_active=False)
        response = self.client.get(reverse('api_operators'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_only_active_services_are_listed(self):
        Service.objects.create(name='Internet', code='internet', is_active=True)
        Service.objects.create(name='Ancien forfait', code='old', is_active=False)
        response = self.client.get(reverse('api_services'))
        self.assertEqual(response.status_code, 200)
        names = [item['name'] for item in response.data]
        self.assertIn('Internet', names)
        self.assertNotIn('Ancien forfait', names)

    def test_service_fields(self):
        service = Service.objects.create(name='Internet', code='internet', is_active=True)
        response = self.client.get(reverse('api_services'))
        self.assertEqual(response.data, [{'id': service.id, 'name': 'Internet', 'code': 'internet'}])

    def test_no_active_services_returns_empty_list(self):
        Service.objects.create(name='Internet', code='internet', is_active=False)
        response = self.client.get(reverse('api_services'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_operators_also_reachable_under_the_gateway_prefix(self):
        Operator.objects.create(name='Orange', code='orange', is_active=True)
        response = self.client.get('/api/gateway/operators/')
        self.assertEqual(response.status_code, 200)


class AmountListViewTests(TestCase):
    """Business-model audit: lets the Flutter Client know which montants
    have a dedicated UssdCode for a given (operator, service) - an empty
    list means "no fixed catalog, free amount entry is fine"."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')

    def _url(self, operator_id, service_id):
        return reverse('api_amounts', args=[operator_id, service_id])

    def test_lists_configured_amounts_in_ascending_order(self):
        UssdCode.objects.create(operator=self.orange, service=self.internet, amount=1000, label='1000F', template='*456*4*2#')
        UssdCode.objects.create(operator=self.orange, service=self.internet, amount=500, label='500F', template='*456*4*1#')
        response = self.client.get(self._url(self.orange.id, self.internet.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [{'amount': 500.0}, {'amount': 1000.0}])

    def test_generic_amount_null_row_is_never_listed_as_an_amount(self):
        UssdCode.objects.create(operator=self.orange, service=self.internet, amount=None, label='Générique', template='*456*{montant}#')
        response = self.client.get(self._url(self.orange.id, self.internet.id))
        self.assertEqual(response.data, [])

    def test_inactive_amount_specific_rows_are_excluded(self):
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500, label='500F',
            template='*456*4*1#', is_active=False,
        )
        response = self.client.get(self._url(self.orange.id, self.internet.id))
        self.assertEqual(response.data, [])

    def test_no_configuration_returns_an_empty_list_not_an_error(self):
        response = self.client.get(self._url(self.orange.id, self.internet.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_nonexistent_operator_or_service_returns_an_empty_list_not_a_404(self):
        response = self.client.get(self._url(999999, 999999))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_amounts_are_scoped_to_the_requested_operator(self):
        mtn = Operator.objects.create(name='MTN', code='mtn')
        UssdCode.objects.create(operator=self.orange, service=self.internet, amount=500, label='Orange 500F', template='*456*4*1#')
        response = self.client.get(self._url(mtn.id, self.internet.id))
        self.assertEqual(response.data, [])


@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class ExecuteTransactionViewIdContractTests(TestCase):
    """Business-model audit Phase 3: operator_id/service_id become the
    authoritative contract; a name is still accepted transitionally but
    never auto-creates a catalog row anymore."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, amount=500, label='500F', template='*456*4*1#',
        )

    def _execute(self, **overrides):
        payload = {'phone': '0700000001', 'amount': 500}
        payload.update(overrides)
        return self.client.post(reverse('api_transaction_execute'), payload, format='json')

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_operator_id_and_service_id_are_accepted_and_prioritised(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

        response = self._execute(operator_id=self.orange.id, service_id=self.internet.id)

        self.assertEqual(response.status_code, 201)
        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertEqual(tx.operator_id, self.orange.id)
        self.assertEqual(tx.service_id, self.internet.id)

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_transaction_records_which_ussd_code_was_used(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})
        expected_code = UssdCode.objects.get(amount=500)

        response = self._execute(operator_id=self.orange.id, service_id=self.internet.id)

        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertEqual(tx.ussd_code_used_id, expected_code.id)

    def test_nonexistent_operator_id_is_rejected(self, _redis_lock):
        response = self._execute(operator_id=999999, service_id=self.internet.id)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_nonexistent_service_id_is_rejected(self, _redis_lock):
        response = self._execute(operator_id=self.orange.id, service_id=999999)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_inactive_operator_id_is_rejected(self, _redis_lock):
        self.orange.is_active = False
        self.orange.save(update_fields=['is_active'])
        response = self._execute(operator_id=self.orange.id, service_id=self.internet.id)
        self.assertEqual(response.status_code, 404)

    def test_inactive_service_id_is_rejected(self, _redis_lock):
        self.internet.is_active = False
        self.internet.save(update_fields=['is_active'])
        response = self._execute(operator_id=self.orange.id, service_id=self.internet.id)
        self.assertEqual(response.status_code, 404)

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_legacy_name_contract_is_still_accepted_transitionally(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

        response = self._execute(operator='Orange', service='Internet')

        self.assertEqual(response.status_code, 201)

    def test_legacy_name_contract_logs_its_transitional_usage(self, _redis_lock):
        with self.assertLogs('apps.devices.views', level='WARNING') as logs:
            self._execute(operator='Orange', service='Internet')
        self.assertTrue(any('transitional operator name lookup' in message for message in logs.output))
        self.assertTrue(any('transitional service name lookup' in message for message in logs.output))

    def test_an_unknown_name_no_longer_silently_creates_an_operator(self, _redis_lock):
        """The dangerous behavior the audit flagged: get_or_create(name=...)
        used to spawn a permanent, active Operator row from any client-sent
        string. It must now be rejected instead."""
        response = self._execute(operator='Zorro Telecom', service='Internet')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Operator.objects.filter(name='Zorro Telecom').exists())

    def test_an_unknown_service_name_no_longer_silently_creates_a_service(self, _redis_lock):
        response = self._execute(operator='Orange', service='Nouveau Forfait')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Service.objects.filter(name='Nouveau Forfait').exists())

    def test_an_inactive_operator_name_is_rejected_on_the_legacy_path(self, _redis_lock):
        self.orange.is_active = False
        self.orange.save(update_fields=['is_active'])
        response = self._execute(operator='Orange', service='Internet')
        self.assertEqual(response.status_code, 400)


class PendingTransactionsViewUssdDegradationTests(TestCase):
    """Gestion des opérateurs: one transaction with a broken/deactivated
    UssdCode must never break polling for every other pending transaction -
    it's skipped and logged, not a 500 for the whole batch."""

    def setUp(self):
        self.client = APIClient()
        self.device = Device.objects.create(uid='client-app', primary_phone='0700000001')
        self.gateway = Gateway.objects.create(name='Orange - 0700000000', host='gateway-1', status='online')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.gateway.generate_secret())
        self.orange = Operator.objects.create(name='Orange', code='orange')
        # Business-model audit Phase 7: PendingTransactionsView's operator
        # cross-check (ambient USE_NEW_TRANSACTION_ENGINE=True from the local
        # .env, unrelated to this test's own concern) requires the
        # authenticated Gateway to actually have a matching active SIM.
        GatewaySim.objects.create(gateway=self.gateway, operator=self.orange, slot=0)
        # Two distinct services so each transaction can have its own
        # independent UssdCode - deactivating one must not affect the other.
        self.internet = Service.objects.create(name='Internet', code='subscription')
        self.sms = Service.objects.create(name='SMS', code='sms')
        self.payment_ok = Payment.objects.create(method='cinetpay', reference='PAY-OK', amount=1000, status='accepted')
        self.payment_broken = Payment.objects.create(method='cinetpay', reference='PAY-BROKEN', amount=1000, status='accepted')

    def _pending_tx(self, payment, service, reference_suffix):
        return Transaction.objects.create(
            device=self.device, service=service, operator=self.orange, gateway=self.gateway,
            phone_number='0700000001', amount=1000, status='pending',
            payment=payment, payment_method='cinetpay', payment_reference=f'PAY-{reference_suffix}',
        )

    def test_a_transaction_with_no_configured_ussd_code_is_skipped_not_500(self):
        UssdCode.objects.create(
            operator=self.orange, service=self.internet, label='Internet',
            template='*456*{montant}#', is_active=True,
        )
        broken_code = UssdCode.objects.create(
            operator=self.orange, service=self.sms, label='SMS',
            template='*456*{montant}#', is_active=True,
        )
        valid_tx = self._pending_tx(self.payment_ok, self.internet, 'OK')
        broken_tx = self._pending_tx(self.payment_broken, self.sms, 'BROKEN')
        broken_code.delete()  # nothing configured for (orange, sms) anymore - internet is untouched

        response = self.client.get(reverse('api_transaction_pending'))
        self.assertEqual(response.status_code, 200)
        references = [item['reference'] for item in response.data]
        self.assertIn(str(valid_tx.reference), references)
        self.assertNotIn(str(broken_tx.reference), references)


class SmsGatewayTests(TestCase):
    """SMS jobs (currently OTP codes - see apps.accounts) are polled and
    reported by the Android Gateway exactly like USSD transactions."""

    def setUp(self):
        self.client = APIClient()
        self.gateway = Gateway.objects.create(name='Orange - 0700000000', host='gateway-1', status='online')
        self.client.credentials(HTTP_X_GATEWAY_SECRET=self.gateway.generate_secret())

    def test_pending_sms_are_listed_for_any_gateway_to_pick_up(self):
        from apps.devices.models import SmsTask

        SmsTask.objects.create(phone_number='+2250700000001', message='code: 123456', purpose='otp')

        response = self.client.get(reverse('api_sms_pending'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['phone_number'], '+2250700000001')
        self.assertEqual(response.data[0]['purpose'], 'otp')

    def test_reporting_success_marks_the_task_sent_and_records_the_gateway(self):
        from apps.devices.models import SmsTask

        task = SmsTask.objects.create(phone_number='+2250700000002', message='code: 123456', purpose='otp')

        response = self.client.post(
            reverse('api_sms_result'),
            {'id': task.id, 'success': True, 'gateway_uuid': 'gateway-1'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, 'sent')
        self.assertEqual(task.gateway_id, self.gateway.id)
        self.assertIsNotNone(task.sent_at)

        # a sent task must not be handed out again
        self.assertEqual(len(self.client.get(reverse('api_sms_pending')).data), 0)

    def test_reporting_failure_marks_the_task_failed(self):
        from apps.devices.models import SmsTask

        task = SmsTask.objects.create(phone_number='+2250700000003', message='code: 123456', purpose='otp')
        response = self.client.post(reverse('api_sms_result'), {'id': task.id, 'success': False}, format='json')
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, 'failed')


class DispatchDueTransactionRetriesCommandTests(TestCase):
    """Phase D audit (Critique - retry dispatch never wired to a scheduler):
    apps/devices/management/commands/dispatch_due_transaction_retries.py is
    the missing cron entry point for RetryManager.dispatch_due_retries()/
    ReservationManager.release_expired() - both already fully tested at the
    unit level (apps/core/tests.py, apps/devices/services/tests.py), so
    these tests only prove the command wires them up correctly, not their
    internal logic again."""

    def setUp(self):
        self.device = Device.objects.create(uid='client-app', primary_phone='0700000001')
        self.service = Service.objects.create(name='Internet', code='subscription')
        self.orange = Operator.objects.create(name='Orange', code='orange')

    def test_dispatches_a_due_retry_to_a_freshly_selected_sim(self):
        gw1 = Gateway.objects.create(name='GW1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        gw2 = Gateway.objects.create(name='GW2', host='gw2', status='online', is_active=True, last_heartbeat=timezone.now())
        sim1 = GatewaySim.objects.create(gateway=gw1, operator=self.orange, slot=0)
        GatewaySim.objects.create(gateway=gw2, operator=self.orange, slot=0)

        tx = Transaction.objects.create(
            device=self.device, service=self.service, operator=self.orange,
            phone_number='0700000001', amount=1000, status='pending',
            next_retry_at=timezone.now() - timedelta(seconds=1),
        )
        # A prior failed attempt on gw1's SIM - the retry must land elsewhere.
        TransactionAttempt.objects.create(
            transaction=tx, attempt_number=1, gateway_sim=sim1, status='failed',
        )

        out = StringIO()
        call_command('dispatch_due_transaction_retries', stdout=out)

        tx.refresh_from_db()
        self.assertIsNone(tx.next_retry_at)
        self.assertEqual(tx.attempts.count(), 2)
        new_attempt = tx.attempts.get(attempt_number=2)
        self.assertEqual(tx.gateway_id, new_attempt.gateway_sim.gateway_id)
        self.assertNotEqual(new_attempt.gateway_sim_id, sim1.id)
        self.assertIn('1 due retry(ies) processed: 1 dispatched', out.getvalue())
        # Business-model audit Phase 3 (Blocage 2): the earlier attempt stays
        # historical, untouched by the new dispatch - never overwritten.
        previous_attempt = tx.attempts.get(attempt_number=1)
        self.assertEqual(previous_attempt.status, 'failed')
        self.assertEqual(previous_attempt.gateway_sim_id, sim1.id)

    def test_reports_when_no_gateway_is_available(self):
        tx = Transaction.objects.create(
            device=self.device, service=self.service, operator=self.orange,
            phone_number='0700000001', amount=1000, status='pending',
            next_retry_at=timezone.now() - timedelta(seconds=1),
        )

        out = StringIO()
        call_command('dispatch_due_transaction_retries', stdout=out)

        self.assertIn('0 dispatched, 1 with no gateway available', out.getvalue())
        # Business-model audit Phase 3 (Blocage 3): must not be orphaned -
        # requeued so the next sweep checks again once a Gateway/SIM for
        # this operator appears, instead of never being reconsidered.
        tx.refresh_from_db()
        self.assertIsNotNone(tx.next_retry_at, 'a transaction with no eligible Gateway must stay queued, not orphaned')

    def test_releases_expired_reservations_before_dispatching(self):
        gateway = Gateway.objects.create(name='GW1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        sim = GatewaySim.objects.create(gateway=gateway, operator=self.orange, slot=0)
        tx = Transaction.objects.create(
            device=self.device, service=self.service, operator=self.orange,
            phone_number='0700000001', amount=1000, status='pending',
        )
        stale_attempt = TransactionAttempt.objects.create(
            transaction=tx, attempt_number=1, gateway_sim=sim, status='dispatched',
        )
        TransactionAttempt.objects.filter(pk=stale_attempt.pk).update(
            created_at=timezone.now() - timedelta(seconds=9999),
        )

        out = StringIO()
        call_command('dispatch_due_transaction_retries', stdout=out)

        stale_attempt.refresh_from_db()
        self.assertEqual(stale_attempt.status, 'expired')
        self.assertIn('1 expired reservation(s) released', out.getvalue())


@override_settings(USE_NEW_TRANSACTION_ENGINE=True)
@patch('apps.payments.services.payment_service.redis_lock', return_value=nullcontext())
class NoCrossOperatorGatewayTests(TestCase):
    """Business-model audit Phase 3 (Blocage 3): an Orange transaction must
    never be assigned to an MTN (or any other non-Orange) Gateway, not even
    as a fallback when no Orange Gateway/SIM is currently eligible."""

    def setUp(self):
        self.client = APIClient()
        self.orange = Operator.objects.create(name='Orange', code='orange')
        self.mtn = Operator.objects.create(name='MTN', code='mtn')
        self.internet = Service.objects.create(name='Internet', code='subscription')
        UssdCode.objects.create(
            operator=self.orange, service=None, label='Défaut Orange',
            template='*456*{montant}#', is_active=True, is_default=True,
        )

    def _execute(self):
        return self.client.post(
            reverse('api_transaction_execute'),
            {'operator': 'Orange', 'service': 'Internet', 'operation': 'subscription', 'phone': '0700000001', 'amount': 1000},
            format='json',
        )

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_orange_transaction_with_an_eligible_orange_gateway_selects_orange(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})
        orange_gw = Gateway.objects.create(name='Orange - gw1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        GatewaySim.objects.create(gateway=orange_gw, operator=self.orange, slot=0)

        response = self._execute()

        self.assertEqual(response.status_code, 201)
        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertEqual(tx.gateway_id, orange_gw.id)

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_mtn_gateway_available_is_never_selected_for_an_orange_transaction(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})
        mtn_gw = Gateway.objects.create(name='MTN - gw1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        GatewaySim.objects.create(gateway=mtn_gw, operator=self.mtn, slot=0)
        # No Orange Gateway/SIM exists at all - only the MTN one above.

        response = self._execute()

        self.assertEqual(response.status_code, 201)
        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertNotEqual(tx.gateway_id, mtn_gw.id, 'an Orange transaction must never land on an MTN Gateway')
        self.assertIsNone(tx.gateway_id, 'queued, not assigned to any mismatched Gateway')
        self.assertIsNotNone(tx.next_retry_at)

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_no_gateway_at_all_is_queued_not_failed(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

        response = self._execute()

        self.assertEqual(response.status_code, 201, 'payment still proceeds - dispatch is queued, not a hard failure')
        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertIsNone(tx.gateway_id)
        self.assertEqual(tx.status, 'pending')
        self.assertIsNotNone(tx.next_retry_at)

    @patch('apps.payments.providers.cinetpay.CinetPayProvider.create_payment')
    def test_transaction_recovers_once_a_matching_gateway_becomes_available(self, create_payment, _redis_lock):
        from apps.payments.providers.base import PaymentInitResult
        create_payment.return_value = PaymentInitResult(checkout_url='https://pay/tok', provider_transaction_id='tok', raw={})

        # No Orange Gateway yet - queued.
        response = self._execute()
        tx = Transaction.objects.get(reference=response.data['reference'])
        self.assertIsNone(tx.gateway_id)

        # An Orange Gateway shows up, and the queued retry becomes due.
        orange_gw = Gateway.objects.create(name='Orange - gw1', host='gw1', status='online', is_active=True, last_heartbeat=timezone.now())
        GatewaySim.objects.create(gateway=orange_gw, operator=self.orange, slot=0)
        tx.next_retry_at = timezone.now() - timedelta(seconds=1)
        tx.save(update_fields=['next_retry_at'])

        out = StringIO()
        call_command('dispatch_due_transaction_retries', stdout=out)

        tx.refresh_from_db()
        self.assertEqual(tx.gateway_id, orange_gw.id, 'now recoverable once a matching Gateway/SIM exists')
        self.assertEqual(tx.attempts.count(), 1)
        self.assertIsNone(tx.next_retry_at)
