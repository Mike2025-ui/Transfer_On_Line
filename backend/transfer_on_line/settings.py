from datetime import timedelta
from pathlib import Path
import os
import sys
from urllib.parse import urlparse

try:
    import dj_database_url
except ImportError:  # pragma: no cover - fallback for local development environments
    dj_database_url = None

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:  # pragma: no cover - python-dotenv is optional
    pass

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-local-dev-only')
DEBUG = os.environ.get('DJANGO_DEBUG', 'false').lower() == 'true'

DEFAULT_ALLOWED_HOSTS = [
    'www.transfert-online.site',
    'transfert-online.site',
    '180.149.198.189',
    'localhost',
    '127.0.0.1',
    '172.20.10.3',
    '::1',
]

raw_allowed_hosts = os.environ.get('DJANGO_ALLOWED_HOSTS', '')
if raw_allowed_hosts and raw_allowed_hosts.strip():
    allowed_hosts = [
        host.strip()
        for host in raw_allowed_hosts.split(',')
        if host.strip()
    ]
else:
    allowed_hosts = DEFAULT_ALLOWED_HOSTS

ALLOWED_HOSTS = allowed_hosts

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'django_rq',
    'corsheaders',

    # Nos apps
    'apps.core',
    'apps.dashboard',
    'apps.devices',
    'apps.payments',
    # Le flux client est désormais anonyme : aucun OTP/JWT n’est utilisé
    # pour la création ou la confirmation de transaction. L’ancienne app
    # d’authentification client reste désactivée pour éviter tout chemin
    # réintroduisant l’identité OTP dans le produit.
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.core.middleware.CorrelationIdMiddleware',
    'apps.core.middleware.RequestTimingMiddleware',
]

SLOW_REQUEST_THRESHOLD_MS = int(os.environ.get('SLOW_REQUEST_THRESHOLD_MS', '2000'))

ROOT_URLCONF = 'transfer_on_line.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'transfer_on_line.wsgi.application'

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    f'sqlite:///{BASE_DIR / "db.sqlite3"}',
)
database_host = urlparse(DATABASE_URL).hostname
if (
    os.name == 'nt'
    and database_host == 'postgres'
    and not os.environ.get('POSTGRES_HOST')
):
    DATABASE_URL = f'sqlite:///{BASE_DIR / "db.sqlite3"}'

if dj_database_url is not None:
    DATABASES = {'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'true').lower() == 'true'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@transfer-on-line.local')

LOGIN_REDIRECT_URL = '/dashboard/'
# Back Office audit: the custom dashboard has its own login page (see
# apps.dashboard.views.dashboard_login) - never Django Admin's. Only affects
# django.contrib.auth's own login_required/user_passes_test default; the
# dashboard's local staff_member_required() below points here explicitly too.
LOGIN_URL = 'dashboard_login'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        # L’authentification OTP/JWT est retirée du flux client. Le parcours
        # d’achat reste anonyme et ne collecte que le numéro requis pour la
        # transaction ; les pages de dashboard internes restent gérées par
        # Django Admin/session si besoin, sans être utilisées dans l’app mobile.
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_THROTTLE_CLASSES': [],
    'DEFAULT_THROTTLE_RATES': {
        'otp-request': os.environ.get('OTP_REQUEST_THROTTLE_RATE', '1/min'),
    },
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.environ.get('JWT_ACCESS_TOKEN_MINUTES', '30'))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.environ.get('JWT_REFRESH_TOKEN_DAYS', '30'))),
    'ROTATE_REFRESH_TOKENS': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    # Customer accounts are created with set_unusable_password() (see
    # apps.accounts.views.VerifyOtpView) - USER_ID_FIELD/CLAIM stay on the
    # default 'id', nothing custom needed since these are real auth.User rows.
}

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
RQ_QUEUES = {
    'default': {
        'URL': REDIS_URL,
        'DEFAULT_TIMEOUT': 360,
    },
}

