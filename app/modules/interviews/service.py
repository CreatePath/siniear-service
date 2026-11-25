from sqlalchemy import select

from app.core.errors import DomainError
from app.core.idempotency import remember, replay
from app.db.models.identity import Senior
from app.db.models.interview import Interview, InterviewTurn
from app.integrations import interview_model
from app.modules.interviews.schemas import InterviewView

QUESTIONS = {
    "experience": "은퇴 전에는 어떤 일을 하셨나요?",
    "strengths": "지금 자신 있거나 잘하는 일은 무엇인가요?",
    "interests": "요즘 관심이 가는 일은 무엇인가요?",
    "can_share": "다른 사람에게 나누거나 가르쳐 주고 싶은 것은 무엇인가요?",
    "want_to_learn": "새롭게 배우고 싶은 것은 무엇인가요?",
    "activity_goals": "어떤 모임에서 무엇을 함께하고 싶으세요?",
}


def main_question(key):
    return {"key": key, "kind": "main", "text": QUESTIONS[key]}


def next_question(turns):
    current = turns[-1]["question"]
    topic = current["key"].partition(".")[0]
    topic_questions = [
        t["question"] for t in turns if t["question"]["key"].partition(".")[0] == topic
    ]
    asked = sum(q["kind"] == "follow_up" for q in topic_questions)
    if turns[-1]["answer"] is not None and asked < 2:
        follow = interview_model.follow_up(turns, QUESTIONS[topic], remaining=2 - asked)
        if (
            follow
            and follow not in QUESTIONS.values()
            and all(q["text"] != follow for q in topic_questions)
        ):
            suffix = ".detail" if asked == 0 else ".detail2"
            return {"key": topic + suffix, "kind": "follow_up", "text": follow}

    topics = list(QUESTIONS)
    index = topics.index(topic) + 1
    return main_question(topics[index]) if index < len(topics) else None


def owned(session, senior_id, interview_id, *, lock=False):
    query = select(Interview).where(Interview.id == interview_id, Interview.senior_id == senior_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(query)
    if row is None:
        raise DomainError(404, "INTERVIEW_NOT_FOUND", "인터뷰를 찾을 수 없습니다.")
    return row


def changed():
    return DomainError(409, "INTERVIEW_CHANGED", "최신 인터뷰 상태를 확인해 주세요.")


def start(session, actor, key):
    args = ("C", str(actor.senior_id), "interview.start", key, {})
    with session.begin():
        record = replay(session, *args)
        if record:
            row = owned(session, actor.senior_id, record.resource_id)
        else:
            row = Interview(
                senior_id=actor.senior_id,
                next_question=main_question(next(iter(QUESTIONS))),
                profile_version=session.get(Senior, actor.senior_id).version,
            )
            session.add(row)
            session.flush()
            remember(session, *args, 201, {}, resource_id=row.id)
        return InterviewView.model_validate(row)


def validate_answer(row, data):
    if (
        row.status != "active"
        or row.version != data.version
        or row.next_question["key"] != data.question_key
    ):
        raise changed()


def answer(session, actor, interview_id, data, key):
    payload = {"interview_id": interview_id, **data.model_dump()}
    args = ("C", str(actor.senior_id), "interview.answer", key, payload)
    with session.begin():
        replayed = replay(session, *args)
        row = owned(session, actor.senior_id, interview_id, lock=True)
        if replayed:
            return InterviewView.model_validate(row)
        validate_answer(row, data)
        turns = [
            {"question": t.question, "answer": t.answer}
            for t in session.scalars(
                select(InterviewTurn)
                .where(InterviewTurn.interview_id == row.id)
                .order_by(InterviewTurn.seq)
            )
        ]
        current = row.next_question
        turns.append({"question": current, "answer": data.answer})

    following = next_question(turns)
    draft = interview_model.summarize(turns) if following is None else None

    with session.begin():
        replayed = replay(session, *args)
        row = owned(session, actor.senior_id, interview_id, lock=True)
        if replayed:
            return InterviewView.model_validate(row)
        validate_answer(row, data)
        session.add(
            InterviewTurn(
                interview_id=row.id,
                seq=row.version,
                question=current,
                answer=data.answer,
                skipped=data.skip,
            )
        )
        row.next_question = following
        row.version += 1
        if following is None:
            row.status, row.draft = "ready", draft
        remember(session, *args, 200, {}, resource_id=row.id)
        return InterviewView.model_validate(row)
