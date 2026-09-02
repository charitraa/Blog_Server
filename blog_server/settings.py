"""
Django settings for blog_server project.

All environment-specific values are read from the environment (see `.env.example`).
Nothing secret is hard-coded here.
"""

from datetime import timedelta
from pathlib import Path
import os
import sys
from decouple import config, Csv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY')

DEBUG = config('DEBUG', default=False, cast=bool)

# Comma separated list, e.g. "api.example.com,example.com". Local hosts are
# always allowed while DEBUG is on so development needs no extra configuration.
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='', cast=Csv())
if DEBUG:
    ALLOWED_HOSTS += ['localhost', '127.0.0.1', '[::1]', 'testserver']

# Public base URL of this API, used to build absolute media URLs in emails.
BACKEND_URL = config('BACKEND_URL', default='http://localhost:8000')
# Public base URL of the SPA, used for links inside emails.
FRONTEND_URL = config('FRONTEND_URL', default='http://localhost:8080')


# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    # Cloudinary. `cloudinary_storage` must precede staticfiles so its storage
    # backends are importable; `cloudinary` carries the SDK configuration.
    'cloudinary_storage',
    'cloudinary',
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'django_filters',
    'drf_spectacular',
    'corsheaders',
    'apps.user',
    'apps.post',
    'apps.comment',
    'apps.newsletter',
    'apps.notification',
    'apps.ai',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'blog_server.api_logging.APILoggingMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'blog_server.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'blog_server.wsgi.application'


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Defaults to the existing SQLite database so local setups keep working. Set
# DB_ENGINE/DB_NAME/... in the environment to point at MySQL/Postgres instead.

DB_ENGINE = config('DB_ENGINE', default='django.db.backends.sqlite3')

if DB_ENGINE == 'django.db.backends.sqlite3':
    DATABASES = {
        'default': {
            'ENGINE': DB_ENGINE,
            'NAME': config('DB_NAME', default=str(BASE_DIR / 'db.sqlite3')),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': DB_ENGINE,
            'NAME': config('DB_NAME'),
            'USER': config('DB_USER', default=''),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default=''),
            'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=60, cast=int),
        }
    }


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

AUTHENTICATION_BACKENDS = [
    'apps.user.backends.EmailOrUsernameBackend',
    'django.contrib.auth.backends.ModelBackend',
]


# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# ---------------------------------------------------------------------------
# Static / media files
# ---------------------------------------------------------------------------

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Local media. Still used in development, and still the fallback whenever
# Cloudinary is not configured, so a checkout with no credentials runs exactly
# as it always did.
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


# ---------------------------------------------------------------------------
# Cloudinary (user-uploaded media)
# ---------------------------------------------------------------------------
#
# Render's filesystem is ephemeral: anything written to MEDIA_ROOT is lost on
# the next deploy or restart. Uploads therefore go to Cloudinary in production.
#
# Static files are deliberately NOT moved there — they are built into the image
# by `collectstatic` and served by the app, which is already reliable on Render.

CLOUDINARY_CLOUD_NAME = config('CLOUDINARY_CLOUD_NAME', default='')
CLOUDINARY_API_KEY = config('CLOUDINARY_API_KEY', default='')
CLOUDINARY_API_SECRET = config('CLOUDINARY_API_SECRET', default='')

# All three are required; a partial configuration would fail at upload time
# rather than at boot, which is a much worse place to discover it.
USE_CLOUDINARY = all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET])

