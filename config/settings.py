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
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Central tuning knobs for the rule-based adaptive learning engine.
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

