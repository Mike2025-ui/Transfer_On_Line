from rest_framework import serializers


class RequestOtpSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=['phone', 'email'], default='phone')
    phone_number = serializers.CharField(max_length=20, required=False)
    email = serializers.EmailField(required=False)

    def validate(self, attrs):
        if attrs['channel'] == 'phone' and not attrs.get('phone_number'):
            raise serializers.ValidationError({'phone_number': 'Ce champ est obligatoire.'})
        if attrs['channel'] == 'email' and not attrs.get('email'):
            raise serializers.ValidationError({'email': 'Ce champ est obligatoire.'})
        return attrs


class VerifyOtpSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=['phone', 'email'], default='phone')
    phone_number = serializers.CharField(max_length=20, required=False)
    email = serializers.EmailField(required=False)
    code = serializers.CharField(max_length=6, min_length=4)
    # Opaque id Aion's /verify/start returns and /verify/check requires -
    # the client only ever forwards it verbatim, it never generates or
    # interprets it. Required: verify_otp() cannot call Aion without it.
    verification_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if attrs['channel'] == 'phone' and (not attrs.get('phone_number') or attrs.get('verification_id') is None):
            raise serializers.ValidationError({'phone_number': 'Téléphone et verification_id obligatoires.'})
        if attrs['channel'] == 'email' and not attrs.get('email'):
            raise serializers.ValidationError({'email': 'Ce champ est obligatoire.'})
        return attrs
