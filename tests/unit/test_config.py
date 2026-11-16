import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_database_password_is_required(monkeypatch):
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_password_is_not_in_repr():
    settings = Settings(db_password="test-only-password", _env_file=None)
    assert "test-only-password" not in repr(settings)
