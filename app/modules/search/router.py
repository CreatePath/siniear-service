from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select

from app.api.dependencies import Actor, Cursor, Database, Limit
from app.core.errors import API_ERRORS
from app.core.pagination import paginate
from app.core.schemas import Page
from app.db.models import Group, Meeting, Senior
from app.modules.groups.repository import group_view
from app.modules.groups.schemas import GroupResponse
from app.modules.meetings.schemas import ActivityCategory, MeetingResponse
from app.modules.meetings.service import as_response, now
from app.modules.search.regions import DISTRICTS, resolve_search

router = APIRouter(prefix="/search", tags=["search"], responses=API_ERRORS)
Keyword = Annotated[str | None, Query(max_length=100, description="시군구명과 모임 검색어")]
CATEGORY_LABELS = {"walk": "산책", "hobby": "취미", "exercise": "운동"}


class SearchRegion(BaseModel):
    region_code: str
    name: str


class SearchPage[T](Page[T]):
    regions: list[SearchRegion]
    total_count: int


def search_page(session, actor, model, query, keyword, category, text_fields, limit, cursor):
    profile_code = session.scalar(select(Senior.region_code).where(Senior.id == actor.senior_id))
    codes, words = resolve_search(profile_code, keyword)
    # 시군구 5자리 외에 기존 읍면동 8·10자리 코드도 해당 시군구에 속한다.
    pattern = "^(" + "|".join(codes) + ")[0-9]{3}([0-9]{2})?$"
    query = query.where(or_(model.region_code.in_(codes), model.region_code.regexp_match(pattern)))
    for word in words:
        query = query.where(or_(*(field.icontains(word, autoescape=True) for field in text_fields)))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    groups = model is Group
    rows, next_cursor = paginate(
        session,
        query,
        column=Group.created_at if groups else Meeting.starts_at,
        id_column=model.id,
        limit=limit,
        cursor=cursor,
        descending=groups,
        scope={
            "resource": f"search/{model.__tablename__}",
            "actor": actor.senior_id,
            "regions": codes,
            "keyword": words,
            "category": category,
        },
    )
    return {
        "regions": [
            SearchRegion(region_code=code, name=DISTRICTS[code].full_name) for code in codes
        ],
        "total_count": total,
        "items": [
            group_view(session, row, actor.senior_id) if groups else as_response(session, row)
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.get("/groups", response_model=SearchPage[GroupResponse], summary="주변 동호회 검색")
def search_groups(
    actor: Actor,
    session: Database,
    keyword: Keyword = None,
    category: ActivityCategory | None = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    with session.begin():
        query = select(Group).where(Group.status == "active")
        if category:
            query = query.where(Group.interests.contains([CATEGORY_LABELS[category]]))
        fields = (Group.name, Group.description, func.array_to_string(Group.interests, " "))
        return search_page(session, actor, Group, query, keyword, category, fields, limit, cursor)


@router.get("/meetings", response_model=SearchPage[MeetingResponse], summary="주변 번개모임 검색")
def search_meetings(
    actor: Actor,
    session: Database,
    keyword: Keyword = None,
    category: ActivityCategory | None = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    with session.begin():
        query = select(Meeting).where(
            Meeting.group_id.is_(None),
            Meeting.status.in_(("recruiting", "closed")),
            Meeting.starts_at > now(),
        )
        if category:
            query = query.where(Meeting.category == category)
        fields = (
            Meeting.title,
            Meeting.description,
            Meeting.location,
            case(CATEGORY_LABELS, value=Meeting.category),
        )
        return search_page(session, actor, Meeting, query, keyword, category, fields, limit, cursor)
