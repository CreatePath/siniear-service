from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = get_settings()
    yield


app = FastAPI(
    title="Siniear Service",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.include_router(router)
