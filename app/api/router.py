from fastapi import APIRouter

from app.api.health import router as health_router
from app.modules.calls.internal_router import router as internal_calls_router
from app.modules.calls.router import router as calls_router
from app.modules.community.router import router as community_router
from app.modules.groups.router import router as groups_router
from app.modules.meetings.internal_router import router as phone_router
from app.modules.meetings.query_router import router as meeting_queries_router
from app.modules.meetings.router import router as meetings_router

router = APIRouter(prefix="/api")
router.include_router(health_router)
router.include_router(groups_router)
router.include_router(meetings_router)
router.include_router(meeting_queries_router)
router.include_router(community_router)


router.include_router(calls_router)


router.include_router(internal_calls_router)

router.include_router(phone_router)
