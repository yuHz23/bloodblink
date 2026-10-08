"""BB-Core — Async database session management."""

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings

database_url = make_url(settings.database_url)
if database_url.drivername in {"postgres", "postgresql"}:
    database_url = database_url.set(drivername="postgresql+asyncpg")

database_query = dict(database_url.query)
ssl_mode = database_query.pop("sslmode", None)
ssl_option = database_query.pop("ssl", None)
ssl_mode = ssl_mode or ssl_option
database_url = database_url.set(query=database_query)

connect_args = {"server_settings": {"search_path": "public,extensions"}}
if settings.database_ssl or ssl_mode:
    # asyncpg uses `ssl`, not libpq's `sslmode` URL option.
    connect_args["ssl"] = "require" if settings.database_ssl else ssl_mode

engine = create_async_engine(
    database_url,
    echo=False,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    connect_args=connect_args,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """Dependency: yield an async database session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
