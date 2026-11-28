from fastapi import APIRouter

from app.api.health import router as health_router
from app.modules.auth.push import router as push_router
from app.modules.auth.router import router as auth_router
from app.modules.cards.exchanges import router as exchanges_router
from app.modules.cards.router import router as cards_router
from app.modules.community.encouragement_router import router as encouragement_router
from app.modules.community.router import router as community_router
from app.modules.groups.memberships import router as memberships_router
from app.modules.groups.router import router as groups_router
from app.modules.interviews.router import router as interviews_router
from app.modules.meetings.query_router import router as meeting_queries_router
from app.modules.meetings.router import router as meetings_router
from app.modules.search.router import router as search_router
from app.modules.seniors.photos import router as photos_router
from app.modules.seniors.router import router as seniors_router

router = APIRouter(prefix="/api")
router.include_router(health_router)
router.include_router(search_router)
router.include_router(auth_router)
router.include_router(push_router)
router.include_router(seniors_router)
router.include_router(photos_router)
router.include_router(interviews_router)
router.include_router(cards_router)
router.include_router(exchanges_router)
router.include_router(groups_router)
router.include_router(memberships_router)
router.include_router(meetings_router)
router.include_router(meeting_queries_router)
router.include_router(community_router)
router.include_router(encouragement_router)
