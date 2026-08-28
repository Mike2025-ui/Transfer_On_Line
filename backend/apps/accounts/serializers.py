from rest_framework import serializers


class RequestOtpSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)


class VerifyOtpSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=6, min_length=4)
    # Opaque id Aion's /verify/start returns and /verify/check requires -
    # the client only ever forwards it verbatim, it never generates or
    # interprets it. Required: verify_otp() cannot call Aion without it.
    verification_id = serializers.IntegerField()
