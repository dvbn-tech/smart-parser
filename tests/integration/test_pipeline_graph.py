"""Конвейер с источником Graph API на имитации graph.facebook.com."""

from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from core.db.models import Account, Brand, BrandAccount, Media, MetricSnapshot, ScrapeTask
from parser.pipeline import Runner
from parser.queue import tasks as q
from parser.sources.graph import GraphApiSource, shortcode_to_pk
from tests.graph_factories import TARGET_ID, discovery, gmedia, graph_error

pytestmark = pytest.mark.integration
SETTINGS = Settings(
    source="graph",
    meta_access_token="TEST_TOKEN",
    meta_ig_user_id="17841400000000001",
    meta_requests_per_hour=100_000,
    meta_media_page_size=2,
)


class Sink:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, body: bytes) -> None:
        self.objects[key] = body


def recent(days: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+0000")


PAGES = {
    None: discovery(
        gmedia("Cnew0000001", recent(1), views=90_000), gmedia("Cnew0000002", recent(3)), after="P2"
    ),
    "P2": discovery(
        gmedia("Cold0000003", recent(40)), gmedia("Cold0000004", recent(90)), after="P3"
    ),
    "P3": discovery(gmedia("Cold0000005", recent(200))),
}


def graph(override: Any = None):  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["access_token"] == "TEST_TOKEN"
        fields = request.url.params["fields"]
        calls.append(fields)
        if override:
            return override(request)
        cursor = fields.split("media.after(")[1].split(")")[0] if "media.after(" in fields else None
        return httpx.Response(200, json=PAGES[cursor])

    return httpx.MockTransport(handler), calls


async def task_for(session: AsyncSession, t: q.TaskType, **kw: Any) -> ScrapeTask:
    await q.enqueue(session, t, window="t", **kw)
    await session.commit()
    task = await q.claim(session)
    await session.commit()
    assert task is not None
    return task


async def run(session: AsyncSession, task: ScrapeTask, transport: httpx.MockTransport) -> str:
    async with GraphApiSource(SETTINGS, transport=transport) as src:
        return await Runner(session, src, Sink(), SETTINGS).run(task)


async def count(session: AsyncSession, model: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_profile_stores_account_media_and_views(session: AsyncSession) -> None:
    session.add(Brand(id=1, name="WAISTLINE", hashtags=[], username_masks=[], domains=[]))
    await session.commit()
    task = await task_for(
        session,
        q.TaskType.PROFILE,
        username="yaroslava_line",
        payload={"link": {"brand_id": 1, "role": "creator", "curator": "Оля"}},
    )
    transport, calls = graph()
    assert await run(session, task, transport) == "succeeded"
    assert len(calls) == 1  # профиль и публикации — одним запросом

    acc = await session.get(Account, TARGET_ID)
    assert acc is not None and acc.username == "yaroslava_line" and acc.external_url
    snap = await session.get(MetricSnapshot, (shortcode_to_pk("Cnew0000001"), _today()))
    assert (
        snap is not None
        and snap.play_count == 90_000
        and snap.like_count == 1200
        and snap.source == "graph"
    )
    link = await session.get(BrandAccount, (1, TARGET_ID))
    assert link is not None and link.status == "tracked" and link.curator == "Оля"


def _today():  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from parser.pipeline import snapshot_day

    return snapshot_day(datetime.now(UTC))


async def seed(session: AsyncSession) -> None:
    session.add(
        Account(
            user_pk=TARGET_ID,
            username="yaroslava_line",
            is_private=False,
            is_verified=False,
            is_business=True,
        )
    )
    await session.commit()


async def test_backfill_pages_by_username_and_cursor(session: AsyncSession) -> None:
    await seed(session)
    task = await task_for(session, q.TaskType.BACKFILL, user_pk=TARGET_ID)
    transport, calls = graph()
    assert await run(session, task, transport) == "succeeded"
    assert len(calls) == 3 and all(
        "business_discovery.username(yaroslava_line)" in c for c in calls
    )
    assert await count(session, Media) == 5


async def test_feed_head_stops_after_30_days(session: AsyncSession) -> None:
    await seed(session)
    task = await task_for(session, q.TaskType.FEED_HEAD, user_pk=TARGET_ID)
    transport, calls = graph()
    assert await run(session, task, transport) == "succeeded"
    assert len(calls) == 2  # на второй странице последний ролик старше 30 дней


async def test_personal_account_fails_with_reason(session: AsyncSession) -> None:
    task = await task_for(session, q.TaskType.PROFILE, username="private_person")
    transport, _ = graph(
        lambda r: httpx.Response(400, json=graph_error(100, "Invalid user id", 2207013))
    )
    assert await run(session, task, transport) == "failed"
    t = await session.get(ScrapeTask, task.id, populate_existing=True)
    assert t is not None and "личный" in (t.last_error or "")


async def test_expired_token_stops_with_auth_error(session: AsyncSession) -> None:
    task = await task_for(session, q.TaskType.PROFILE, username="yaroslava_line")
    transport, _ = graph(
        lambda r: httpx.Response(400, json=graph_error(190, "Session has expired"))
    )
    assert await run(session, task, transport) == "auth_error"
    t = await session.get(ScrapeTask, task.id, populate_existing=True)
    assert t is not None and t.status == "deferred" and t.attempts == 0


async def test_rate_limit_defers(session: AsyncSession) -> None:
    task = await task_for(session, q.TaskType.PROFILE, username="yaroslava_line")
    transport, _ = graph(
        lambda r: httpx.Response(400, json=graph_error(4, "Application request limit reached"))
    )
    assert await run(session, task, transport) == "deferred"


async def test_token_not_saved_in_raw_url(session: AsyncSession) -> None:
    transport, _ = graph()
    async with GraphApiSource(SETTINGS, transport=transport) as src:
        page = await src.fetch_profile("yaroslava_line")
    assert "TEST_TOKEN" not in page.url
