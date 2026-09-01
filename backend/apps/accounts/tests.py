import threading
from unittest import mock, skipUnless

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView

from apps.accounts.models import PhoneOtp
from apps.accounts.services.otp_service import OtpError, request_otp, verify_otp

User = get_user_model()


class _WhoAmIView(APIView):
    """Minimal protected view used only to prove a token issued by
    VerifyOtpView is actually accepted by JWTAuthentication end-to-end."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'username': request.user.username})


class _FakeIkoddiResponse:
    """Minimal stand-in for requests.Response, just enough for
    IkoddiService's own handling."""

    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = {'status': 0} if json_data is None else json_data

    def json(self):
        return self._json_data


def _ikoddi_responder(*, send_token='ikoddi-otp-token', correct_code=None, send_status_code=200):
    """A fake for `requests.post` that plays both of IKODDI's OTP endpoints:
    .../otp/{app}/sms/{identity} (send - no body, path-based) and
    .../otp/{app}/verify (verify - JSON body). IKODDI is the actual source
    of truth for whether a code matches, so tests decide correctness via
    `correct_code`, exactly like the real provider would - Django/these
    tests never see or store the real code."""

    def _responder(url, headers=None, json=None, timeout=None):
        if url.endswith('/verify'):
            submitted = (json or {}).get('otp')
            matched = correct_code is not None and str(submitted) == str(correct_code)
            return _FakeIkoddiResponse(200, {'status': 0 if matched else -1, 'message': 'OTP Matched' if matched else 'OTP Mismatch'})
        return _FakeIkoddiResponse(send_status_code, {'status': 0, 'otpToken': send_token})

    return _responder


IKODDI_SETTINGS = {'IKODDI_API_KEY': 'test_key_do_not_leak', 'IKODDI_GROUP_ID': 'grp-123', 'IKODDI_OTP_APP_ID': 'app-123'}


def _latest_otp(phone_number):
    return PhoneOtp.objects.filter(phone_number=phone_number, consumed_at__isnull=True).latest('created_at')


