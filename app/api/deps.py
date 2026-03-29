from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infra.db.session import async_session_factory

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: Annotated[str | None, Security(api_key_header)],
) -> str | None:
    if api_key is None or not secrets.compare_digest(api_key, settings.api_key.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key


async def get_session() -> AsyncSession: # type: ignore
    async with async_session_factory() as session:
        yield session # type: ignore


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ApiKeyDep = Annotated[None, Depends(verify_api_key)]
