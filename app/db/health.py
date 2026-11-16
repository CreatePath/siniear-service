import asyncio

import psycopg

from app.core.config import Settings


async def check_database(settings: Settings) -> None:
    """Check the configured database without creating or changing tables."""
    async with asyncio.timeout(5):
        async with await psycopg.AsyncConnection.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password.get_secret_value(),
            connect_timeout=3,
            options="-c statement_timeout=2000",
            autocommit=True,
        ) as connection:
            await connection.execute("SELECT 1")
