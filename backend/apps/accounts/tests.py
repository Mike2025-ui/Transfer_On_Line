from unittest import mock, skipUnless

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView

from apps.accounts.services import AionError, OtpError, request_otp, verify_otp

User = get_user_model()


class _WhoAmIView(APIView):
    """Minimal protected view used only to prove a token issued by
    VerifyOtpView is actually accepted by JWTAuthentication end-to-end."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'username': request.user.username})


class _FakeResponse:
    """Minimal stand-in for requests.Response, just enough for
    apps.accounts.services._aion_post's own handling."""

    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        self._json_data = {'success': True} if json_data is None else json_data
        self.text = text if text is not None else str(self._json_data)

    def json(self):
        return self._json_data


AION_SETTINGS = {'AION_API_KEY': 'sk_test_secret_do_not_leak', 'AION_SENDER_ID': 'TRANSFERON'}


@override_settings(**AION_SETTINGS)
class RequestOtpServiceTests(TestCase):
    """request_otp() talks exclusively to POST /verify/start - Aion
    Messaging is the sole OTP provider, there is no local generation/mock
    path (see apps.accounts.services's module doc)."""

    def test_calls_verify_start_with_the_documented_body_and_header(self):
        with mock.patch(
            'apps.accounts.services.requests.post',
            return_value=_FakeResponse(json_data={'success': True, 'verification_id': 42}),
        ) as fake_post:
            verification_id = request_otp('+2250700000001')

        self.assertEqual(verification_id, 42)
        fake_post.assert_called_once()
        args, kwargs = fake_post.call_args
        self.assertEqual(args[0], 'https://aionmessaging.com/api/v1/verify/start')
        self.assertEqual(kwargs['json'], {'phone': '+2250700000001', 'sender_id': 'TRANSFERON'})
        self.assertEqual(kwargs['headers']['X-API-Key'], 'sk_test_secret_do_not_leak')

    def test_invalid_phone_number_is_rejected_without_calling_aion(self):
        with mock.patch('apps.accounts.services.requests.post') as fake_post:
            with self.assertRaises(OtpError):
                request_otp('123')
        fake_post.assert_not_called()

    def test_local_number_without_country_code_gets_ci_prefix(self):
        with mock.patch(
            'apps.accounts.services.requests.post',
            return_value=_FakeResponse(json_data={'success': True, 'verification_id': 7}),
        ) as fake_post:
            request_otp('0700000008')
        self.assertEqual(fake_post.call_args.kwargs['json']['phone'], '+2250700000008')

    def test_401_from_aion_is_translated_to_a_safe_otp_error(self):
        with mock.patch('apps.accounts.services.requests.post', return_value=_FakeResponse(401, text='Invalid API key')):
            with self.assertRaises(OtpError) as ctx:
                request_otp('+2250700000002')
        self.assertNotIn('sk_test_secret_do_not_leak', str(ctx.exception))

    def test_422_from_aion_is_translated(self):
        with mock.patch('apps.accounts.services.requests.post', return_value=_FakeResponse(422, text='insufficient balance')):
            with self.assertRaises(OtpError):
                request_otp('+2250700000003')

    def test_429_from_aion_is_translated(self):
        with mock.patch('apps.accounts.services.requests.post', return_value=_FakeResponse(429, text='rate limited')):
            with self.assertRaises(OtpError):
                request_otp('+2250700000004')

    def test_500_from_aion_is_translated(self):
        with mock.patch('apps.accounts.services.requests.post', return_value=_FakeResponse(500, text='server error')):
            with self.assertRaises(OtpError):
                request_otp('+2250700000005')

    def test_connection_error_is_translated(self):
        with mock.patch('apps.accounts.services.requests.post', side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaises(OtpError):
                request_otp('+2250700000006')

    def test_timeout_is_translated(self):
        with mock.patch('apps.accounts.services.requests.post', side_effect=requests.exceptions.Timeout()):
            with self.assertRaises(OtpError):
                request_otp('+2250700000007')

    def test_unparseable_response_body_is_translated(self):
        response = _FakeResponse()
        response.json = mock.Mock(side_effect=ValueError('not json'))
        with mock.patch('apps.accounts.services.requests.post', return_value=response):
            with self.assertRaises(OtpError):
                request_otp('+2250700000009')

    def test_explicit_success_false_is_translated(self):
        with mock.patch(
            'apps.accounts.services.requests.post',
            return_value=_FakeResponse(json_data={'success': False}),
        ):
            with self.assertRaises(OtpError):
                request_otp('+2250700000010')

    def test_missing_verification_id_in_an_otherwise_successful_response_is_rejected(self):
        """Aion's docs do not show /verify/start's success body - defensive
        floor: without a verification_id, /verify/check can never be called,
        so this must fail clearly rather than silently return None."""
        with mock.patch(
            'apps.accounts.services.requests.post',
            return_value=_FakeResponse(json_data={'success': True}),
        ):
            with self.assertRaises(OtpError):
                request_otp('+2250700000011')

    @override_settings(AION_API_KEY='')
    def test_missing_api_key_raises_without_calling_aion(self):
        with mock.patch('apps.accounts.services.requests.post') as fake_post:
            with self.assertRaises(OtpError):
                request_otp('+2250700000012')
        fake_post.assert_not_called()

    @override_settings(AION_SENDER_ID='')
    def test_missing_sender_id_raises_without_calling_aion(self):
        with mock.patch('apps.accounts.services.requests.post') as fake_post:
            with self.assertRaises(OtpError):
                request_otp('+2250700000013')
        fake_post.assert_not_called()


@override_settings(**AION_SETTINGS)
class VerifyOtpServiceTests(TestCase):
    """verify_otp() talks exclusively to POST /verify/check - the code is
    validated by Aion, never against anything stored locally."""

    def test_calls_verify_check_with_the_documented_body_and_creates_the_user(self):
        with mock.patch(
            'apps.accounts.services.requests.post',
            return_value=_FakeResponse(json_data={'success': True}),
        ) as fake_post:
            user = verify_otp('+2250700000020', '482910', 42)

        self.assertEqual(user.username, '+2250700000020')
        self.assertFalse(user.has_usable_password())
        args, kwargs = fake_post.call_args
        self.assertEqual(args[0], 'https://aionmessaging.com/api/v1/verify/check')
        self.assertEqual(kwargs['json'], {'verification_id': 42, 'code': '482910'})

    def test_reuses_the_existing_user_on_a_second_login(self):
        with mock.patch('apps.accounts.services.requests.post', return_value=_FakeResponse(json_data={'success': True})):
            first = verify_otp('+2250700000021', '111111', 1)
            second = verify_otp('+2250700000021', '222222', 2)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(User.objects.filter(username='+2250700000021').count(), 1)

    def test_missing_verification_id_is_rejected_without_calling_aion(self):
        with mock.patch('apps.accounts.services.requests.post') as fake_post:
            with self.assertRaises(OtpError):
                verify_otp('+2250700000022', '482910', None)
        fake_post.assert_not_called()

    def test_a_422_from_verify_check_is_treated_as_an_invalid_code(self):
        """Aion's docs do not show an explicit failure body for
        /verify/check - handled the same conservative way as every other
        Aion call in this module: any non-2xx means "not verified"."""
        with mock.patch('apps.accounts.services.requests.post', return_value=_FakeResponse(422, text='invalid code')):
            with self.assertRaises(OtpError) as ctx:
                verify_otp('+2250700000023', '000000', 42)
        self.assertEqual(str(ctx.exception), 'Code invalide ou expiré')

    def test_explicit_success_false_is_treated_as_an_invalid_code(self):
        with mock.patch(
            'apps.accounts.services.requests.post',
            return_value=_FakeResponse(json_data={'success': False}),
        ):
            with self.assertRaises(OtpError):
                verify_otp('+2250700000024', '000000', 42)

    def test_unparseable_verify_check_response_is_treated_as_an_invalid_code(self):
        response = _FakeResponse()
        response.json = mock.Mock(side_effect=ValueError('not json'))
        with mock.patch('apps.accounts.services.requests.post', return_value=response):
            with self.assertRaises(OtpError):
                verify_otp('+2250700000025', '482910', 42)

    def test_network_error_during_verify_check_is_translated(self):
        with mock.patch('apps.accounts.services.requests.post', side_effect=requests.exceptions.Timeout()):
            with self.assertRaises(OtpError):
                verify_otp('+2250700000026', '482910', 42)

    def test_no_aion_error_message_ever_leaks_the_api_key(self):
        with mock.patch('apps.accounts.services.requests.post', return_value=_FakeResponse(401, text='unauthorized')):
            try:
                verify_otp('+2250700000027', '482910', 42)
                self.fail('expected OtpError')
            except OtpError as exc:
                self.assertNotIn('sk_test_secret_do_not_leak', str(exc))


@override_settings(**AION_SETTINGS)
class OtpEndpointTests(TestCase):
    """Exercises the real REST_FRAMEWORK config from settings.py (JWT auth,
    AllowAny defaults, otp-request throttle rate) through the actual HTTP
    endpoints, with every Aion call mocked."""

    def setUp(self):
        self.client = APIClient()

    def test_request_otp_endpoint_returns_a_verification_id_never_a_code(self):
        with mock.patch(
            'apps.accounts.services.requests.post',
            return_value=_FakeResponse(json_data={'success': True, 'verification_id': 99}),
        ):
            response = self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000030'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'sent', 'verification_id': 99})

    def test_request_otp_never_exposes_the_api_key_in_the_response(self):
        with mock.patch('apps.accounts.services.requests.post', return_value=_FakeResponse(401, text='bad key')):
            response = self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000031'})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('sk_test_secret_do_not_leak', str(response.data))

    def test_full_flow_issues_a_working_jwt(self):
        with mock.patch(
            'apps.accounts.services.requests.post',
            return_value=_FakeResponse(json_data={'success': True, 'verification_id': 55}),
        ):
            request_response = self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000032'})
        self.assertEqual(request_response.status_code, 200)
        verification_id = request_response.data['verification_id']

        with mock.patch('apps.accounts.services.requests.post', return_value=_FakeResponse(json_data={'success': True})):
            verify_response = self.client.post(
                reverse('api_auth_otp_verify'),
                {'phone_number': '+2250700000032', 'code': '482910', 'verification_id': verification_id},
            )
        self.assertEqual(verify_response.status_code, 200)
        access_token = verify_response.data['access']
        self.assertEqual(verify_response.data['phone_number'], '+2250700000032')

        # The issued token must actually authenticate against a protected
        # view through the real JWTAuthentication class - no force_authenticate.
        factory = APIRequestFactory()
        request = factory.get('/whoami/', HTTP_AUTHORIZATION=f'Bearer {access_token}')
        whoami_response = _WhoAmIView.as_view()(request)
        self.assertEqual(whoami_response.status_code, 200)
        self.assertEqual(whoami_response.data['username'], '+2250700000032')

    def test_verify_without_verification_id_is_a_400_not_a_500(self):
        response = self.client.post(reverse('api_auth_otp_verify'), {'phone_number': '+2250700000033', 'code': '482910'})
        self.assertEqual(response.status_code, 400)

    def test_verify_with_wrong_code_returns_400_not_500(self):
        with mock.patch('apps.accounts.services.requests.post', return_value=_FakeResponse(422, text='invalid code')):
            response = self.client.post(
                reverse('api_auth_otp_verify'),
                {'phone_number': '+2250700000034', 'code': '000000', 'verification_id': 1},
            )
        self.assertEqual(response.status_code, 400)

    def test_second_otp_request_within_the_window_is_throttled(self):
        with mock.patch(
            'apps.accounts.services.requests.post',
            return_value=_FakeResponse(json_data={'success': True, 'verification_id': 1}),
        ):
            first = self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000035'})
            second = self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000035'})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


@skipUnless(
    settings.OTP_TEST_PHONE_NUMBER and settings.AION_API_KEY and settings.AION_SENDER_ID,
    'Requires a real, funded Aion Messaging account in backend/.env '
    '(AION_API_KEY/AION_SENDER_ID) and OTP_TEST_PHONE_NUMBER set to a real, '
    'reachable phone number. Not runnable in this sandbox (no Aion account, '
    'cannot receive SMS) - run it yourself once configured, e.g.: '
    'python manage.py test apps.accounts.tests.RealAionVerifyTests',
)
class RealAionVerifyTests(TestCase):
    """The only test in this file that talks to the real Aion API and sends
    a real SMS. The phone number comes exclusively from
    settings.OTP_TEST_PHONE_NUMBER - never hardcoded. Interactive: prompts
    for the code received by SMS. This is also the only way to confirm the
    exact response shape of /verify/start and /verify/check, which Aion's
    docs do not show - see the defensive handling this documents in
    apps/accounts/services.py."""

    def test_real_otp_round_trip(self):
        phone_number = settings.OTP_TEST_PHONE_NUMBER
        verification_id = request_otp(phone_number)
        code = input(f'Enter the verification code just sent to {phone_number}: ')
        user = verify_otp(phone_number, code, verification_id)
        self.assertEqual(user.username, phone_number)
