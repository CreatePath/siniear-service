import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import database_url, get_session
from app.main import app
from scripts.seed_dev import ids, seed


@pytest.fixture
def schema_engine(monkeypatch):
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("RUN_DB_TESTS=1 enables real PostgreSQL tests")
    monkeypatch.setenv("INTERVIEW_PROVIDER", "fake")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    schema = "test_" + uuid4().hex
    admin = create_engine(database_url(), hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        database_url(),
        hide_parameters=True,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000"},
    )
    try:
        yield engine
    finally:
        engine.dispose()
        # Only the random schema created by this fixture is removed.
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
        get_settings.cache_clear()


@pytest.fixture
def db_engine(schema_engine):
    with schema_engine.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    with Session(schema_engine) as session, session.begin():
        seed(session)
    return schema_engine


@pytest.fixture
def api(db_engine):
    def session_override():
        with Session(db_engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer dev:{ids('owner')[0]}"
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


def auth(name):
    return {"Authorization": f"Bearer dev:{ids(name)[0]}"}


def join(api, group_id, name="member"):
    path = f"/api/groups/{group_id}/join-requests"
    result = api.post(path, headers={**auth(name), "Idempotency-Key": group_id + name})
    assert result.status_code == 201
    decision = api.patch(path + "/" + result.json()["id"], json={"status": "approved"})
    assert decision.status_code == 200
