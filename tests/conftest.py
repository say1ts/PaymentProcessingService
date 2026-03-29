import os
from collections.abc import AsyncGenerator

import pytest
from fastapi import Header, HTTPException, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ["DATABASE_URL"] = "postgresql+asyncpg://payments:payments_secret@localhost:5432/payments_test"

from app.api.deps import verify_api_key
from app.api.main import app
from app.infra.db.models import Base
from app.infra.db.session import get_session

_engine = None
_sessionmaker = None


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    global _engine, _sessionmaker
    admin_url = "postgresql+asyncpg://payments:payments_secret@localhost:5432/postgres"
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        res = await conn.execute(text("SELECT 1 FROM pg_database WHERE datname='payments_test'"))
        if not res.scalar():
            await conn.execute(text("CREATE DATABASE payments_test"))
    await admin_engine.dispose()

    _engine = create_async_engine(os.getenv("DATABASE_URL"))
    _sessionmaker = async_sessionmaker(bind=_engine, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield

    await _engine.dispose()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Чистая сессия для каждого теста с откатом."""
    async with _sessionmaker() as session:  # type: ignore
        yield session
        await session.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """Клиент, который прокидывает тестовую сессию и мокает API-ключ."""
    app.dependency_overrides[get_session] = lambda: db_session

    async def mock_verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
        if x_api_key != "dev_secret_key_change_in_production":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API Key",
            )
        return x_api_key

    app.dependency_overrides[verify_api_key] = mock_verify_api_key

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
