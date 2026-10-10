"""Интеграционные тесты идут на отдельной базе <db>_test, чтобы не трогать рабочие данные."""

import os
import subprocess
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import get_settings

TABLES = (
    "metric_snapshot, metric_quarantine, media_signal, media_brand, media_stats, media, "
    "account_snapshot, account_username_history, brand_account, brand, account, "
    "scrape_task, raw_response, shape_fingerprint"
)


def _test_url() -> str:
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    import asyncio

    url = _test_url()
    admin = make_url(url).set(database="postgres").render_as_string(hide_password=False)
    name = make_url(url).database

    async def ensure() -> bool:
        engine = create_async_engine(admin, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                exists = await conn.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
                )
                if not exists:
                    await conn.execute(text(f'CREATE DATABASE "{name}"'))
            return True
        except OSError:
            return False
        finally:
            await engine.dispose()

    if not asyncio.run(ensure()):
        pytest.skip("postgres is not running (make up)")
    subprocess.run(
        ["alembic", "-c", "infra/alembic.ini", "upgrade", "head"],
        check=True,
        env={**os.environ, "SP_DATABASE_URL": url},
        capture_output=True,
    )
    yield url


@pytest.fixture
async def session(test_database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(test_database_url)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()