if USE_CLOUDINARY:
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': CLOUDINARY_CLOUD_NAME,
        'API_KEY': CLOUDINARY_API_KEY,
        'API_SECRET': CLOUDINARY_API_SECRET,
        # Always hand the frontend an https URL; a mixed-content image would be
        # blocked outright by the browser.
        'SECURE': True,
    }

    STORAGES = {
        'default': {
            'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }
else:
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }

    if not DEBUG:
        # Production without Cloudinary means uploads vanish on the next deploy.
        # Worth a loud line in the log rather than a silent data-loss bug.
        import logging as _logging

        _logging.getLogger('django').warning(
            'Cloudinary is not configured and DEBUG is off. Uploaded media will '
            'be written to the local filesystem and lost on the next restart. '
            'Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET.'
        )

# Hard ceiling for uploads handled in memory. Per-field limits live in the
# serializers (see blog_server/validators.py).
DATA_UPLOAD_MAX_MEMORY_SIZE = config('DATA_UPLOAD_MAX_MEMORY_SIZE', default=10 * 1024 * 1024, cast=int)
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE

# Maximum accepted size for user uploaded images, in bytes.
MAX_IMAGE_UPLOAD_SIZE = config('MAX_IMAGE_UPLOAD_SIZE', default=5 * 1024 * 1024, cast=int)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'user.User'


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    'NON_FIELD_ERRORS_KEY': 'error',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        # Accepts `Authorization: Bearer <token>` and, for backwards
        # compatibility with the original cookie login, an `access_token` cookie.
        'apps.user.authentication.CookieOrHeaderJWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ),
    'DEFAULT_PAGINATION_CLASS': 'blog_server.pagination.StandardPagination',
    'PAGE_SIZE': config('PAGE_SIZE', default=10, cast=int),
    'EXCEPTION_HANDLER': 'blog_server.exceptions.custom_exception_handler',
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': config('THROTTLE_USER', default='2000/day'),
        'anon': config('THROTTLE_ANON', default='300/day'),
        # Tight budgets on the endpoints worth brute-forcing.
        'auth': config('THROTTLE_AUTH', default='20/hour'),
        'register': config('THROTTLE_REGISTER', default='10/hour'),
        'write': config('THROTTLE_WRITE', default='120/hour'),
        # Every AI call costs money at the provider, so it gets its own budget
        # rather than sharing the general write allowance.
        'ai': config('THROTTLE_AI', default='40/hour'),
    },
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Mindful Blog API',
    'DESCRIPTION': (
        'REST API powering the Mindful Blog publishing platform: authentication, '
        'posts, categories, tags, likes, comments, profiles and dashboard statistics.'
    ),
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': '/api',
}


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=config('ACCESS_TOKEN_MINUTES', default=60, cast=int)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=config('REFRESH_TOKEN_DAYS', default=7, cast=int)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# Names of the cookies the auth views mirror the tokens into. The SPA can
# authenticate with the `Authorization` header alone and never touch these,
# but keeping the refresh token in an httpOnly cookie means a client can hold
# the short-lived access token in memory and still survive a page reload.
AUTH_COOKIE_NAME = 'access_token'
REFRESH_COOKIE_NAME = 'refresh_token'


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

# Brevo (formerly Sendinblue) handles delivery when a key is present. It is
# preferred over raw SMTP because it reports opens and clicks — a plain SMTP
# server physically cannot, since tracking means rewriting links and embedding
# a pixel, which only the sending service can do.
BREVO_API_KEY = config('BREVO_API_KEY', default='')
BREVO_SENDER_EMAIL = config('BREVO_SENDER_EMAIL', default='')
BREVO_SENDER_NAME = config('BREVO_SENDER_NAME', default='')
# The Brevo contact list confirmed newsletter subscribers are added to.
BREVO_LIST_ID = config('BREVO_LIST_ID', default=0, cast=int)

EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='').strip()
# Google displays an app password as four groups of four ("abcd efgh ijkl mnop"),
# but SMTP will not accept those spaces. Stripping them here means a password
# pasted straight from the Google page works instead of failing as bad credentials.
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='').replace(' ', '').strip()

# Brevo first, SMTP second, console last. The console fallback means a fresh
# checkout with no credentials still runs and shows you the emails.
if BREVO_API_KEY:
    EMAIL_BACKEND = 'apps.newsletter.backends.BrevoEmailBackend'
elif EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
# Gmail (and most providers) refuse to send as an address the authenticated
# account does not own, so a made-up From silently breaks every email. Fall back
# to the account itself, and ignore a configured value that cannot work.
_configured_from = config('DEFAULT_FROM_EMAIL', default='').strip()
if EMAIL_HOST_USER and _configured_from.endswith(('.local', '.invalid', '.example')):
    DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
else:
    DEFAULT_FROM_EMAIL = _configured_from or EMAIL_HOST_USER or 'no-reply@mindfulblog.local'

SITE_NAME = config('SITE_NAME', default='Mindful Blog')

# New accounts must confirm the emailed code before they can log in.
REQUIRE_EMAIL_VERIFICATION = config('REQUIRE_EMAIL_VERIFICATION', default=True, cast=bool)
LOGIN_CODE_TTL_MINUTES = config('LOGIN_CODE_TTL_MINUTES', default=10, cast=int)


# ---------------------------------------------------------------------------
# Security / CORS / CSRF
# ---------------------------------------------------------------------------

# Only the real frontend origins may call the API. Never "allow all" in production.
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:8080,http://127.0.0.1:8080',
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False

CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default=','.join(CORS_ALLOWED_ORIGINS),
    cast=Csv(),
)

# Cookies may only carry the Secure flag over HTTPS, so keep it off in development.
COOKIE_SECURE = config('COOKIE_SECURE', default=not DEBUG, cast=bool)
COOKIE_SAMESITE = config('COOKIE_SAMESITE', default='None' if COOKIE_SECURE else 'Lax')

CSRF_COOKIE_SECURE = COOKIE_SECURE
SESSION_COOKIE_SECURE = COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = COOKIE_SAMESITE
CSRF_COOKIE_SAMESITE = COOKIE_SAMESITE
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

if not DEBUG:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# ---------------------------------------------------------------------------
# Social auth
# ---------------------------------------------------------------------------

GITHUB_CLIENT_ID = config('GITHUB_CLIENT_ID', default='')
GITHUB_SECRET = config('GITHUB_SECRET', default='')

