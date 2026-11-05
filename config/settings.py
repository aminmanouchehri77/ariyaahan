"""Settings for the Aria Steel website."""

import os
import ast
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_project_env():
    """Load simple KEY=value settings without overriding the shell environment."""
    env_path = BASE_DIR / '.env'
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, separator, value = line.partition('=')
        key = key.strip()
        if not separator or not key or not key.replace('_', '').isalnum():
            continue
        value = value.strip()
        if value.startswith(('"', "'")):
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].rstrip()
        os.environ.setdefault(key, str(value))


load_project_env()

DEBUG = os.getenv("DEBUG", "1").strip().lower() in {"1", "true", "yes", "on"}
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-this-key")
if not DEBUG and SECRET_KEY == "dev-only-change-this-key":
    raise RuntimeError("Set DJANGO_SECRET_KEY before running with DEBUG=0.")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'accounts.apps.AccountsConfig',
    'core.apps.CoreConfig',
    'catalog.apps.CatalogConfig',
    'pricing.apps.PricingConfig',
    'marketplace.apps.MarketplaceConfig',
    'inquiries.apps.InquiriesConfig',
    'orders.apps.OrdersConfig',
    'content.apps.ContentConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.navigation_categories',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


DATABASE_ENGINE = os.getenv("DB_ENGINE", "django.db.backends.mysql").strip()
DATABASES = {
    'default': {
        'ENGINE': DATABASE_ENGINE,
        'NAME': os.getenv("DB_NAME", "ariaahan"),
        'USER': os.getenv("DB_USER", "ariaahan_app"),
        'PASSWORD': os.getenv("DB_PASSWORD", ""),
        'HOST': os.getenv("DB_HOST", "127.0.0.1"),
        'PORT': os.getenv("DB_PORT", "3306"),
        'CONN_MAX_AGE': int(os.getenv("DB_CONN_MAX_AGE", "0")),
    }
}
if DATABASE_ENGINE.endswith("mysql"):
    DATABASES['default']['OPTIONS'] = {
        'charset': 'utf8mb4',
        'isolation_level': 'read committed',
    }
elif DATABASE_ENGINE.endswith("sqlite3"):
    DATABASES['default']['NAME'] = os.getenv("DB_NAME", str(BASE_DIR / 'db.sqlite3'))


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:profile'
LOGOUT_REDIRECT_URL = 'core:home'

# Development prints OTP messages to the runserver console unless Kavenegar is
# configured. Production defaults to Kavenegar and requires its credentials.
KAVENEGAR_API_KEY = os.getenv('KAVENEGAR_API_KEY', '').strip()
KAVENEGAR_OTP_TEMPLATE = os.getenv('KAVENEGAR_OTP_TEMPLATE', '').strip()
KAVENEGAR_ACCEPT_TEMPLATE = os.getenv('KAVENEGAR_ACCEPT_TEMPLATE', '').strip()
KAVENEGAR_TIMEOUT = float(os.getenv('KAVENEGAR_TIMEOUT', '10'))
DEFAULT_SMS_BACKEND = (
    'accounts.sms.KavenegarVerifyLookupBackend'
    if (KAVENEGAR_API_KEY and KAVENEGAR_OTP_TEMPLATE) or not DEBUG
    else 'accounts.sms.ConsoleSMSBackend'
)
SMS_BACKEND = os.getenv('SMS_BACKEND', DEFAULT_SMS_BACKEND).strip()
if not DEBUG:
    backend_name = SMS_BACKEND.rsplit('.', 1)[-1]
    if backend_name == 'ConsoleSMSBackend':
        raise RuntimeError(
            'The console SMS backend is development-only. Configure a production SMS backend before startup.'
        )
    if backend_name == 'KavenegarVerifyLookupBackend':
        missing_kavenegar_settings = [
            name for name, value in (
                ('KAVENEGAR_API_KEY', KAVENEGAR_API_KEY),
                ('KAVENEGAR_OTP_TEMPLATE', KAVENEGAR_OTP_TEMPLATE),
                ('KAVENEGAR_ACCEPT_TEMPLATE', KAVENEGAR_ACCEPT_TEMPLATE),
            ) if not value
        ]
        if missing_kavenegar_settings:
            raise RuntimeError(
                'Configure these Kavenegar settings before production startup: '
                + ', '.join(missing_kavenegar_settings)
            )
OTP_EXPIRY_SECONDS = int(os.getenv('OTP_EXPIRY_SECONDS', '300'))
OTP_RESEND_SECONDS = int(os.getenv('OTP_RESEND_SECONDS', '60'))
OTP_MAX_SENDS_PER_HOUR = int(os.getenv('OTP_MAX_SENDS_PER_HOUR', '5'))
OTP_MAX_ATTEMPTS = int(os.getenv('OTP_MAX_ATTEMPTS', '5'))
VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY', '').strip()
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY', '').strip()
VAPID_PRIVATE_KEY_FILE = os.getenv('VAPID_PRIVATE_KEY_FILE', '').strip()
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@localhost').strip()
VAPID_CLAIMS_EMAIL = os.getenv('VAPID_CLAIMS_EMAIL', DEFAULT_FROM_EMAIL).strip()
PUSH_DELIVERY_ENABLED = os.getenv('PUSH_DELIVERY_ENABLED', '0').strip().lower() in {'1', 'true', 'yes', 'on'}
PUSH_ALLOWED_HOST_SUFFIXES = tuple(
    host.strip().lower().lstrip('.')
    for host in os.getenv(
        'PUSH_ALLOWED_HOST_SUFFIXES',
        'fcm.googleapis.com,fcmregistrations.googleapis.com,push.services.mozilla.com,notify.windows.com,push.apple.com',
    ).split(',')
    if host.strip()
)
PUBLIC_SITE_URL = os.getenv('PUBLIC_SITE_URL', '').strip().rstrip('/')
TWA_PACKAGE_NAME = os.getenv('TWA_PACKAGE_NAME', '').strip()
TWA_SHA256_CERT_FINGERPRINTS = os.getenv('TWA_SHA256_CERT_FINGERPRINTS', '').strip()
PAYMENT_PROVIDER = os.getenv('PAYMENT_PROVIDER', '').strip()
PAYMENT_MERCHANT_ID = os.getenv('PAYMENT_MERCHANT_ID', '').strip()


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'fa-ir'

TIME_ZONE = 'Asia/Tehran'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "1").strip().lower() in {"1", "true", "yes", "on"}
    SECURE_HSTS_SECONDS = max(0, int(os.getenv('SECURE_HSTS_SECONDS', '0')))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', '0').strip().lower() in {"1", "true", "yes", "on"}