default_origins = 'http://localhost:3000,http://localhost:8080,http://127.0.0.1:8000,http://127.0.0.1:8080'
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CORS_ALLOWED_ORIGINS', default_origins).split(',')
    if origin.strip()
]
default_csrf_origins = (
    'http://www.transfert-online.site,http://transfert-online.site,'
    'http://localhost:3000,http://localhost:8000,http://127.0.0.1:3000,http://127.0.0.1:8000'
)
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', default_csrf_origins).split(',')
    if origin.strip()
]

# Back Office audit (CSRF 403 root cause): these five settings must be
# driven by whether the site is ACTUALLY served over HTTPS
# (DJANGO_SECURE_SSL_REDIRECT), never by DEBUG. The previous `not DEBUG`
# wiring meant a correctly-configured DEBUG=False production server, while
# still HTTP-only (no certificate yet - the exact current state of
# http://www.transfert-online.site/), silently marked the session and CSRF
# cookies `Secure`. A browser refuses to store or resend a `Secure` cookie
# over a plain HTTP connection, so the CSRF cookie set on the form's GET
# request never actually reached the server on the following POST -
# producing "CSRF verification failed" regardless of a correct
# {% csrf_token %} in the template. Flipping DJANGO_SECURE_SSL_REDIRECT=true
# once the certificate is installed now turns on the whole HTTPS-only
# bundle together - no other code change needed, nothing forced early.
SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SECURE_SSL_REDIRECT', 'false').lower() == 'true'
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '31536000' if SECURE_SSL_REDIRECT else '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_SSL_REDIRECT
SECURE_HSTS_PRELOAD = SECURE_SSL_REDIRECT
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

GENIUSPAY_API_KEY = os.environ.get('GENIUSPAY_API_KEY', '')
GENIUSPAY_API_SECRET = os.environ.get('GENIUSPAY_API_SECRET', '')
GENIUSPAY_BASE_URL = os.environ.get('GENIUSPAY_BASE_URL', 'https://geniuspay.ci/api/v1/merchant')
GENIUSPAY_WEBHOOK_SECRET = os.environ.get('GENIUSPAY_WEBHOOK_SECRET', '')
GENIUSPAY_CURRENCY = os.environ.get('GENIUSPAY_CURRENCY', 'XOF')
GENIUSPAY_SUCCESS_URL = os.environ.get('GENIUSPAY_SUCCESS_URL', 'https://transfert-online.site/payment/success')
GENIUSPAY_ERROR_URL = os.environ.get('GENIUSPAY_ERROR_URL', 'https://transfert-online.site/payment/cancel')
GENIUSPAY_TIMEOUT_SECONDS = int(os.environ.get('GENIUSPAY_TIMEOUT_SECONDS', '30'))
GENIUSPAY_ALLOW_MOCK = os.environ.get('GENIUSPAY_ALLOW_MOCK', 'false').lower() == 'true'

