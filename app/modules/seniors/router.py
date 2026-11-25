from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.dependencies import Actor, Database
from app.core.errors import API_ERRORS, DomainError
from app.db.models.call import CareContact
from app.db.models.identity import Senior, User
from app.modules.auth.dependencies import Member
from app.modules.auth.service import unauthorized
from app.modules.meetings.service import require_owner
from app.modules.seniors.profile import (
    Profile,
    ProfileCreate,
    ProfilePatch,
    VersionHeader,
    check_photo,
    edit_profile,
)
from app.modules.seniors.schemas import (
    Contact,
    ContactCreate,
    ContactPatch,
    Contacts,
)

router = APIRouter(tags=["seniors"], responses=API_ERRORS)


def own_senior(senior_id: UUID, actor: Actor):
    require_owner(senior_id, actor)
    return senior_id


OwnerId = Annotated[UUID, Depends(own_senior)]


@router.post("/seniors", status_code=201)
def create_profile(data: ProfileCreate, account: Member, session: Database) -> Profile:
    with session.begin():
        user = session.scalar(select(User).where(User.id == account.user_id).with_for_update())
        if user is None or user.withdrawn_at:
            raise unauthorized()
        if session.scalar(select(Senior.id).where(Senior.user_id == user.id)):
            raise DomainError(409, "PROFILE_EXISTS", "이미 프로필이 등록되어 있습니다.")
        check_photo(session, user.id, data.photo_id)
        senior = Senior(user_id=user.id, **data.model_dump())
        session.add(senior)
        session.flush()
        return Profile.model_validate(senior)


@router.get("/seniors/{senior_id}")
def profile(senior_id: OwnerId, session: Database) -> Profile:
    with session.begin():
        return Profile.model_validate(session.get(Senior, senior_id))


@router.patch("/seniors/{senior_id}")
def update_profile(
    senior_id: OwnerId, data: ProfilePatch, if_match: VersionHeader, session: Database
) -> Profile:
    with session.begin():
        senior = session.get(Senior, senior_id, with_for_update=True)
        edit_profile(session, senior, data, int(if_match[1:-1]))
        session.flush()
        return Profile.model_validate(senior)


CONTACTS = "/seniors/{senior_id}/care-contacts"


@router.get(CONTACTS)
def contacts(senior_id: OwnerId, session: Database) -> Contacts:
    with session.begin():
        rows = session.scalars(
            select(CareContact)
            .where(CareContact.senior_id == senior_id, CareContact.deleted_at.is_(None))
            .order_by(CareContact.created_at, CareContact.id)
        )
        return Contacts(items=[Contact.model_validate(row) for row in rows])


@router.post(CONTACTS, status_code=201)
def create_contact(senior_id: OwnerId, data: ContactCreate, session: Database) -> Contact:
    with session.begin():
        row = CareContact(senior_id=senior_id, **data.model_dump())
        session.add(row)
        session.flush()
        return Contact.model_validate(row)


def lock_contact(session, senior_id, contact_id):
    row = session.scalar(
        select(CareContact)
        .where(
            CareContact.senior_id == senior_id,
            CareContact.id == contact_id,
            CareContact.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise DomainError(404, "CONTACT_NOT_FOUND", "연락처를 찾을 수 없습니다.")
    return row


@router.patch(CONTACTS + "/{contact_id}")
def update_contact(
    senior_id: OwnerId, contact_id: UUID, data: ContactPatch, session: Database
) -> Contact:
    with session.begin():
        row = lock_contact(session, senior_id, contact_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        return Contact.model_validate(row)


@router.delete(CONTACTS + "/{contact_id}", status_code=204)
def delete_contact(senior_id: OwnerId, contact_id: UUID, session: Database):
    with session.begin():
        row = lock_contact(session, senior_id, contact_id)
        row.enabled = False
        row.deleted_at = datetime.now(UTC)
    return Response(status_code=204)