@override_settings(**IKODDI_SETTINGS)
class RequestOtpServiceTests(TestCase):
    """request_otp() talks exclusively to IkoddiService.send_otp() (mocked
    here at the HTTP boundary) - IKODDI generates and sends the code itself;
    Django only stores the opaque verificationKey it returns
    (apps.accounts.models.PhoneOtp.verification_key), never a code or a
    hash of one."""

    def test_calls_ikoddi_with_the_documented_url_and_header(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(),
        ) as fake_post:
            request_otp('+2250700000001')

        fake_post.assert_called_once()
        args, kwargs = fake_post.call_args
        self.assertEqual(args[0], 'https://api.ikoddi.com/api/v1/groups/grp-123/otp/app-123/sms/2250700000001')
        self.assertEqual(kwargs['headers']['x-api-key'], 'test_key_do_not_leak')
        self.assertNotIn('+', args[0], 'IKODDI identities are digits-only, no leading +')

    def test_stores_the_verification_key_never_a_code(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(send_token='opaque-token-abc'),
        ):
            request_otp('+2250700000002')
        otp = _latest_otp('+2250700000002')
        self.assertEqual(otp.verification_key, 'opaque-token-abc')
        self.assertEqual(otp.attempts, 0)
        self.assertIsNone(otp.consumed_at)

    def test_invalid_phone_number_is_rejected_without_calling_ikoddi(self):
        with mock.patch('apps.accounts.services.ikoddi_service.requests.post') as fake_post:
            with self.assertRaises(OtpError):
                request_otp('123')
        fake_post.assert_not_called()

    def test_local_number_without_country_code_gets_ci_prefix(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(),
        ) as fake_post:
            request_otp('0700000008')
        self.assertIn('2250700000008', fake_post.call_args.args[0])

    def test_non_200_from_ikoddi_is_translated_to_a_safe_otp_error(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(send_status_code=401),
        ):
            with self.assertRaises(OtpError) as ctx:
                request_otp('+2250700000003')
        self.assertNotIn('test_key_do_not_leak', str(ctx.exception))

    def test_status_minus_one_on_send_is_translated(self):
        def _fails(url, headers=None, json=None, timeout=None):
            return _FakeIkoddiResponse(200, {'status': -1})
        with mock.patch('apps.accounts.services.ikoddi_service.requests.post', side_effect=_fails):
            with self.assertRaises(OtpError):
                request_otp('+2250700000004')

    def test_connection_error_is_translated(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=requests.exceptions.ConnectionError(),
        ):
            with self.assertRaises(OtpError):
                request_otp('+2250700000005')

    def test_timeout_is_translated(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=requests.exceptions.Timeout(),
        ):
            with self.assertRaises(OtpError):
                request_otp('+2250700000006')

    def test_unparseable_response_body_is_translated(self):
        response = _FakeIkoddiResponse()
        response.json = mock.Mock(side_effect=ValueError('not json'))
        with mock.patch('apps.accounts.services.ikoddi_service.requests.post', return_value=response):
            with self.assertRaises(OtpError):
                request_otp('+2250700000007')

    @override_settings(IKODDI_API_KEY='')
    def test_missing_api_key_raises_without_calling_ikoddi(self):
        with mock.patch('apps.accounts.services.ikoddi_service.requests.post') as fake_post:
            with self.assertRaises(OtpError):
                request_otp('+2250700000009')
        fake_post.assert_not_called()

    @override_settings(IKODDI_OTP_APP_ID='')
    def test_missing_otp_app_id_raises_without_calling_ikoddi(self):
        with mock.patch('apps.accounts.services.ikoddi_service.requests.post') as fake_post:
            with self.assertRaises(OtpError):
                request_otp('+2250700000010')
        fake_post.assert_not_called()

    def test_two_requests_for_different_numbers_never_collide(self):
        """No shared/global "current code" variable - each phone number's
        pending verification is its own row, isolated from every other
        number's."""
        with mock.patch('apps.accounts.services.ikoddi_service.requests.post', side_effect=_ikoddi_responder()):
            request_otp('+2250700000011')
            request_otp('+2250700000012')
        otp_a = _latest_otp('+2250700000011')
        otp_b = _latest_otp('+2250700000012')
        self.assertNotEqual(otp_a.pk, otp_b.pk)


