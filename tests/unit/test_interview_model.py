import json
from io import BytesIO

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import DomainError
from app.integrations import interview_model
from app.modules.interviews.schemas import Draft
from app.modules.interviews.service import QUESTIONS


def test_gemini_accepts_only_question_and_draft_fields(monkeypatch):
    monkeypatch.setenv("INTERVIEW_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_INTERVIEW_MODEL", "test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture")
    get_settings.cache_clear()
    outputs = iter(
        [
            '{"follow_up":"어떤 작업을 하셨어요?"}',
            '{"intro":"합성 소개"}',
            '{"owner_id":"invalid"}',
            "invalid",
        ]
    )
    turns = [
        {
            "question": {"key": "experience", "text": "합성 질문", "kind": "main"},
            "answer": "합성 답변",
        }
    ]

    def respond(request, timeout):
        assert request.full_url.endswith("/models/test-model:generateContent")
        payload = json.loads(request.data)
        assert json.loads(payload["contents"][0]["parts"][0]["text"]) == turns
        if "follow_up" in payload["generationConfig"]["responseJsonSchema"]["properties"]:
            prompt = payload["systemInstruction"]["parts"][0]["text"]
            assert QUESTIONS["experience"] in prompt
            assert "최대 두 번" in prompt and "남은 기회는 2회" in prompt
        result = {
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": next(outputs)}]}}
            ]
        }
        return BytesIO(json.dumps(result).encode())

    monkeypatch.setattr(interview_model, "urlopen", respond)
    try:
        follow = interview_model.follow_up(turns, QUESTIONS["experience"], remaining=2)
        assert follow == "어떤 작업을 하셨어요?"
        assert interview_model.summarize(turns) == {"intro": "합성 소개"}
        for _ in range(2):
            with pytest.raises(DomainError, match="인터뷰 분석") as error:
                interview_model.summarize(turns)
            assert error.value.status == 503
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "fields",
    [
        {"experience": "가" * 25},
        {"want_to_learn": ["가" * 25]},
        {"interests": ["가", "나", "다", "라"]},
        {"intro": "가" * 49},
        {"intro": "위 문장\n아래 문장"},
    ],
)
def test_new_draft_limits_do_not_break_stored_drafts(fields):
    Draft.model_validate(fields)
    with pytest.raises(ValidationError):
        interview_model.GeneratedDraft.model_validate(fields)


def test_long_demo_answers_fit_and_have_an_excerpt_marker(monkeypatch):
    monkeypatch.setenv("INTERVIEW_PROVIDER", "fake")
    get_settings.cache_clear()
    try:
        turn = {"question": {"key": "want_to_learn"}, "answer": "긴 합성 답변 " * 12}
        result = interview_model.summarize([turn, turn])
        assert len(result["want_to_learn"]) == 1
        assert result["want_to_learn"][0].endswith("…") and len(result["want_to_learn"][0]) <= 24
        assert result["intro"].endswith("…") and len(result["intro"]) <= 48
    finally:
        get_settings.cache_clear()
