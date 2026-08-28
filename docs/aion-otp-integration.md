# Intégration Aion Messaging - OTP Configuration Guide

## 🔑 Vue d'ensemble

Ce guide explique comment l'application Transfer On Line utilise **Aion Messaging** pour envoyer et vérifier les codes OTP (One-Time Password) via SMS.

- **Documentation Aion:** https://aionmessaging.com/api/v1/
- **Endpoints utilisés:**
  - `POST /verify/start` - Envoyer un code OTP
  - `POST /verify/check` - Vérifier le code soumis

## 📱 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Frontend Flutter                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  PhoneVerificationScreen                               │ │
│  │  - Collect phone number (10 digits local format)       │ │
│  │  - Display OTP code input form                         │ │
│  │  - Handle resend with 60s cooldown                     │ │
│  │  - Max 3 verification attempts                         │ │
│  └────────────┬─────────────────────────────────────────┘ │
│               │ (HTTP REST API)                            │
└───────────────┼────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│                 Backend Django REST API                     │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  POST /api/auth/otp/request/                           │ │
│  │  - Input: {phone_number}                               │ │
│  │  - Returns: {verification_id, status}                  │ │
│  │  - Rate limit: PhoneNumberOtpThrottle (60 req/hour)    │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  POST /api/auth/otp/verify/                            │ │
│  │  - Input: {phone_number, code, verification_id}        │ │
│  │  - Returns: {access, refresh, phone_number}            │ │
│  │  - Creates/retrieves User by phone number              │ │
│  └────────────┬───────────────────────────────────────────┘ │
└───────────────┼────────────────────────────────────────────┘
                │ (HTTP JSON)
                ▼
┌─────────────────────────────────────────────────────────────┐
│              Aion Messaging API                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  POST https://aionmessaging.com/api/v1/verify/start    │ │
│  │  - Input: {phone, sender_id}                           │ │
│  │  - Returns: {success, verification_id}                 │ │
│  │  - Sends SMS with 6-digit code (10 min expiry)         │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  POST https://aionmessaging.com/api/v1/verify/check    │ │
│  │  - Input: {verification_id, code}                      │ │
│  │  - Returns: {success, ...}                             │ │
│  │  - Validates code, returns 422 if invalid              │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## ⚙️ Configuration Backend Requise

### 1. Variables d'environnement (.env ou settings de production)

```bash
# Aion Messaging API Credentials
AION_API_KEY=sk_sandbox_YOUR_API_KEY_HERE
AION_SENDER_ID=YOUR_APPROVED_SENDER_ID
AION_BASE_URL=https://aionmessaging.com/api/v1/

# Example values (replace with your actual credentials):
AION_API_KEY=sk_sandbox_WWyBpGpr2IwNEIPVG7fDIZlKIV6WVFjg
AION_SENDER_ID=TransferOnLine
AION_BASE_URL=https://aionmessaging.com/api/v1/
```

**Où trouver ces valeurs:**

