from alembic import command
from alembic.config import Config
from sqlalchemy import text

from scripts.seed_dev import ids


def test_upgrade_preserves_existing_senior_and_old_writer(db_engine):
    with db_engine.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.downgrade(config, "d824e81c48c2")
        legacy = text("SELECT id, user_id, name, phone_number, interests FROM seniors ORDER BY id")
        before = connection.execute(legacy).all()
        assert before
        command.upgrade(config, "head")
        assert connection.execute(legacy).all() == before
        version, avatar, goals = connection.execute(
            text("SELECT version, avatar_key, activity_goals FROM seniors WHERE id=:id"),
            {"id": ids("owner")[1]},
        ).one()
        assert (version, avatar, goals) == (1, "default", [])
        assert connection.scalar(text("SELECT count(*) FROM cards")) == 0
