from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Comment, Post, Senior
from scripts.seed_dev import ids
from tests.integration.conftest import auth
from tests.integration.test_groups_meetings import create_group


def create_post(api, group=None, author="member", **changes):
    group = group or create_group(api)
    response = api.post(
        f"/api/groups/{group['id']}/posts",
        json={"title": "가상 산책 후기", "content": "함께 걸어서 즐거웠습니다.", **changes},
        headers=auth(author),
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_comment(api, post, author="other", **changes):
    response = api.post(
        f"/api/posts/{post['id']}/comments",
        json={"content": "다음에도 함께해요.", **changes},
        headers=auth(author),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_crud_current_names_counts_and_response_fields(api, db_engine):
    post = create_post(api, title="  가상 후기  ")
    assert post["author_id"] == str(ids("member")[1])
    assert post["title"] == "가상 후기"
    assert post["created_at"] == post["updated_at"]
    assert set(post) == {
        "id",
        "group_id",
        "author_id",
        "author_name",
        "title",
        "content",
        "comment_count",
        "created_at",
        "updated_at",
    }
    assert post["comment_count"] == 0
    path = f"/api/posts/{post['id']}"
    first = create_comment(api, post, content="  댓글  ")
    second = create_comment(api, post, author="unverified")
    assert first["content"] == "댓글"
    assert first["created_at"] == first["updated_at"]
    assert set(first) == {
        "id",
        "post_id",
        "meeting_id",
        "parent_comment_id",
        "reply_count",
        "author_id",
        "author_name",
        "content",
        "created_at",
        "updated_at",
    }
    updated = api.patch(path, json={"title": "수정 제목"}, headers=auth("member")).json()
    assert updated["title"] == "수정 제목"
    assert updated["content"] == post["content"]
    assert updated["created_at"] == post["created_at"]
    assert updated["updated_at"] > post["updated_at"]
    assert updated["comment_count"] == 2
    response = api.patch(
        f"/api/comments/{first['id']}", json={"content": "수정 댓글"}, headers=auth("other")
    )
    assert response.status_code == 200
    assert response.json()["updated_at"] > first["updated_at"]
    with Session(db_engine) as session, session.begin():
        session.get(Senior, ids("member")[1]).nickname = "가상 새 작성자"
        session.get(Senior, ids("other")[1]).nickname = "가상 새 댓글자"
    detail = api.get(path).json()
    assert detail["author_name"] == "가상 새 작성자"
    listing = api.get(f"/api/groups/{post['group_id']}/posts").json()["items"]
    assert listing == [detail]
    comments = api.get(path + "/comments").json()["items"]
    assert [c["id"] for c in comments] == [first["id"], second["id"]]
    assert comments[0]["author_name"] == "가상 새 댓글자"
    assert comments[0]["content"] == "수정 댓글"
    deleted = api.delete(f"/api/comments/{first['id']}", headers=auth("other"))
    assert deleted.status_code == 204 and deleted.content == b""
    assert api.get(path).json()["comment_count"] == 1
    assert api.delete(f"/api/comments/{first['id']}", headers=auth("other")).status_code == 404
    with Session(db_engine) as session:
        assert session.get(Comment, UUID(first["id"])) is None


def test_permissions_author_group_owner_and_unrelated_owner(api):
    post = create_post(api)
    comment = create_comment(api, post)
    # The default owner cannot edit another author's content, even in their group.
    for actor in ("owner", "other"):
        assert (
            api.patch(
                f"/api/posts/{post['id']}", json={"title": "변조"}, headers=auth(actor)
            ).status_code
            == 403
        )
    for actor in ("owner", "member"):
        assert (
            api.patch(
                f"/api/comments/{comment['id']}", json={"content": "변조"}, headers=auth(actor)
            ).status_code
            == 403
        )
    assert api.delete(f"/api/comments/{comment['id']}", headers=auth("member")).status_code == 403
    assert api.delete(f"/api/posts/{post['id']}", headers=auth("other")).status_code == 403
    other_group = api.post(
        "/api/groups", json={"name": "다른 그룹", "region_code": "11110"}, headers=auth("other")
    ).json()
    other_post = create_post(api, group=other_group)
    other_comment = create_comment(api, other_post)
    for path in (f"/api/posts/{other_post['id']}", f"/api/comments/{other_comment['id']}"):
        assert api.delete(path).status_code == 403
    assert api.delete(f"/api/comments/{comment['id']}").status_code == 204
    assert api.delete(f"/api/posts/{post['id']}").status_code == 204
    assert api.delete(f"/api/posts/{other_post['id']}", headers=auth("member")).status_code == 204


def test_deleted_parent_hides_and_blocks_every_child_operation(api, db_engine):
    post = create_post(api)
    comment = create_comment(api, post)
    path = f"/api/posts/{post['id']}"
    assert api.delete(path).status_code == 204
    assert api.get(f"/api/groups/{post['group_id']}/posts").json()["items"] == []
    requests = [
        ("GET", path, None),
        ("DELETE", path, None),
        ("PATCH", path, {"content": "복원 시도"}),
        ("GET", path + "/comments", None),
        ("POST", path + "/comments", {"content": "추가"}),
        ("PATCH", f"/api/comments/{comment['id']}", {"content": "수정"}),
        ("DELETE", f"/api/comments/{comment['id']}", None),
    ]
    for method, url, body in requests:
        response = api.request(method, url, json=body, headers=auth("other"))
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "POST_NOT_FOUND"
    with Session(db_engine) as session:
        assert session.get(Post, UUID(post["id"])).deleted_at is not None
        assert session.get(Comment, UUID(comment["id"])).content == comment["content"]


def test_authentication_on_all_routes(api):
    post = create_post(api)
    comment = create_comment(api, post)
    api.headers.pop("Authorization")
    headers = {}
    requests = [
        ("GET", f"/api/groups/{post['group_id']}/posts", None),
        ("POST", f"/api/groups/{post['group_id']}/posts", {"title": "제목", "content": "본문"}),
        ("GET", f"/api/posts/{post['id']}", None),
        ("PATCH", f"/api/posts/{post['id']}", {"title": "수정"}),
        ("DELETE", f"/api/posts/{post['id']}", None),
        ("GET", f"/api/posts/{post['id']}/comments", None),
        ("POST", f"/api/posts/{post['id']}/comments", {"content": "댓글"}),
        ("PATCH", f"/api/comments/{comment['id']}", {"content": "수정"}),
        ("DELETE", f"/api/comments/{comment['id']}", None),
    ]
    for method, url, body in requests:
        assert api.request(method, url, json=body, headers=headers).status_code == 401


def test_validation_and_unknown_resources(api):
    group = create_group(api)
    path = f"/api/groups/{group['id']}/posts"
    for changes in (
        {"title": " "},
        {"title": "가" * 101},
        {"content": "\n\t"},
        {"content": "가" * 5001},
        {"content": None},
        {"author_id": str(ids("owner")[1])},
        {"group_id": str(uuid4())},
        {"deleted_at": None},
    ):
        assert (
            api.post(path, json={"title": "제목", "content": "본문", **changes}).status_code == 422
        )
    post = create_post(api, group, title="가" * 100, content="나" * 5000)
    comment = create_comment(api, post, content="다" * 1000)
    for payload in (
        {},
        {"title": None},
        {"content": ""},
        {"title": "\n"},
        {"author_id": str(uuid4())},
    ):
        assert (
            api.patch(f"/api/posts/{post['id']}", json=payload, headers=auth("member")).status_code
            == 422
        )
    for payload in (
        {},
        {"content": None},
        {"content": "\t"},
        {"content": "가" * 1001},
        {"content": "댓글", "author_id": str(uuid4())},
    ):
        assert api.post(f"/api/posts/{post['id']}/comments", json=payload).status_code == 422
        assert (
            api.patch(
                f"/api/comments/{comment['id']}", json=payload, headers=auth("other")
            ).status_code
            == 422
        )
    missing = str(uuid4())
    for method, url, payload in (
        ("GET", f"/api/groups/{missing}/posts", None),
        ("POST", f"/api/groups/{missing}/posts", {"title": "제목", "content": "본문"}),
        ("GET", f"/api/posts/{missing}", None),
        ("PATCH", f"/api/posts/{missing}", {"title": "제목"}),
        ("DELETE", f"/api/posts/{missing}", None),
        ("GET", f"/api/posts/{missing}/comments", None),
        ("POST", f"/api/posts/{missing}/comments", {"content": "댓글"}),
        ("PATCH", f"/api/comments/{missing}", {"content": "댓글"}),
        ("DELETE", f"/api/comments/{missing}", None),
    ):
        assert api.request(method, url, json=payload).status_code == 404
    assert api.get("/api/posts/not-a-uuid").status_code == 422


def test_keyset_order_scope_and_deleted_cursor_anchor(api, db_engine):
    group = create_group(api)
    posts = [create_post(api, group) for _ in range(3)]
    comment_parent = min(posts, key=lambda post: post["id"])
    comments = [create_comment(api, comment_parent) for _ in range(3)]
    # Same timestamps must still produce deterministic, gap-free pages.
    with Session(db_engine) as session, session.begin():
        moment = datetime.now(UTC)
        for model in (Post, Comment):
            for row in session.scalars(select(model)):
                row.created_at = moment
    post_path = f"/api/groups/{group['id']}/posts"
    comment_path = f"/api/posts/{comment_parent['id']}/comments"
    for path, rows, descending in ((post_path, posts, True), (comment_path, comments, False)):
        expected = sorted([r["id"] for r in rows], reverse=descending)
        page = api.get(path, params={"limit": 1}).json()
        assert page["items"][0]["id"] == expected[0]
        cursor = page["next_cursor"]
        anchor = page["items"][0]["id"]
        if descending:
            assert api.delete(f"/api/posts/{anchor}").status_code == 204
        else:
            assert api.delete(f"/api/comments/{anchor}").status_code == 204
        remaining = api.get(path, params={"limit": 2, "cursor": cursor}).json()
        assert [r["id"] for r in remaining["items"]] == expected[1:]
        assert remaining["next_cursor"] is None
        wrong_path = (
            f"/api/groups/{create_group(api)['id']}/posts"
            if descending
            else f"/api/posts/{create_post(api)['id']}/comments"
        )
        invalid = api.get(wrong_path, params={"cursor": cursor})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "INVALID_CURSOR"
    for params in ({"limit": 0}, {"limit": 101}, {"cursor": "broken"}):
        assert api.get(post_path, params=params).status_code == 422


def test_closed_group_keeps_community_permissions(api):
    group = create_group(api)
    assert api.patch(f"/api/groups/{group['id']}", json={"status": "closed"}).status_code == 200
    post = create_post(api, group, author="unverified")
    comment = create_comment(api, post, author="unverified")
    assert api.get(f"/api/posts/{post['id']}", headers=auth("unverified")).status_code == 200
    assert api.delete(f"/api/comments/{comment['id']}").status_code == 204


def test_database_lengths_and_foreign_keys(api, db_engine):
    post = create_post(api)
    for row in (
        Post(group_id=UUID(post["group_id"]), author_id=ids("member")[1], title="", content="본문"),
        Post(group_id=uuid4(), author_id=ids("member")[1], title="제목", content="본문"),
        Comment(post_id=UUID(post["id"]), author_id=ids("other")[1], content="가" * 1001),
        Comment(post_id=uuid4(), author_id=ids("other")[1], content="댓글"),
        Comment(post_id=UUID(post["id"]), author_id=uuid4(), content="댓글"),
    ):
        with pytest.raises(IntegrityError), Session(db_engine) as session, session.begin():
            session.add(row)


def test_openapi_community_contract(api):
    schema = api.get("/api/openapi.json").json()
    paths = {
        "/api/groups/{group_id}/posts": {"get": "200", "post": "201"},
        "/api/posts/{post_id}": {"get": "200", "patch": "200", "delete": "204"},
        "/api/posts/{post_id}/comments": {"get": "200", "post": "201"},
        "/api/comments/{comment_id}": {"patch": "200", "delete": "204"},
    }
    for path, methods in paths.items():
        for method, success in methods.items():
            operation = schema["paths"][path][method]
            assert operation["security"]
            assert {success, "401", "403", "404", "422"} <= operation["responses"].keys()
            if success == "204":
                assert "content" not in operation["responses"][success]