GOOGLE_CLIENT_ID = config('GOOGLE_CLIENT_ID', default='')
GOOGLE_SECRET = config('GOOGLE_SECRET', default='')
# Google validates the redirect_uri against the one registered for the client,
# so the default has to match whatever the SPA actually sends.
GOOGLE_REDIRECT_URI = config(
    'GOOGLE_REDIRECT_URI',
    default=f'{FRONTEND_URL.rstrip("/")}/auth/callback/google',
)

# How long an emailed password-reset link stays usable.
PASSWORD_RESET_TTL_MINUTES = config('PASSWORD_RESET_TTL_MINUTES', default=30, cast=int)
# ---------------------------------------------------------------------------
# reCAPTCHA
# ---------------------------------------------------------------------------
#
# Guards registration and the two endpoints that email an address the requester
# chose. Off unless a secret is set, so development needs no keys.
#
# The site key is public by design — it ships in the HTML of every site using
# reCAPTCHA. The secret is server-side only and must never reach the frontend.

RECAPTCHA_ENABLED = config('RECAPTCHA_ENABLED', default=True, cast=bool)
RECAPTCHA_SITE_KEY = config('RECAPTCHA_SITE_KEY', default='')
RECAPTCHA_SECRET_KEY = config('RECAPTCHA_SECRET_KEY', default='')
# Only consulted for v3 keys, which return a score. v2 sends none and is
# judged on success alone. 0.5 is Google's suggested starting point.
RECAPTCHA_MIN_SCORE = config('RECAPTCHA_MIN_SCORE', default=0.5, cast=float)


# ---------------------------------------------------------------------------
# AI assistant
# ---------------------------------------------------------------------------
#
# Optional. With no API key the endpoints report themselves as unavailable and
# the editor hides the assistant, rather than offering buttons that fail.

AI_ENABLED = config('AI_ENABLED', default=True, cast=bool)
AI_PREFERRED_PROVIDER = config('AI_PREFERRED_PROVIDER', default='nvidia')

# NVIDIA NIM speaks the OpenAI chat-completions dialect.
NVIDIA_BASE_URL = config('NVIDIA_BASE_URL', default='https://integrate.api.nvidia.com/v1')
NVIDIA_API_KEY = config('NVIDIA_API_KEY', default='')

# Main model: returns clean answers with its reasoning in a separate field.
NVIDIA_MODEL = config('NVIDIA_MODEL', default='openai/gpt-oss-120b')
# Smaller sibling for short, cheap tasks (tags, proofreading, social posts).
NVIDIA_FAST_MODEL = config('NVIDIA_FAST_MODEL', default='openai/gpt-oss-20b')
# Purpose-built models beat the general one at their own job.
NVIDIA_TRANSLATE_MODEL = config(
    'NVIDIA_TRANSLATE_MODEL', default='nvidia/riva-translate-4b-instruct-v2',
)
NVIDIA_SAFETY_MODEL = config(
    'NVIDIA_SAFETY_MODEL', default='nvidia/llama-3.1-nemoguard-8b-content-safety',
)
# Powers semantic search and vector-based related posts. Chosen by measurement:
# of the seven embedding models in the catalogue only two are enabled for this
# account, and this one separated related from unrelated text most cleanly.
NVIDIA_EMBED_MODEL = config('NVIDIA_EMBED_MODEL', default='nvidia/nemotron-3-embed-1b')


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

# Throttle counters live here.
#
# A file-based cache rather than in-memory: LocMemCache is per-process, so a
# multi-worker deployment would give every worker its own separate rate limit.
# Backing it with a directory means all workers on a host share one budget with
# no extra service to run.
CACHE_DIR = os.path.join(BASE_DIR, '.cache')

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': CACHE_DIR,
        'OPTIONS': {
            # Old entries are culled when the directory reaches this size, so a
            # busy site cannot fill the disk with expired throttle counters.
            'MAX_ENTRIES': 5000,
        },
    }
}

os.makedirs(CACHE_DIR, exist_ok=True)

# Under the test runner every request comes from the same address, so a shared
# throttle counter would leak between unrelated tests and fail them at random.
# Throttling itself is covered by its own tests, which install a real cache.
if 'test' in sys.argv:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}}

    # Likewise the CAPTCHA. Whether it is on would otherwise depend on which
    # keys the developer running the suite happens to have in their own .env,
    # so every guarded endpoint would pass or fail by accident. The tests that
    # are actually about the CAPTCHA switch it on explicitly.
    RECAPTCHA_ENABLED = False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

from .logging_utils import SimpleColoredFormatter  # noqa: E402

LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple_colored': {
            '()': SimpleColoredFormatter,
        },
        'verbose': {  # For log files
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple_colored',
        },
        'error_file': {
            'class': 'logging.FileHandler',
            'filename': os.path.join(LOG_DIR, 'errors.log'),
            'formatter': 'verbose',
            'level': 'ERROR',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'error_file'],
            'level': 'INFO',
            'propagate': True,
        },
        'apps': {
            'handlers': ['console', 'error_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
