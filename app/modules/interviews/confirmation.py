from sqlalchemy import select

from app.core.errors import DomainError
from app.core.idempotency import remember, replay
from app.db.models.identity import Senior
from app.db.models.interview import Card
from app.modules.cards.schemas import Confirmed
from app.modules.cards.service import changed as card_changed
from app.modules.cards.service import project_card, render_card
from app.modules.interviews.service import changed, owned
from app.modules.seniors.profile import Profile, check_name, check_photo, edit_profile


def check_versions(row, senior, card, data):
    if row.status != "ready" or row.version != data.version:
        raise changed()
    if row.profile_version != data.profile_version or senior.version != data.profile_version:
        raise DomainError(409, "PROFILE_CHANGED", "인터뷰 시작 후 프로필이 변경되었습니다.")
    if data.card_version != (card.version if card else None):
        raise card_changed()


def preview(session, actor, interview_id, data):
    with session.begin():
        row = owned(session, actor.senior_id, interview_id)
        senior = session.get(Senior, actor.senior_id)
        card = session.scalar(
            select(Card).where(Card.senior_id == senior.id, Card.membership_id.is_(None))
        )
        check_versions(row, senior, card, data)
        edits = data.profile.model_dump(exclude_unset=True)
        check_photo(session, senior.user_id, edits.get("photo_id"))
        proposed = Profile.model_validate(senior).model_copy(update=edits)
        check_name(proposed.card_name_mode, proposed.name)
        settings = (
            data
            if not card or "color_code" in data.model_fields_set
            else data.model_copy(update={"color_code": card.color_code})
        )
        return project_card(settings, proposed)


def confirm(session, actor, interview_id, data, key):
    payload = {"interview_id": interview_id, **data.model_dump(exclude_unset=True)}
    args = ("C", str(actor.senior_id), "interview.confirm", key, payload)
    with session.begin():
        record = replay(session, *args)
        row = owned(session, actor.senior_id, interview_id, lock=True)
        senior = session.get(Senior, actor.senior_id, with_for_update=True)
        card = session.scalar(
            select(Card)
            .where(Card.senior_id == senior.id, Card.membership_id.is_(None))
            .with_for_update()
        )
        if not record:
            check_versions(row, senior, card, data)
            edit_profile(session, senior, data.profile, data.profile_version)
            if card is None:
                card = Card(senior_id=senior.id)
                session.add(card)
            else:
                card.version += 1
            if card.version is None or "color_code" in data.model_fields_set:
                card.color_code = data.color_code
            card.template_key = data.template_key
            card.visible_fields = data.visible_fields
            row.status, row.draft = "confirmed", None
            row.version += 1
            session.flush()
            remember(session, *args, 200, {}, resource_id=card.id)
        if card is None or (record and record.resource_id != card.id):
            raise card_changed()
        return Confirmed(
            interview_id=row.id,
            profile=Profile.model_validate(senior),
            card=render_card(session, card, owner=True),
        )
