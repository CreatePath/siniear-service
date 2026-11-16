from unittest.mock import AsyncMock

import psycopg
import pytest

from app.api import health


def test_readiness_checks_database(client, monkeypatch):
    check = AsyncMock()
    monkeypatch.setattr(health, "check_database", check)
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    check.assert_awaited_once()


@pytest.mark.parametrize(
    "error", [psycopg.OperationalError("private connection details"), TimeoutError()]
)
def test_database_failure_keeps_liveness_and_hides_details(client, monkeypatch, error):
    monkeypatch.setattr(health, "check_database", AsyncMock(side_effect=error))
    assert client.get("/api/health").status_code == 200
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
