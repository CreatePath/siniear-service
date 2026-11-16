from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from queue import Queue
from time import monotonic, sleep
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Comment, Post
from app.modules.auth.dependencies import Principal
from app.modules.community import service
from app.modules.community.repository import get_post
from app.modules.community.schemas import CommentWrite, PostPatch
from scripts.seed_dev import ids
from tests.integration.test_community import create_comment, create_post
from tests.integration.test_concurrency import race


@pytest.mark.parametrize(
    "operation",
    ["create_comment", "update_comment", "delete_comment", "update_post", "delete_post"],
)
def test_waiting_mutation_rechecks_committed_parent_deletion(api, db_engine, operation):
    post = create_post(api)
    comment = create_comment(api, post)
    post_id, comment_id = UUID(post["id"]), UUID(comment["id"])
    actor = Principal(*ids("other" if "comment" in operation else "member"))
    tasks = {
        "create_comment": lambda session: service.create_comment(
            session, actor, post_id, CommentWrite(content="추가")
        ),
        "update_comment": lambda session: service.update_comment(
            session, actor, comment_id, CommentWrite(content="수정")
        ),
        "delete_comment": lambda session: service.delete_comment(session, actor, comment_id),
        "update_post": lambda session: service.update_post(
            session, actor, post_id, PostPatch(title="수정")
        ),
        "delete_post": lambda session: service.delete_post(session, actor, post_id),
    }
    backend = Queue()

    def waiting_change():
        with db_engine.connect() as connection:
            backend.put(connection.scalar(text("SELECT pg_backend_pid()")))
            connection.commit()
            with Session(bind=connection, expire_on_commit=False) as session:
                try:
                    tasks[operation](session)
                except DomainError as error:
                    return error.status, error.code
        return "unexpected success"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(db_engine) as session, session.begin():
            row = get_post(session, post_id, lock=True)
            row.deleted_at = datetime.now(UTC)
            session.flush()
            future = pool.submit(waiting_change)
            pid = backend.get(timeout=3)
            # Observe a real PostgreSQL lock wait, rather than assuming thread timing.
            deadline = monotonic() + 3
            while monotonic() < deadline:
                blocked = session.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                )
                if blocked:
                    break
                sleep(0.01)
            else:
                pytest.fail("Mutation did not wait for the parent post lock")
        assert future.result(timeout=5) == (404, "POST_NOT_FOUND")
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(Comment)) == 1
        assert session.get(Comment, comment_id).content == comment["content"]
        assert session.get(Post, post_id).title == post["title"]


def test_two_comment_deletions_have_one_effect(api, db_engine):
    post = create_post(api)
    comment = create_comment(api, post)
    actor = Principal(*ids("other"))
    results = race(
        db_engine,
        lambda session: service.delete_comment(session, actor, UUID(comment["id"])),
        lambda session: service.delete_comment(session, actor, UUID(comment["id"])),
    )
    assert results.count(None) == 1
    assert results.count((404, "COMMENT_NOT_FOUND")) == 1
    assert api.get(f"/api/posts/{post['id']}").json()["comment_count"] == 0


def test_concurrent_partial_post_updates_preserve_both_fields(api, db_engine):
    post = create_post(api)
    actor = Principal(*ids("member"))
    results = race(
        db_engine,
        lambda session: service.update_post(
            session, actor, UUID(post["id"]), PostPatch(title="새 제목")
        ),
        lambda session: service.update_post(
            session, actor, UUID(post["id"]), PostPatch(content="새 본문")
        ),
    )
    assert all(result.id == UUID(post["id"]) for result in results)
    detail = api.get(f"/api/posts/{post['id']}").json()
    assert detail["title"] == "새 제목" and detail["content"] == "새 본문"


def test_failed_permission_rolls_back_and_releases_parent_lock(api, db_engine):
    post = create_post(api)
    comment = create_comment(api, post)
    with Session(db_engine, expire_on_commit=False) as session:
        with pytest.raises(DomainError) as error:
            service.delete_post(session, Principal(*ids("other")), UUID(post["id"]))
        assert error.value.status == 403
        result = service.create_comment(
            session, Principal(*ids("other")), UUID(post["id"]), CommentWrite(content="재시도")
        )
        assert result.post_id == UUID(post["id"])
    assert api.get(f"/api/posts/{post['id']}").json()["comment_count"] == 2
    assert api.get(f"/api/posts/{post['id']}/comments").json()["items"][0]["id"] == comment["id"]
