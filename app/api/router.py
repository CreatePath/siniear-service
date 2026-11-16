from fastapi import APIRouter

from app.api.health import router as health_router
from app.modules.groups.router import router as groups_router
from app.modules.meetings.query_router import router as meeting_queries_router
from app.modules.meetings.router import router as meetings_router

router = APIRouter(prefix="/api")
router.include_router(health_router)
router.include_router(groups_router)
router.include_router(meetings_router)
router.include_router(meeting_queries_router)
