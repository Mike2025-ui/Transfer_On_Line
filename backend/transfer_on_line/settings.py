from datetime import timedelta
from pathlib import Path
import os

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

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,172.20.10.3"
    ).split(",")
    if host.strip()
]

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
    'apps.accounts',
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
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
RESEND_FROM_EMAIL = os.environ.get('RESEND_FROM_EMAIL', 'onboarding@resend.dev')
RESEND_WEBHOOK_SECRET = os.environ.get('RESEND_WEBHOOK_SECRET', '')

LOGIN_REDIRECT_URL = '/dashboard/'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        # SessionAuthentication stays first: the dashboard (apps.dashboard)
        # keeps using Django's normal staff login, unchanged. JWTAuthentication
        # is additive - it resolves request.user to a *real* auth.User (the
        # same model staff accounts use), no custom user-resolution needed.
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        # Deliberately still AllowAny by default: existing endpoints
        # (transactions/execute, gateway heartbeat, payment webhooks) are not
        # locked down in this change to avoid breaking the Flutter app and the
        # Android Gateway before they can actually obtain a JWT. Individual
        # views opt into IsAuthenticated explicitly (see apps.accounts) as
        # they're migrated - see the production audit for the follow-up plan.
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

default_origins = 'http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000,http://127.0.0.1:8080'
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CORS_ALLOWED_ORIGINS', default_origins).split(',')
    if origin.strip()
]
default_csrf_origins = 'http://localhost:3000,http://localhost:8000,http://127.0.0.1:3000,http://127.0.0.1:8000'
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', default_csrf_origins).split(',')
    if origin.strip()
]

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SECURE_SSL_REDIRECT', 'false').lower() == 'true'
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '0' if DEBUG else '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CINETPAY_API_KEY = os.environ.get('CINETPAY_API_KEY', '')
CINETPAY_SITE_ID = os.environ.get('CINETPAY_SITE_ID', '')
CINETPAY_SECRET_KEY = os.environ.get('CINETPAY_SECRET_KEY', '')
CINETPAY_INIT_URL = os.environ.get('CINETPAY_INIT_URL', 'https://api-checkout.cinetpay.com/v2/payment')
CINETPAY_CHECK_URL = os.environ.get('CINETPAY_CHECK_URL', 'https://api-checkout.cinetpay.com/v2/payment/check')
CINETPAY_CURRENCY = os.environ.get('CINETPAY_CURRENCY', 'XOF')
CINETPAY_NOTIFY_URL = os.environ.get('CINETPAY_NOTIFY_URL', 'http://127.0.0.1:8000/api/payments/cinetpay/notify/')
CINETPAY_RETURN_URL = os.environ.get('CINETPAY_RETURN_URL', 'http://127.0.0.1:3000/payment/success')
CINETPAY_CANCEL_URL = os.environ.get('CINETPAY_CANCEL_URL', 'http://127.0.0.1:3000/payment/cancel')
CINETPAY_CHANNELS = os.environ.get('CINETPAY_CHANNELS', 'MOBILE_MONEY')
CINETPAY_LANG = os.environ.get('CINETPAY_LANG', 'fr')
CINETPAY_TIMEOUT_SECONDS = int(os.environ.get('CINETPAY_TIMEOUT_SECONDS', '20'))
CINETPAY_ALLOW_MOCK = os.environ.get('CINETPAY_ALLOW_MOCK', 'true').lower() == 'true'

GENIUSPAY_API_KEY = os.environ.get('GENIUSPAY_API_KEY', '')
GENIUSPAY_API_SECRET = os.environ.get('GENIUSPAY_API_SECRET', '')
GENIUSPAY_BASE_URL = os.environ.get('GENIUSPAY_BASE_URL', 'https://geniuspay.ci/api/v1/merchant')
GENIUSPAY_WEBHOOK_SECRET = os.environ.get('GENIUSPAY_WEBHOOK_SECRET', '')
GENIUSPAY_CURRENCY = os.environ.get('GENIUSPAY_CURRENCY', 'XOF')
GENIUSPAY_SUCCESS_URL = os.environ.get('GENIUSPAY_SUCCESS_URL', 'http://127.0.0.1:3000/payment/success')
GENIUSPAY_ERROR_URL = os.environ.get('GENIUSPAY_ERROR_URL', 'http://127.0.0.1:3000/payment/cancel')
GENIUSPAY_TIMEOUT_SECONDS = int(os.environ.get('GENIUSPAY_TIMEOUT_SECONDS', '30'))
GENIUSPAY_ALLOW_MOCK = os.environ.get('GENIUSPAY_ALLOW_MOCK', 'true').lower() == 'true'

FEEXPAY_API_KEY = os.environ.get('FEEXPAY_API_KEY', '')
FEEXPAY_SHOP = os.environ.get('FEEXPAY_SHOP', '')
FEEXPAY_BASE_URL = os.environ.get('FEEXPAY_BASE_URL', 'https://api-v2.feexpay.me')
FEEXPAY_CHANNELS = {
    'mtn': os.environ.get('FEEXPAY_CHANNEL_MTN', 'mtn_ci'),
    'moov': os.environ.get('FEEXPAY_CHANNEL_MOOV', 'moov_ci'),
    'wave': os.environ.get('FEEXPAY_CHANNEL_WAVE', 'wave_ci'),
    'orange': os.environ.get('FEEXPAY_CHANNEL_ORANGE', 'orange_ci'),
}
FEEXPAY_TIMEOUT_SECONDS = int(os.environ.get('FEEXPAY_TIMEOUT_SECONDS', '20'))
PAYMENT_PROVIDER_ORDER = os.environ.get('PAYMENT_PROVIDER_ORDER', 'feexpay,geniuspay')

# Aion Messaging - the sole OTP provider (see apps/accounts/services.py).
# /verify/start and /verify/check generate, deliver AND verify the code on
# Aion's side - Django keeps no OTP state of its own (no mock mode: every
# request_otp()/verify_otp() call really reaches Aion; tests mock
# requests.post directly instead, see apps/accounts/tests.py).
AION_API_KEY = os.environ.get('AION_API_KEY', '')
AION_BASE_URL = os.environ.get('AION_BASE_URL', 'https://aionmessaging.com/api/v1/')
AION_SENDER_ID = os.environ.get('AION_SENDER_ID', '')
# Only ever read from the environment for a gated real-provider test (see
# apps/accounts/tests.py) - never a default value used by the application.
OTP_TEST_PHONE_NUMBER = os.environ.get('OTP_TEST_PHONE_NUMBER', '')

CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.environ.get('CIRCUIT_BREAKER_FAILURE_THRESHOLD', '5'))
CIRCUIT_BREAKER_RESET_SECONDS = int(os.environ.get('CIRCUIT_BREAKER_RESET_SECONDS', '60'))

# Transaction Engine / Gateway Manager (Phase B) - thresholds only, never business
# logic. Two dicts, not a class: adding a future key never requires a migration
# or a signature change anywhere that reads them.
TRANSACTION_ENGINE = {
    "MAX_RETRY": int(os.environ.get("TXN_MAX_RETRY", "3")),
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
