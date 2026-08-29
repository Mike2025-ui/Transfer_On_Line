from rest_framework import serializers


class RequestOtpSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)


class VerifyOtpSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=6, min_length=4)