@override_settings(**IKODDI_SETTINGS)
class VerifyOtpServiceTests(TestCase):
    """verify_otp() resolves the most recent unconsumed PhoneOtp for a
    number, then asks IKODDI to actually check the code - Django holds no
    copy of the code to compare against, only the opaque verificationKey.
    Max attempts (3) is Django's own local safety net, since IKODDI's docs
    do not expose one."""

    def _request(self, phone, correct_code):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code=correct_code),
        ):
            request_otp(phone)

    def test_correct_code_on_first_try_succeeds_and_creates_the_user(self):
        self._request('+2250700000020', correct_code='482910')
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code='482910'),
        ):
            user = verify_otp('+2250700000020', '482910')
        self.assertEqual(user.username, '+2250700000020')
        self.assertFalse(user.has_usable_password())

    def test_reuses_the_existing_user_on_a_second_login_same_number(self):
        """Same normalized number -> same User, across as many logins as
        needed - never a second, independent identity."""
        self._request('+2250700000021', correct_code='111111')
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code='111111'),
        ):
            first = verify_otp('+2250700000021', '111111')

        self._request('+2250700000021', correct_code='222222')
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code='222222'),
        ):
            second = verify_otp('+2250700000021', '222222')

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(User.objects.filter(username='+2250700000021').count(), 1)

    def test_wrong_code_is_rejected(self):
        self._request('+2250700000022', correct_code='999999')
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code='999999'),
        ):
            with self.assertRaises(OtpError):
                verify_otp('+2250700000022', '000000')

    def test_ikoddi_status_minus_one_represents_an_expired_or_wrong_code(self):
        """IKODDI does not distinguish "wrong" from "expired" - both come
        back as status -1 (see ikoddi_service.py's doc). Genuine expiry is
        therefore surfaced exactly like this, never guessed with a
        fabricated local TTL."""
        self._request('+2250700000023', correct_code='333333')
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code=None),  # IKODDI now always reports a mismatch
        ):
            with self.assertRaises(OtpError):
                verify_otp('+2250700000023', '333333')

    def test_maximum_3_attempts_then_refused_locally_without_calling_ikoddi_again(self):
        self._request('+2250700000024', correct_code='444444')
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code='444444'),
        ) as fake_post:
            for _ in range(3):
                with self.assertRaises(OtpError):
                    verify_otp('+2250700000024', '000000')
            calls_after_3_failures = fake_post.call_count
            with self.assertRaises(OtpError):
                verify_otp('+2250700000024', '444444')  # locked out even though this is the right code
            self.assertEqual(
                fake_post.call_count, calls_after_3_failures,
                'the 4th attempt must be refused locally, without ever calling IKODDI again',
            )

    def test_code_already_used_cannot_be_reused(self):
        self._request('+2250700000025', correct_code='555555')
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code='555555'),
        ):
            verify_otp('+2250700000025', '555555')
            with self.assertRaises(OtpError):
                verify_otp('+2250700000025', '555555')

    def test_verify_with_no_prior_request_is_rejected(self):
        with self.assertRaises(OtpError):
            verify_otp('+2250700000026', '123456')

    def test_a_number_without_a_pending_request_cannot_verify_another_numbers_code(self):
        """Isolation between users: number A requests a code; number B
        (which never requested one) has no PhoneOtp row at all, so its
        verification is rejected before IKODDI is even called."""
        self._request('+2250700000027', correct_code='666666')  # number A's code
        with mock.patch('apps.accounts.services.ikoddi_service.requests.post') as fake_post:
            with self.assertRaises(OtpError):
                verify_otp('+2250700000028', '666666')  # number B tries A's code
        fake_post.assert_not_called()


@override_settings(**IKODDI_SETTINGS)
class OtpEndpointTests(TestCase):
    """Exercises the real REST_FRAMEWORK config from settings.py (JWT auth,
    AllowAny defaults, otp-request throttle rate) through the actual HTTP
    endpoints, with every IKODDI call mocked."""

    def setUp(self):
        self.client = APIClient()

    def test_request_otp_endpoint_never_returns_the_code_or_the_token(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(send_token='super-secret-token'),
        ):
            response = self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000030'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'sent', 'channel': 'sms'})
        self.assertNotIn('super-secret-token', str(response.data))
        self.assertNotIn('test_key_do_not_leak', str(response.data))

    def test_request_otp_never_exposes_the_api_key_on_failure(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(send_status_code=401),
        ):
            response = self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000031'})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('test_key_do_not_leak', str(response.data))

    def test_full_flow_issues_a_working_jwt(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code='123456'),
        ):
            request_response = self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000032'})
        self.assertEqual(request_response.status_code, 200)

        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code='123456'),
        ):
            verify_response = self.client.post(
                reverse('api_auth_otp_verify'),
                {'phone_number': '+2250700000032', 'code': '123456'},
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

    def test_verify_with_wrong_code_returns_400_not_500(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(correct_code='999999'),
        ):
            self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000034'})
            response = self.client.post(
                reverse('api_auth_otp_verify'),
                {'phone_number': '+2250700000034', 'code': '000000'},
            )
        self.assertEqual(response.status_code, 400)

    def test_second_otp_request_within_the_window_is_throttled(self):
        with mock.patch('apps.accounts.services.ikoddi_service.requests.post', side_effect=_ikoddi_responder()):
            first = self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000035'})
            second = self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000035'})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_no_email_channel_exists_anymore(self):
        """The old phone/email selector and the whole email path stay
        removed for good - an email-shaped payload (no phone_number) is
        simply not a valid request. `channel` on this serializer today is
        unrelated and new: it only picks the IKODDI OTP delivery method
        (sms/whatsapp, see RequestOtpChannelTests below) - never email."""
        response = self.client.post(reverse('api_auth_otp_request'), {'email': 'someone@example.com'})
        self.assertEqual(response.status_code, 400)

    def test_unsupported_channel_is_rejected_without_calling_ikoddi(self):
        with mock.patch('apps.accounts.services.ikoddi_service.requests.post') as fake_post:
            response = self.client.post(
                reverse('api_auth_otp_request'), {'phone_number': '+2250700000036', 'channel': 'email'},
            )
        self.assertEqual(response.status_code, 400)
        fake_post.assert_not_called()

    def test_whatsapp_channel_calls_the_documented_whatsapp_endpoint(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(),
        ) as fake_post:
            response = self.client.post(
                reverse('api_auth_otp_request'), {'phone_number': '+2250700000037', 'channel': 'whatsapp'},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'sent', 'channel': 'whatsapp'})
        self.assertIn('/whatsapp/', fake_post.call_args.args[0])

    def test_channel_defaults_to_sms_when_omitted(self):
        with mock.patch(
            'apps.accounts.services.ikoddi_service.requests.post',
            side_effect=_ikoddi_responder(),
        ) as fake_post:
            self.client.post(reverse('api_auth_otp_request'), {'phone_number': '+2250700000038'})
        self.assertIn('/sms/', fake_post.call_args.args[0])


