import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Comment, Group, Meeting, Post, Registration, Senior, User
from app.db.session import database_url, get_session
from app.main import app
from scripts import seed_non_call_demo as demo


@pytest.fixture(params=["7ac4d29b10ef", "head"])
def demo_engine(request, monkeypatch):
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("RUN_DB_TESTS=1 enables PostgreSQL tests")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    schema = "test_demo_" + uuid4().hex
    admin = create_engine(database_url(), hide_parameters=True)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        database_url(),
        hide_parameters=True,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000"},
    )
    try:
        with engine.begin() as conn:
            config = Config("alembic.ini")
            config.attributes["connection"] = conn
            command.upgrade(config, request.param)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
        get_settings.cache_clear()


def test_seed_preserves_edits_cancellation_and_deleted_comment(demo_engine):
    with Session(demo_engine) as session, session.begin():
        assert demo.seed(session)
    with Session(demo_engine) as session, session.begin():
        session.get(Group, demo.demo_id("group", "walk")).name = "팀이 수정한 이름"
        registration = session.get(Registration, demo.demo_id("registration", "member-walk"))
        registration.status = "canceled"
        registration.version = 2
        session.delete(session.get(Comment, demo.demo_id("comment", "welcome")))
        first_time = session.get(Meeting, demo.demo_id("meeting", "walk")).starts_at
    with Session(demo_engine) as session, session.begin():
        assert demo.seed(session) is False
        assert session.get(Group, demo.demo_id("group", "walk")).name == "팀이 수정한 이름"
        assert (
            session.get(Registration, demo.demo_id("registration", "member-walk")).status
            == "canceled"
        )
        assert session.get(Comment, demo.demo_id("comment", "welcome")) is None
        assert session.get(Meeting, demo.demo_id("meeting", "walk")).starts_at == first_time
        assert session.scalar(select(func.count()).select_from(User)) == 4
        assert session.scalar(select(func.count()).select_from(Post)) == 3


def test_seed_rolls_back_all_data_on_late_failure(demo_engine, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("simulated late write failure")

    monkeypatch.setattr(demo, "Comment", fail)
    with pytest.raises(RuntimeError, match="simulated"):
        with Session(demo_engine) as session, session.begin():
            demo.seed(session)
    with Session(demo_engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0
        assert session.scalar(select(func.count()).select_from(Meeting)) == 0


def test_seed_refuses_partial_existing_batch(demo_engine):
    with Session(demo_engine) as session, session.begin():
        session.execute(User.__table__.insert().values(id=demo.demo_id("user", "owner")))
    with pytest.raises(ValueError, match="일부만"):
        with Session(demo_engine) as session, session.begin():
            demo.seed(session)
    with Session(demo_engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(Senior)) == 0


def test_demo_accounts_support_non_call_api_workflow(demo_engine):
    with Session(demo_engine) as session, session.begin():
        demo.seed(session)
    with demo_engine.begin() as conn:
        config = Config("alembic.ini")
        config.attributes["connection"] = conn
        command.upgrade(config, "head")

    def override():
        with Session(demo_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    ids = demo.manifest()
    try:
        with TestClient(app) as client:
            assert client.get("/api/groups").status_code == 401
            client.headers["Authorization"] = (
                "Bearer " + ids["accounts"]["unverified"]["swagger_token"]
            )
            assert client.get("/api/groups").status_code == 200
            client.headers["Authorization"] = "Bearer " + ids["accounts"]["member"]["swagger_token"]
            assert len(client.get("/api/groups").json()["items"]) == 2
            assert len(client.get("/api/meetings").json()["items"]) == 4
            full = ids["meetings"]["full"]
            result = client.post(
                f"/api/meetings/{full}/registrations", headers={"Idempotency-Key": "full"}
            )
            assert result.status_code == 409
            solo = ids["meetings"]["solo"]
            path = f"/api/meetings/{solo}/registrations"
            registered = client.post(path, headers={"Idempotency-Key": "solo"})
            assert registered.status_code == 201
            repeated = client.post(path, headers={"Idempotency-Key": "solo"})
            assert repeated.json() == registered.json()
            assert (
                client.delete(
                    f"{path}/{registered.json()['id']}", headers={"If-Match": '"1"'}
                ).status_code
                == 204
            )
            group = ids["groups"]["walk"]
            assert (
                client.patch(f"/api/groups/{group}", json={"name": "unauthorized"}).status_code
                == 403
            )
            posts = client.get(f"/api/groups/{group}/posts")
            assert len(posts.json()["items"]) == 2
            post = ids["posts"]["hello"]
            assert (
                client.patch(f"/api/posts/{post}", json={"title": "수정 테스트"}).status_code == 200
            )
            assert (
                client.post(f"/api/posts/{post}/comments", json={"content": "새 댓글"}).status_code
                == 201
            )
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.parametrize(
    ("app_env", "opt_in"),
    [("production", "1"), ("test", "0")],
)
def test_cli_guard_before_database(monkeypatch, app_env, opt_in):
    monkeypatch.setattr(demo, "get_settings", lambda: SimpleNamespace(app_env=app_env))
    monkeypatch.setenv("SEED_NON_CALL_DEMO", opt_in)

    def fail():
        pytest.fail("guard must reject before accessing the DB")

    monkeypatch.setattr(demo, "get_engine", fail)
    with pytest.raises(SystemExit):
        demo.main()
