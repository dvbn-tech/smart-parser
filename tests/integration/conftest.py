from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import get_settings

TABLES = (
    "metric_snapshot, metric_quarantine, media_signal, media_brand, media_stats, media, "
    "account_snapshot, account_username_history, brand_account, brand, account, "
    "scrape_task, raw_response, shape_fingerprint"
)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
    except OSError:
        await engine.dispose()
        pytest.skip("postgres is not running (make up && make migrate)")
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()
