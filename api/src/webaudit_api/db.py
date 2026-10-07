"""Database engine and session factory (async SQLAlchemy; SQLite for dev, PostgreSQL in production)."""

from __future__ import annotations

from sqlalchemy import bindparam, event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> AsyncEngine:
    is_sqlite = database_url.startswith("sqlite")
    engine = create_async_engine(
        database_url,
        connect_args={"timeout": 30} if is_sqlite else {},
        pool_pre_ping=not is_sqlite,
    )
    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")  # API and worker write concurrently
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# Keys of services the app no longer offers; their rows are deleted on start so no key is kept
# for something the user cannot see or use any more (Mapy.com map tiles were dropped in 0.5.2).
RETIRED_KEY_SERVICES = ("mapy",)


async def create_schema(engine: AsyncEngine) -> None:
    """Create missing tables and add missing columns. (Alembic migrations arrive before the first production deploy.)"""
    from . import models  # noqa: F401  (register tables)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
        await conn.run_sync(_drop_retired_keys)


def _add_missing_columns(conn: Connection) -> None:
    """Bring an older database up to date: a column added to a model is added to its table.

    The desktop app keeps its database across updates, and ``create_all`` only creates
    missing tables. Only additive, nullable columns are supported this way.
    """
    inspector = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            if not column.nullable:
                raise RuntimeError(f"{table.name}.{column.name} is new and NOT NULL; add it with a real migration")
            preparer = conn.dialect.identifier_preparer
            conn.execute(
                text(
                    f"ALTER TABLE {preparer.quote(table.name)} ADD COLUMN {preparer.quote(column.name)} "
                    f"{column.type.compile(dialect=conn.dialect)}"
                )
            )


def _drop_retired_keys(conn: Connection) -> None:
    if not inspect(conn).has_table("api_keys"):
        return
    conn.execute(
        text("DELETE FROM api_keys WHERE service IN :services").bindparams(bindparam("services", expanding=True)),
        {"services": list(RETIRED_KEY_SERVICES)},
    )