# Production audit: Jèko is the sole primary provider, GeniusPay its only
# fallback (PaymentService._provider_order() tries them in this order for
# payment_method='auto' and stops at the first that accepts the payment -
# see apps/payments/services/payment_service.py). CinetPay and FeexPay have
# been removed entirely (providers, webhook, URLs, settings, Payment.
# METHOD_CHOICES) - they are no longer selectable at all, not even
# explicitly, per an explicit request to drop them rather than just
# deprioritize them.
PAYMENT_PROVIDER_ORDER = os.environ.get('PAYMENT_PROVIDER_ORDER', 'jeko,geniuspay')
# Jèko (https://developer.jeko.africa) - standard merchant Payments API
# (`/partner_api/payment_requests`, `/partner_api/stores`), see
# apps/payments/providers/jeko.py. X-API-KEY/X-API-KEY-ID and JEKO_STORE_ID
# come from Jèko's own dashboard (cockpit.jeko.africa) for Transfer On
# Line's own business/store - there is no sandbox environment (confirmed by
# Jèko's own docs), so these always point at the one real environment.
JEKO_API_KEY = os.environ.get('JEKO_API_KEY', '')
JEKO_API_KEY_ID = os.environ.get('JEKO_API_KEY_ID', '')
JEKO_BASE_URL = os.environ.get('JEKO_BASE_URL', 'https://api.jeko.africa')
JEKO_STORE_ID = os.environ.get('JEKO_STORE_ID', '')
JEKO_SUCCESS_URL = os.environ.get('JEKO_SUCCESS_URL', 'https://transfert-online.site/payment/success')
JEKO_ERROR_URL = os.environ.get('JEKO_ERROR_URL', 'https://transfert-online.site/payment/cancel')
JEKO_WEBHOOK_SECRET = os.environ.get('JEKO_WEBHOOK_SECRET', '')
JEKO_TIMEOUT_SECONDS = int(os.environ.get('JEKO_TIMEOUT_SECONDS', '20'))
# Jèko "Service Providers" program (business_onboarding/business_api_keys/...
# in apps/payments/providers/jeko_service.py) is a SEPARATE, optional
# marketplace/reseller feature - Jèko's own docs say it "ne concerne pas
# tous les intégrateurs" and is for platforms that create Jèko accounts FOR
# OTHER companies. Transfer On Line collects its own payments, so this is
# not used by the payment flow above; these credentials are only for that
# unused onboarding client, kept separate from JEKO_API_KEY/_ID on purpose.
JEKO_PARTNER_API_KEY = os.environ.get('JEKO_PARTNER_API_KEY', '')
JEKO_PARTNER_API_KEY_ID = os.environ.get('JEKO_PARTNER_API_KEY_ID', '')

# Test safety net (production audit, Jèko has no sandbox environment): with
# PAYMENT_PROVIDER_ORDER defaulting to 'jeko,geniuspay' and CinetPay/FeexPay
# removed entirely, a test that mocks JekoProvider.create_payment (the
# convention this whole test suite uses for payment_method='auto' flows)
# would otherwise fall through to the real, live Jèko/GeniusPay APIs
# whenever this machine's own .env happens to carry real credentials for
# local manual testing - Jèko in particular has no sandbox, so that call
# would hit production. Forcing 'jeko' and blanking the live keys here, only
# under the test runner, makes every such test hit its intended mock
# unconditionally - and if a test forgets to mock at all, _ensure_configured()
# fails cleanly on the blanked keys instead of silently reaching a real API.
# A test that genuinely wants to exercise Jèko/GeniusPay already sets its
# own credentials via @override_settings (see apps/payments/tests.py's
# JEKO_SETTINGS/IKODDI_SETTINGS-style dicts) - override_settings always
# wins over this module-level default, so those tests are unaffected.
if 'test' in sys.argv:
    PAYMENT_PROVIDER_ORDER = 'jeko'
    JEKO_API_KEY = JEKO_API_KEY_ID = JEKO_STORE_ID = ''
    GENIUSPAY_API_KEY = GENIUSPAY_API_SECRET = ''

# IKODDI (https://docs.ikoddi.com) - the sole OTP/SMS/WhatsApp provider.
# IKODDI's OTP As A Service generates, sends AND verifies the code itself
# (see apps/accounts/services/ikoddi_service.py) - Django never generates
# or stores the code, only the opaque `verificationKey` it returns
# (apps.accounts.models.PhoneOtp.verification_key). No mock mode: every
# request_otp() call really reaches IKODDI; tests mock the HTTP call
# directly instead (see apps/accounts/tests.py).
IKODDI_API_KEY = os.environ.get('IKODDI_API_KEY', '')
IKODDI_BASE_URL = os.environ.get('IKODDI_BASE_URL', 'https://api.ikoddi.com/api/v1')
IKODDI_GROUP_ID = os.environ.get('IKODDI_GROUP_ID', '')
IKODDI_OTP_APP_ID = os.environ.get('IKODDI_OTP_APP_ID', '')
IKODDI_TIMEOUT_SECONDS = int(os.environ.get('IKODDI_TIMEOUT_SECONDS', '20'))
# Only ever read from the environment for a gated real-provider test (see
# apps/accounts/tests.py) - never a default value used by the application.
OTP_TEST_PHONE_NUMBER = os.environ.get('OTP_TEST_PHONE_NUMBER', '')

CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.environ.get('CIRCUIT_BREAKER_FAILURE_THRESHOLD', '5'))
CIRCUIT_BREAKER_RESET_SECONDS = int(os.environ.get('CIRCUIT_BREAKER_RESET_SECONDS', '60'))

# Transaction Engine / Gateway Manager (Phase B) - thresholds only, never business
# logic. Two dicts, not a class: adding a future key never requires a migration
# or a signature change anywhere that reads them.
TRANSACTION_ENGINE = {
    # Total attempts: initial execution + one retry.
    "MAX_RETRY": int(os.environ.get("TXN_MAX_RETRY", "2")),
    "TIMEOUT_SECONDS": int(os.environ.get("TXN_TIMEOUT_SECONDS", "90")),
    "RETRY_BACKOFF": [
        int(x) for x in os.environ.get("TXN_RETRY_BACKOFF", "30,45,60").split(",")
    ],
}

GATEWAY_MANAGER = {
    "LOW_BATTERY_THRESHOLD": int(os.environ.get("GATEWAY_LOW_BATTERY_THRESHOLD", "20")),
    "MAX_CONCURRENT_TASKS": int(os.environ.get("GATEWAY_MAX_CONCURRENT_TASKS", "2")),
    "MAX_QUEUE": int(os.environ.get("GATEWAY_MAX_QUEUE", "20")),
    "HEARTBEAT_STALE_SECONDS": int(os.environ.get("GATEWAY_HEARTBEAT_STALE_SECONDS", "90")),
    "MAX_CONSECUTIVE_FAILURES": int(os.environ.get("GATEWAY_MAX_CONSECUTIVE_FAILURES", "5")),
}

# Progressive cutover switch: when true, ExecuteTransactionView/TransactionResultView
# route gateway/SIM selection and attempt lifecycle through Scheduler/
# ReservationManager/RetryManager, which reserves a specific GatewaySim and
# creates a TransactionAttempt per dial. Default false - the legacy path
# stays the production behavior until this has been validated on real
# Android phones; it uses GatewayManager.select_operator_gateway() instead
# (business-model audit Phase 7.2) - the same operator-eligibility chain as
# the new engine, just without a reservation/TransactionAttempt. Neither
# engine ever falls back to a Gateway of the wrong operator: with no
# eligible GatewaySim, the transaction is queued via next_retry_at (see
# ExecuteTransactionView.post / RetryManager.dispatch_due_retries), never
# assigned to a mismatched Gateway.
USE_NEW_TRANSACTION_ENGINE = os.environ.get('USE_NEW_TRANSACTION_ENGINE', 'false').lower() == 'true'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'correlation_id': {'()': 'apps.core.logging_utils.CorrelationIdLogFilter'},
    },
    'formatters': {
        'plain': {'format': '%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s'},
        'json': {'()': 'apps.core.logging_utils.JsonFormatter'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'filters': ['correlation_id'],
            'formatter': 'json' if os.environ.get('DJANGO_LOG_FORMAT', 'plain').lower() == 'json' else 'plain',
        },
    },
    'root': {'handlers': ['console'], 'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO')},
}

# Observability: Sentry is entirely opt-in via SENTRY_DSN - unset (the
# default), this block is a no-op and no new dependency is required at
# runtime unless sentry-sdk is actually installed.
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[
                DjangoIntegration(),
                LoggingIntegration(level=None, event_level='ERROR'),
            ],
            traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.1')),
            environment=os.environ.get('SENTRY_ENVIRONMENT', 'development' if DEBUG else 'production'),
            send_default_pii=False,
        )
    except ImportError:  # pragma: no cover - sentry-sdk is an optional dependency
        pass