class ConcurrentOtpRequestTests(TransactionTestCase):
    """Real threads, real database - proves two different phone numbers
    requesting an OTP at the exact same time never interfere with each
    other."""

    @override_settings(**IKODDI_SETTINGS)
    def test_simultaneous_requests_for_different_numbers_stay_isolated(self):
        numbers = [f'+225070001{n:04d}' for n in range(20)]
        barrier = threading.Barrier(len(numbers))
        errors = []

        def worker(phone):
            try:
                barrier.wait(timeout=5)
                request_otp(phone)
            except Exception as exc:  # pragma: no cover - failure path only
                errors.append(exc)
            finally:
                connections.close_all()

        # mock.patch() rewrites a module-level attribute - it is not
        # thread-safe to enter/exit it independently inside each worker
        # (one thread's __exit__ can restore a DIFFERENT thread's mock, or
        # the real `requests.post`, mid-flight). Patched exactly once,
        # around the whole concurrent section, instead.
        with mock.patch('apps.accounts.services.ikoddi_service.requests.post', side_effect=_ikoddi_responder()):
            threads = [threading.Thread(target=worker, args=(n,)) for n in numbers]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        self.assertEqual(errors, [])
        for number in numbers:
            self.assertEqual(
                PhoneOtp.objects.filter(phone_number=number).count(), 1,
                f'expected exactly one OTP row for {number}',
            )


@skipUnless(
    settings.OTP_TEST_PHONE_NUMBER and settings.IKODDI_API_KEY and settings.IKODDI_GROUP_ID and settings.IKODDI_OTP_APP_ID,
    'Requires a real, funded IKODDI account in backend/.env (IKODDI_API_KEY/'
    'IKODDI_GROUP_ID/IKODDI_OTP_APP_ID) and OTP_TEST_PHONE_NUMBER set to a '
    'real, reachable phone number. Not runnable in this sandbox (no IKODDI '
    'account, cannot receive SMS) - run it yourself once configured: '
    'python manage.py test apps.accounts.tests.RealIkoddiOtpTests',
)
class RealIkoddiOtpTests(TestCase):
    """The only test in this file that sends a real SMS. The phone number
    comes exclusively from settings.OTP_TEST_PHONE_NUMBER - never
    hardcoded. Interactive: prompts for the code received by SMS."""

    def test_real_otp_round_trip(self):
        phone_number = settings.OTP_TEST_PHONE_NUMBER
        request_otp(phone_number)
        code = input(f'Enter the verification code just sent to {phone_number}: ')
        user = verify_otp(phone_number, code)
        self.assertEqual(user.username, phone_number)
