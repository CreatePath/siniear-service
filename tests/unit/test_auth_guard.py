import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_development_auth():
    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None, db_password="test-only", app_env="production", dev_auth_enabled=True
        )
    assert "test-only" not in str(error.value)


def test_development_auth_is_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("DEV_AUTH_ENABLED", raising=False)
    settings = Settings(_env_file=None, db_password="test-only", app_env="development")
    assert settings.dev_auth_enabled is False
