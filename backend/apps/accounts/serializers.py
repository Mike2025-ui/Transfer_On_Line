from rest_framework import serializers

from apps.accounts.services.otp_service import OTP_CHANNELS


class RequestOtpSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    # Optional, defaults to 'sms' - IKODDI remains the only provider either
    # way (see apps.accounts.services.ikoddi_service.IkoddiService.send_otp).
    # Anything outside OTP_CHANNELS is rejected here, before ever reaching
    # otp_service/IKODDI.
    channel = serializers.ChoiceField(choices=OTP_CHANNELS, default='sms')


class VerifyOtpSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=6, min_length=4)