1. Créez un compte sur [Aion Messaging](https://aionmessaging.com)
2. Allez à **Dashboard → API Keys** pour générer votre `AION_API_KEY`
3. Allez à **Dashboard → Sender IDs** pour créer et approuver votre `AION_SENDER_ID`
4. L'URL de base est toujours `https://aionmessaging.com/api/v1/`

### 2. Django Settings (/backend/transfer_on_line/settings.py)

Les variables d'environnement sont déjà configurées:

```python
# Line ~207-214
AION_API_KEY = os.environ.get('AION_API_KEY', '')
AION_BASE_URL = os.environ.get('AION_BASE_URL', 'https://aionmessaging.com/api/v1/')
AION_SENDER_ID = os.environ.get('AION_SENDER_ID', '')
```

### 3. Rate Limiting

La throttle `PhoneNumberOtpThrottle` limite les demandes OTP:

```python
# backend/apps/accounts/throttles.py
class PhoneNumberOtpThrottle(SimpleRateThrottle):
    scope = 'otp-request'
    # Default: 60 requests per hour per phone number
```

Configuration REST Framework:

```python
# settings.py
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_RATES': {
        'otp-request': '60/hour',  # Limit OTP requests
    }
}
```

## 📝 Code Files

### Backend Implementation

| File                                   | Purpose                                                         |
| -------------------------------------- | --------------------------------------------------------------- |
| `backend/apps/accounts/views.py`       | API views for `/auth/otp/request/` and `/auth/otp/verify/`      |
| `backend/apps/accounts/services.py`    | Core OTP logic (Aion integration, normalization, user creation) |
| `backend/apps/accounts/serializers.py` | Input validation for phone number and code                      |
| `backend/apps/accounts/throttles.py`   | Rate limiting by phone number                                   |
| `backend/apps/accounts/urls.py`        | URL routing for OTP endpoints                                   |

**Key Backend Functions:**

```python
def normalize_phone_number(raw) -> str
  # Converts to E.164 format: +225XXXXXXXXXX (Côte d'Ivoire)
  # Accepts: 07XXXXXXXX (local 10-digit) or +225... (international)

def request_otp(raw_phone_number) -> int
  # Returns verification_id from Aion /verify/start
  # Logs OTP request, handles errors

def verify_otp(raw_phone_number, submitted_code, verification_id) -> User
  # Calls Aion /verify/check
  # Creates or retrieves User for this phone number
  # Returns user for JWT token generation
```

### Frontend Implementation

| File                                                  | Purpose                                    |
| ----------------------------------------------------- | ------------------------------------------ |
| `frontend/lib/services/otp_service.dart`              | **NEW** - Complete OTP service wrapper     |
| `frontend/lib/screens/phone_verification_screen.dart` | UI for phone + OTP verification (improved) |
| `frontend/lib/services/auth_service.dart`             | Authentication service (unchanged)         |

**Key Frontend Classes:**

```dart
class OtpService {
  // Rate limiting
  static const maxRetries = 3;
  static const resendDelaySeconds = 60;
  static const codeExpirySeconds = 600; // 10 minutes

  // Core methods
  Future<OtpRequest> requestOtp(String phoneNumber)
  Future<OtpVerificationResult> verifyOtp(String code, String phoneNumber, int verificationId)
  Future<OtpRequest> requestResend(String phoneNumber)

  // Utilities
  static bool isValidPhoneNumber(String phone)
  static String formatPhoneNumber(String raw)
}

class PhoneVerificationScreen {
  // Features:
  // - Phone number validation (10 digits local or international)
  // - OTP code input with 6-digit placeholder
  // - 60-second resend cooldown timer
  // - Max 3 verification attempts
  // - "Change phone number" button
  // - Error/success snackbar notifications
}
```

## 🔄 Phone Number Format

### Accepted Formats

| Format            | Example                          | Backend Conversion |
| ----------------- | -------------------------------- | ------------------ |
| Local (10 digits) | `0745123456` or `07 45 12 34 56` | `+2250745123456`   |
| International     | `+2250745123456`                 | `+2250745123456`   |
| With country code | `+225 07 45 12 34 56`            | `+2250745123456`   |

### Frontend Validation

```dart
// Valid
OtpService.isValidPhoneNumber('0745123456')      // true
OtpService.isValidPhoneNumber('+2250745123456')  // true

// Invalid
OtpService.isValidPhoneNumber('745123456')       // false (9 digits)
OtpService.isValidPhoneNumber('33123456789')     // false (no country code)
```

## 📋 API Endpoints

### 1. Request OTP Code

```http
POST /api/auth/otp/request/
Content-Type: application/json

{
  "phone_number": "0745123456"
}
```

**Success Response (200):**

```json
{
  "status": "sent",
  "verification_id": 42
}
```

**Error Response (400):**

```json
{
  "error": "Unable to send verification code"
}
```

**Rate Limited (429):**

```json
{
  "detail": "Request was throttled. Expected available in 60 seconds."
}
```

### 2. Verify OTP Code

```http
POST /api/auth/otp/verify/
Content-Type: application/json

{
  "phone_number": "0745123456",
  "code": "482910",
  "verification_id": 42
}
```

**Success Response (200):**

```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "phone_number": "+2250745123456"
}
```

**Invalid Code (400):**

```json
{
  "error": "Code invalide ou expiré"
}
```

## 🚀 Deployment Checklist

- [ ] **Create Aion Messaging Account**
  - Sign up at https://aionmessaging.com
  - Generate API Key in Dashboard → API Keys
  - Create Sender ID and get approval (may take 24-48 hours)

- [ ] **Set Environment Variables**

  ```bash
  export AION_API_KEY="sk_sandbox_..."
  export AION_SENDER_ID="YourBrand"
  export AION_BASE_URL="https://aionmessaging.com/api/v1/"
  ```

- [ ] **Test Backend Endpoints**

  ```bash
  # Request OTP
  curl -X POST http://localhost:8000/api/auth/otp/request/ \
    -H "Content-Type: application/json" \
    -d '{"phone_number":"0745123456"}'

  # Verify OTP (replace with actual code and verification_id)
  curl -X POST http://localhost:8000/api/auth/otp/verify/ \
    -H "Content-Type: application/json" \
    -d '{"phone_number":"0745123456","code":"123456","verification_id":42}'
  ```

- [ ] **Test Frontend**
  - Run app on device/emulator
  - Navigate to first login screen
  - Enter valid phone number
  - Verify SMS received
  - Enter code and submit
  - Confirm login success

- [ ] **Monitor OTP Flow**
  - Check Aion Messaging Dashboard → Messages for SMS logs
  - Monitor Django logs for errors: `apps.accounts.services`
  - Check rate limiting thresholds

## 🔐 Security Notes

1. **API Key Protection**
   - Never commit `AION_API_KEY` to version control
   - Use `.env` file (gitignored) for local development
   - Use environment variables or secrets manager for production

2. **Code Expiration**
   - Aion codes expire after 10 minutes (hardcoded)
   - User gets 3 verification attempts before being throttled
   - Request new code if attempts exhausted

3. **Phone Number Privacy**
   - Phone numbers stored as User.username (not hashed)
   - Can be queried to check if phone is registered
   - Consider adding privacy controls if needed

4. **Rate Limiting**
   - Prevents SMS bombing: 60 OTP requests/hour per phone
   - Throttle per phone_number in request body (not IP)
   - Allows legitimate users on shared networks

## 🐛 Troubleshooting

### SMS Not Received

**Problem:** User requested OTP but never receives SMS

**Solutions:**

1. Verify phone number is in correct format: `07XXXXXXXX` or `+225...`
2. Check Aion Dashboard → Messages for delivery status
3. Verify `AION_SENDER_ID` is approved and active
4. Test with a different phone number

**Logs:**

```python
# Django logs show:
# [WARNING] Aion Messaging verify/start failed for +225745123456: ...
```

### Code Verification Always Fails

**Problem:** User enters correct code but gets "Code invalid or expired"

**Solutions:**

1. Code expires after 10 minutes - request new one
2. Max 3 attempts - request new code if exhausted
3. Verify `verification_id` is passed correctly from frontend
4. Check backend logs for Aion response errors

### Rate Limit Errors

**Problem:** "Too many requests" error on OTP request

**Solutions:**

1. Wait 60 seconds before requesting new code
2. Use "Resend" button which enforces cooldown
3. Check if multiple requests from same phone in short time

## 📚 Additional Resources

- [Aion Messaging Documentation](https://aionmessaging.com/api/v1/)
- [Django REST Framework Throttling](https://www.django-rest-framework.org/api-guide/throttling/)
- [Flutter http Package](https://pub.dev/packages/http)
- [Flutter Secure Storage](https://pub.dev/packages/flutter_secure_storage)

## 📞 Support

For issues with:

- **Aion Messaging:** Contact support@aionmessaging.com
- **Transfer On Line Backend:** Check logs in `backend/transfer_on_line/` settings
- **Frontend:** Check Flutter console output and device logs

---

**Last Updated:** 2026-08-27  
**Status:** Production Ready ✅
