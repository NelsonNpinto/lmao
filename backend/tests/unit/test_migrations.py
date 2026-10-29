"""The Alembic migration must produce exactly the schema the models describe."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection

from app.config import Settings
from app.db.migrate import upgrade_to_head
from app.db.models import Base
from app.db.session import make_engine


async def test_migration_matches_models(settings: Settings) -> None:
    engine = make_engine(settings.database_url)
    await upgrade_to_head(engine)

    def diff(conn: Connection) -> list[object]:
        ctx = MigrationContext.configure(conn, opts={"compare_type": False})
        return list(compare_metadata(ctx, Base.metadata))

    async with engine.connect() as conn:
        assert await conn.run_sync(diff) == []
    await engine.dispose()
