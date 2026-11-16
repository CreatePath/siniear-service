from alembic import context
from sqlalchemy import create_engine, pool

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import database_url

config = context.config


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    migrate(config.attributes["connection"])
else:
    engine = create_engine(database_url(), poolclass=pool.NullPool, hide_parameters=True)
    with engine.connect() as connection:
        migrate(connection)
