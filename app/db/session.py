from functools import lru_cache

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings


def database_url():
    s = get_settings()
    return URL.create(
        "postgresql+psycopg",
        username=s.db_user,
        password=s.db_password.get_secret_value(),
        host=s.db_host,
        port=s.db_port,
        database=s.db_name,
    )


@lru_cache
def get_engine():
    return create_engine(database_url(), pool_pre_ping=True, hide_parameters=True)


def get_session():
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session
