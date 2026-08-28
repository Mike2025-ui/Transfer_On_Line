from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.serializers import RequestOtpSerializer, VerifyOtpSerializer
from apps.accounts.services import OtpError, request_otp, verify_otp
from apps.accounts.throttles import PhoneNumberOtpThrottle


class RequestOtpView(APIView):
    """Views stay thin: validate input via a serializer, delegate to
    apps.accounts.services, translate the outcome to an HTTP response. All
    the actual OTP/User logic lives in services.py, not here."""

    permission_classes = [AllowAny]
    throttle_classes = [PhoneNumberOtpThrottle]

    def post(self, request):
        serializer = RequestOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            verification_id = request_otp(serializer.validated_data['phone_number'])
        except OtpError as exc:
            return Response({'error': str(exc)}, status=400)
        # Aion Messaging is the sole OTP provider - the code itself is never
        # known to Django, so there is nothing to echo back even in DEBUG
        # (see the removed debug_code field's history in git for context).
        return Response({'status': 'sent', 'verification_id': verification_id})


class VerifyOtpView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = verify_otp(
                serializer.validated_data['phone_number'],
                serializer.validated_data['code'],
                serializer.validated_data['verification_id'],
            )
        except OtpError as exc:
            return Response({'error': str(exc)}, status=400)

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'phone_number': user.username,
        })
