from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.serializers import RequestOtpSerializer, VerifyOtpSerializer
from apps.accounts.services.otp_service import OtpError, request_otp, verify_otp
from apps.accounts.throttles import PhoneNumberOtpThrottle


class RequestOtpView(APIView):
    """Views stay thin: validate input via a serializer, delegate to
    apps.accounts.services.otp_service, translate the outcome to an HTTP
    response. AllowAny is correct here - this is exactly the step before
    any identity/token exists, there is nothing to authenticate yet."""

    permission_classes = [AllowAny]
    throttle_classes = [PhoneNumberOtpThrottle]

    def post(self, request):
        serializer = RequestOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            request_otp(serializer.validated_data['phone_number'])
        except OtpError as exc:
            return Response({'error': str(exc)}, status=400)
        # The code itself is never returned here, in any build - see
        # otp_service.request_otp's doc.
        return Response({'status': 'sent'})


class VerifyOtpView(APIView):
    """Also AllowAny: this is the request that *establishes* identity (it
    issues the JWT) - there is no existing session to require yet."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = verify_otp(
                serializer.validated_data['phone_number'],
                serializer.validated_data['code'],
            )
        except OtpError as exc:
            return Response({'error': str(exc)}, status=400)

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'phone_number': user.username,
        })
