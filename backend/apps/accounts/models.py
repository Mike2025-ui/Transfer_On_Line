# Aion Messaging is the sole OTP provider (see apps.accounts.services): it
# generates, delivers and verifies the one-time code itself via
# /verify/start and /verify/check. Django never sees the code and keeps no
# OTP state of its own - the OtpCode model that used to store
# locally-generated codes was removed for exactly this reason (see
# migration 0002_delete_otpcode).
