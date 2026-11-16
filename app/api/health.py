import psycopg
from fastapi import APIRouter, HTTPException, Request

from app.db.health import check_database

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "siniear-service"}


@router.get("/ready")
async def readiness(request: Request) -> dict[str, str]:
    try:
        await check_database(request.app.state.settings)
    except (psycopg.Error, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "service": "siniear-service", "database": "ok"}
