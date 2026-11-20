import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PROBE = """
import json
from config import settings
database = settings.DATABASES["default"]
print(json.dumps({
    "debug": settings.DEBUG,
    "engine": database["ENGINE"],
    "name": str(database.get("NAME")),
    "user": database.get("USER"),
    "credentials_match": (
        database.get("USER") == "user@name"
        and database.get("PASSWORD") == "p@ss:word"
    ),
    "conn_max_age": database.get("CONN_MAX_AGE"),
    "sslmode": database.get("OPTIONS", {}).get("sslmode"),
    "channel_binding": database.get("OPTIONS", {}).get("channel_binding"),
    "connect_timeout": database.get("OPTIONS", {}).get("connect_timeout"),
}))
"""


class DatabaseSettingsTests(SimpleTestCase):
    def run_settings_probe(self, **overrides):
        environment = os.environ.copy()
        for key in (
            "DATABASE_URL",
            "DJANGO_ENV",
            "DJANGO_DEBUG",
            "DJANGO_SECRET_KEY",
            "VERCEL",
            "VERCEL_ENV",
        ):
            environment.pop(key, None)
        environment["DJANGO_SECRET_KEY"] = "database-settings-test-only-key"
        environment.update(overrides)
        return subprocess.run(
            [sys.executable, "-c", SETTINGS_PROBE],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_local_settings_keep_sqlite_when_database_url_is_absent(self):
        result = self.run_settings_probe()

        self.assertEqual(result.returncode, 0, result.stderr)
        configuration = json.loads(result.stdout)
        self.assertTrue(configuration["debug"])
        self.assertEqual(configuration["engine"], "django.db.backends.sqlite3")
        self.assertTrue(configuration["name"].endswith("db.sqlite3"))

    def test_vercel_production_uses_postgres_even_if_debug_is_requested(self):
        result = self.run_settings_probe(
            VERCEL="1",
            VERCEL_ENV="production",
            DJANGO_DEBUG="1",
            DATABASE_URL=(
                "postgresql://user%40name:p%40ss%3Aword@db.example:5432/eduplay"
                "?sslmode=verify-full&channel_binding=require&connect_timeout=8"
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        configuration = json.loads(result.stdout)
        self.assertFalse(configuration["debug"])
        self.assertEqual(configuration["engine"], "django.db.backends.postgresql")
        self.assertTrue(configuration["credentials_match"])
        self.assertEqual(configuration["conn_max_age"], 0)
        self.assertEqual(configuration["sslmode"], "verify-full")
        self.assertEqual(configuration["channel_binding"], "require")
        self.assertEqual(configuration["connect_timeout"], 8)

    def test_explicit_production_environment_uses_database_url_without_vercel_markers(self):
        result = self.run_settings_probe(
            DJANGO_ENV="production",
            DJANGO_DEBUG="1",
            DATABASE_URL=(
                "postgresql://user:password@db.example:5432/eduplay"
                "?sslmode=verify-full"
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        configuration = json.loads(result.stdout)
        self.assertFalse(configuration["debug"])
        self.assertEqual(configuration["engine"], "django.db.backends.postgresql")
        self.assertEqual(configuration["sslmode"], "verify-full")

    def test_neon_url_defaults_to_ssl_and_preserves_channel_binding(self):
        result = self.run_settings_probe(
            VERCEL_ENV="production",
            DATABASE_URL=(
                "postgresql://user:password@ep-example-pooler.region.aws.neon.tech"
                "/eduplay?channel_binding=require"
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        configuration = json.loads(result.stdout)
        self.assertEqual(configuration["sslmode"], "require")
        self.assertEqual(configuration["channel_binding"], "require")

    def test_vercel_production_does_not_fall_back_to_sqlite(self):
        result = self.run_settings_probe(
            VERCEL="1",
            VERCEL_ENV="production",
            DJANGO_DEBUG="1",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL is required for production deployments", result.stderr)
        self.assertNotIn("database-settings-test-only-key", result.stderr)

    def test_explicit_production_environment_requires_database_url_without_vercel_markers(self):
        result = self.run_settings_probe(
            DJANGO_ENV="production",
            DJANGO_DEBUG="1",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL is required for production deployments", result.stderr)
        self.assertNotIn("database-settings-test-only-key", result.stderr)

    def test_vercel_production_rejects_sqlite_database_url(self):
        result = self.run_settings_probe(
            VERCEL_ENV="production",
            DATABASE_URL="sqlite:///:memory:",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL must use PostgreSQL in production", result.stderr)

    def test_vercel_production_rejects_incomplete_postgresql_url(self):
        result = self.run_settings_probe(
            VERCEL_ENV="production",
            DATABASE_URL="postgresql://",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "DATABASE_URL must include a PostgreSQL database name, user, and host",
            result.stderr,
        )

    def test_invalid_database_url_reports_configuration_error_without_echoing_url(self):
        invalid_url = "not-a-valid-database-url"
        result = self.run_settings_probe(
            VERCEL_ENV="production",
            DATABASE_URL=invalid_url,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL is invalid", result.stderr)
        self.assertNotIn(invalid_url, result.stderr)
