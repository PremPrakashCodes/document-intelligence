"""Settings: the URL and endpoint derivations other layers depend on."""

import pytest

from api.config import Settings


class TestSqlalchemyUrl:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
            ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
            ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
            ("sqlite+aiosqlite://", "sqlite+aiosqlite://"),
        ],
    )
    def test_adds_the_async_driver_without_disturbing_env(self, given, expected):
        """.env keeps the plain form BullMQ and psycopg want; SQLAlchemy needs
        the driver named, so the two must never be edited apart."""
        assert Settings(database_url=given).sqlalchemy_url == expected


class TestDerived:
    def test_r2_endpoint_defaults_to_the_account_url(self):
        settings = Settings(r2_account_id="abc")
        assert settings.r2_endpoint == "https://abc.r2.cloudflarestorage.com"

    def test_r2_endpoint_override_wins(self):
        settings = Settings(r2_account_id="abc", r2_endpoint_url="http://localhost:9000")
        assert settings.r2_endpoint == "http://localhost:9000"

    def test_configuration_flags(self):
        assert not Settings(azure_di_endpoint="", azure_di_key="").azure_di_configured
        assert Settings(azure_di_endpoint="https://x/", azure_di_key="k").azure_di_configured
        assert not Settings(r2_access_key_id="", r2_secret_access_key="").r2_configured

    def test_allowed_origins_splits_and_trims(self):
        settings = Settings(cors_origins="http://a , http://b,, ")
        assert settings.allowed_origins == ["http://a", "http://b"]
