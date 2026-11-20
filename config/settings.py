"""Django settings for the EduPlay academic project."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is required. See README.md for a local setup command."
    )

DEBUG = os.environ.get("DJANGO_DEBUG", "1").strip().lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    ".vercel.app",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves compressed static files efficiently in production.
    # It must come directly after SecurityMiddleware and before everything else.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Production security settings
# These are only activated when DEBUG is False (i.e. in production).
# They are safe to leave here — they have no effect during local development.
# ---------------------------------------------------------------------------
if not DEBUG:
    # Redirect all non-HTTPS requests to HTTPS.
    SECURE_SSL_REDIRECT = True

    # Tell browsers to only connect via HTTPS for the next year (31536000 seconds).
    # includeSubDomains ensures subdomains are also protected.
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Cookies are only sent over HTTPS — prevents session hijacking.
    SESSION_COOKIE_SECURE = True

    # CSRF cookie is only sent over HTTPS — prevents CSRF token theft.
    CSRF_COOKIE_SECURE = True

    # Allow the application to detect HTTPS when behind a proxy or load balancer
    # (PythonAnywhere and most hosts terminate SSL at a proxy layer).
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # Trusted origins for CSRF. Must include your deployed domain.
    # Set via the DJANGO_CSRF_TRUSTED_ORIGINS environment variable.
    _csrf_origins = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")
    if _csrf_origins:
        CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(",") if o.strip()]

# ---------------------------------------------------------------------------
# Central tuning knobs for the rule-based adaptive learning engine.
# ---------------------------------------------------------------------------
ADAPTIVE_RECOMMENDATION_MIN_ANSWERS = 5
ADAPTIVE_RECOMMENDATION_BANDS = (
    {"minimum": 0, "maximum": 39, "difficulty": "Beginner", "approach": "Revision"},
    {"minimum": 40, "maximum": 69, "difficulty": "Guided", "approach": "Guided practice"},
    {"minimum": 70, "maximum": 89, "difficulty": "Intermediate", "approach": "Extension practice"},
    {"minimum": 90, "maximum": 100, "difficulty": "Advanced", "approach": "Advanced extension"},
)
ADAPTIVE_TOPIC_MIN_ANSWERS = 4
ADAPTIVE_TOPIC_MIN_DISTINCT_QUESTIONS = 2
ADAPTIVE_MASTERY_WEIGHTS = {"accuracy": 60, "coverage": 20, "completion": 10, "recency": 10}
ADAPTIVE_MASTERY_LEVEL_THRESHOLDS = {"mastered": 90, "proficient": 75, "developing": 50}
ADAPTIVE_STRENGTH_MASTERY_THRESHOLD = 75
ADAPTIVE_WEAKNESS_MASTERY_THRESHOLD = 55

# Collaborative Learning limits are enforced by the server-side service layer.
EDUPLAY_MAX_TEAM_SIZE = 6

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"

