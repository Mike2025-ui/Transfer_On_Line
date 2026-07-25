from pathlib import Path
import os

try:
    import dj_database_url
except ImportError:  # pragma: no cover - fallback for local development environments
    dj_database_url = None

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-local-dev-only')
DEBUG = os.environ.get('DJANGO_DEBUG', 'false').lower() == 'true'
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
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
    'apps.gateway',
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
]

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

LOGIN_REDIRECT_URL = '/dashboard/'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ]
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
CINETPAY_CURRENCY = os.environ.get('CINETPAY_CURRENCY', 'XOF')
CINETPAY_NOTIFY_URL = os.environ.get('CINETPAY_NOTIFY_URL', 'http://127.0.0.1:8000/api/payments/cinetpay/notify/')
CINETPAY_RETURN_URL = os.environ.get('CINETPAY_RETURN_URL', 'http://127.0.0.1:3000/payment/success')
CINETPAY_CANCEL_URL = os.environ.get('CINETPAY_CANCEL_URL', 'http://127.0.0.1:3000/payment/cancel')
CINETPAY_CHANNELS = os.environ.get('CINETPAY_CHANNELS', 'MOBILE_MONEY')
CINETPAY_LANG = os.environ.get('CINETPAY_LANG', 'fr')
CINETPAY_TIMEOUT_SECONDS = int(os.environ.get('CINETPAY_TIMEOUT_SECONDS', '20'))
CINETPAY_ALLOW_MOCK = os.environ.get('CINETPAY_ALLOW_MOCK', 'true').lower() == 'true'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO')},
}
