from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.interview import InterviewTurn
from app.integrations import interview_model
from tests.integration.conftest import auth


def start(api, key="begin"):
    response = api.post("/api/interviews", headers={"Idempotency-Key": key})
    assert response.status_code == 201, response.text
    return response.json()


def answer(api, row, key, **body):
    return api.post(
        f"/api/interviews/{row['id']}/answers",
        headers={"Idempotency-Key": key},
        json={"version": row["version"], "question_key": row["next_question"]["key"], **body},
    )


def ready(api, key="begin"):
    row = start(api, key)
    while row["next_question"]:
        res = answer(api, row, f"{key}-{row['version']}", answer="가상의 목공 활동")
        assert res.status_code == 200, res.text
        row = res.json()
    return row


def test_private_interview_follow_up_skip_and_retry(api, monkeypatch):
    row = start(api)
    assert start(api) == row
    path = "/api/interviews/" + row["id"]
    assert api.get(path, headers=auth("other")).status_code == 404
    assert (
        api.post(
            path + "/answers",
            headers={**auth("other"), "Idempotency-Key": "other"},
            json={"version": 1, "question_key": "experience", "answer": "합성"},
        ).status_code
        == 404
    )
    assert answer(api, row, "blank", answer="  ").status_code == 422
    assert answer(api, row, "both", answer="답", skip=True).status_code == 422
    with monkeypatch.context() as patch:

        def fail(*_, **kwargs):
            raise interview_model.unavailable()

        patch.setattr(interview_model, "follow_up", fail)
        assert answer(api, row, "first", answer="목공").status_code == 503
    assert api.get(path).json() == row
    follow = answer(api, row, "first", answer="목공").json()
    assert follow["next_question"]["kind"] == "follow_up"
    assert follow == answer(api, row, "first", answer="목공").json()
    assert answer(api, row, "first", skip=True).status_code == 409
    assert answer(api, row, "stale", skip=True).status_code == 409
    following = answer(api, follow, "skip", skip=True).json()
    assert following["next_question"]["key"] == "strengths"
    assert following["draft"] is None


def test_withdraw_while_model_is_processing(api, monkeypatch, db_engine):
    row = start(api)

    def withdraw(*_, **kwargs):
        assert api.delete("/api/users/me").status_code == 204
        return None

    monkeypatch.setattr(interview_model, "follow_up", withdraw)
    assert answer(api, row, "late", answer="가상의 활동").status_code == 404
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(InterviewTurn)) == 0


def test_two_answers_to_same_question(api, db_engine, monkeypatch):
    row = start(api)
    barrier = Barrier(2)

    def analyze(*_, **kwargs):
        barrier.wait(timeout=4)
        return None

    monkeypatch.setattr(interview_model, "follow_up", analyze)
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda key: answer(api, row, key, answer="가상의 취미 활동"), ["a", "b"])
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(InterviewTurn)) == 1


def test_all_six_topics_allow_at_most_two_follow_ups(api):
    row = start(api)
    topics = [
        "experience",
        "strengths",
        "interests",
        "can_share",
        "want_to_learn",
        "activity_goals",
    ]
    for topic in topics:
        assert row["next_question"]["key"] == topic
        for suffix in (".detail", ".detail2"):
            row = answer(api, row, str(row["version"]), answer="목공").json()
            assert row["next_question"]["kind"] == "follow_up"
            assert row["next_question"]["key"] == topic + suffix
        row = answer(api, row, str(row["version"]), answer="목공").json()
    assert row["status"] == "ready" and row["next_question"] is None


def test_fixed_main_questions_do_not_need_model_on_start_or_skip(api, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("시작 및 건너뛰기는 모델을 호출하지 않습니다.")

    monkeypatch.setattr(interview_model, "follow_up", unexpected)
    row = start(api)
    assert row["next_question"]["text"] == "은퇴 전에는 어떤 일을 하셨나요?"
    assert start(api) == row
    row = answer(api, row, "skip", skip=True).json()
    assert row["next_question"]["text"] == "지금 자신 있거나 잘하는 일은 무엇인가요?"


def test_repeated_or_main_question_from_model_advances_to_fixed_topic(api, monkeypatch):
    replies = iter(
        [
            "어떤 공구를 사용하셨나요?",
            "어떤 공구를 사용하셨나요?",
            "새롭게 배우고 싶은 것은 무엇인가요?",
        ]
    )
    monkeypatch.setattr(interview_model, "follow_up", lambda *args, **kwargs: next(replies))
    row = start(api)
    row = answer(api, row, "one", answer="공구를 수리했어요.").json()
    assert row["next_question"]["text"] == "어떤 공구를 사용하셨나요?"
    row = answer(api, row, "two", answer="망치요.").json()
    assert row["next_question"]["text"] == "지금 자신 있거나 잘하는 일은 무엇인가요?"
    row = answer(api, row, "three", answer="도색도 해요.").json()
    assert row["next_question"]["text"] == "요즘 관심이 가는 일은 무엇인가요?"
