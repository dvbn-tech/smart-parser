"""Конвейер целиком на имитации Instagram: задача → сырой ответ → разбор → проверка → база."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from core.db.models import (
    Account,
    AccountSnapshot,
    Brand,
    BrandAccount,
    Media,
    MediaSignal,
    MetricSnapshot,
    RawResponse,
    ScrapeTask,
    ShapeFingerprint,
)
from parser.pipeline import Runner
from parser.queue import tasks as q
from parser.sources.web import WebSource
from tests.factories import OWNER_PK, graphql_node, profile_response, reel_node, reels_page

pytestmark = pytest.mark.integration
SETTINGS = Settings(min_pause_between_requests_s=0, proxy_url=None)
NOW = datetime.now(UTC)


class MemorySink:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, body: bytes) -> None:
        self.objects[key] = body


def ts(days_ago: float) -> int:
    return int((NOW - timedelta(days=days_ago)).timestamp())


def reel(pk: int, days_ago: float, views: int, **kw: Any) -> dict[str, Any]:
    return reel_node(pk=str(pk), code=f"c{pk}", taken_at=ts(days_ago), play_count=views, **kw)


PAGES = {
    None: reels_page(
        reel(1, 2, 50_000, clips_tab_pinned_user_ids=[OWNER_PK]),
        reel(2, 3, 40_000, caption={"text": "арт. 847963328 #Waistline"}),
        cursor="p2",
    ),
    "p2": reels_page(reel(3, 20, 30_000), reel(4, 45, 20_000), cursor="p3"),
    "p3": reels_page(reel(5, 90, 10_000), reel(6, 200, 5_000)),
}


def instagram(overrides: dict[str, Callable[[httpx.Request], httpx.Response]] | None = None):  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        for prefix, fn in (overrides or {}).items():
            if path.startswith(prefix):
                return fn(request)
        if path == "/api/v1/users/web_profile_info/":
            return httpx.Response(
                200,
                json=profile_response(
                    highlight_reel_count=3,
                    edge_owner_to_timeline_media={
                        "count": 412,
                        "edges": [{"node": graphql_node()}],
                    },
                ),
            )
        if path == "/api/v1/clips/user/":
            cursor = dict(httpx.QueryParams(request.content.decode())).get("max_id")
            return httpx.Response(200, json=PAGES[cursor])
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


async def make_task(session: AsyncSession, task_type: q.TaskType, **kw: Any) -> ScrapeTask:
    task_id = await q.enqueue(session, task_type, window="t", **kw)
    await session.commit()
    task = await q.claim(session)
    await session.commit()
    assert task is not None and task.id == task_id
    return task


async def run(
    session: AsyncSession,
    task: ScrapeTask,
    transport: httpx.MockTransport,
    sink: MemorySink | None = None,
) -> str:
    async with WebSource(SETTINGS, transport=transport) as src:
        return await Runner(session, src, sink or MemorySink(), SETTINGS).run(task)


async def count(session: AsyncSession, model: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_profile_by_username_links_to_brand_and_queues_backfill(
    session: AsyncSession,
) -> None:
    session.add(Brand(id=1, name="WAISTLINE", hashtags=["waistline"], username_masks=[]))
    await session.commit()
    task = await make_task(
        session,
        q.TaskType.PROFILE,
        username="yaroslava_line",
        payload={"link": {"brand_id": 1, "role": "creator"}},
    )
    transport, _ = instagram()
    sink = MemorySink()
    assert await run(session, task, transport, sink) == "succeeded"

    acc = await session.get(Account, OWNER_PK, populate_existing=True)
    assert acc is not None and acc.highlight_reel_count == 3 and acc.business_category is None
    assert await count(session, AccountSnapshot) == 1
    # 12 постов из ответа профиля — метаданные без снимка просмотров
    timeline = await session.get(Media, 3471298811234999)
    assert timeline is not None and timeline.location_name == "Москва"
    assert await count(session, MetricSnapshot) == 0
    link = await session.get(BrandAccount, (1, OWNER_PK))
    assert link is not None and link.status == "tracked"
    backfill = await session.scalar(select(ScrapeTask).where(ScrapeTask.type == "backfill"))
    assert backfill is not None and backfill.user_pk == OWNER_PK
    raw = (await session.execute(select(RawResponse))).scalars().all()
    assert [(r.request_kind, r.parse_status) for r in raw] == [("profile", "ok")]
    assert raw[0].s3_key in sink.objects
    assert await count(session, ShapeFingerprint) == 1


async def seed_account(session: AsyncSession) -> None:
    session.add(
        Account(
            user_pk=OWNER_PK,
            username="yaroslava_line",
            is_private=False,
            is_verified=False,
            is_business=False,
        )
    )
    await session.commit()


async def test_backfill_collects_full_history(session: AsyncSession) -> None:
    await seed_account(session)
    task = await make_task(session, q.TaskType.BACKFILL, user_pk=OWNER_PK)
    transport, _ = instagram()
    assert await run(session, task, transport) == "succeeded"

    assert await count(session, Media) == 6
    assert await count(session, MetricSnapshot) == 6
    t = await session.get(ScrapeTask, task.id, populate_existing=True)
    assert t is not None and t.status == "succeeded" and t.pages_done == 3 and t.cursor is None
    acc = await session.get(Account, OWNER_PK, populate_existing=True)
    assert acc is not None and acc.backfill_done_at is not None
    signals = set(
        (
            await session.execute(
                select(MediaSignal.kind, MediaSignal.value).where(MediaSignal.media_pk == 2)
            )
        ).all()
    )
    assert ("wb_article", "847963328") in signals and ("hashtag", "waistline") in signals
    pinned = await session.get(Media, 1)
    assert pinned is not None and pinned.is_pinned


async def test_feed_head_stops_at_30_days_ignoring_pinned(session: AsyncSession) -> None:
    await seed_account(session)
    task = await make_task(session, q.TaskType.FEED_HEAD, user_pk=OWNER_PK)
    transport, calls = instagram()
    assert await run(session, task, transport) == "succeeded"
    # страница 2 содержит ролик старше 30 дней — третью не запрашиваем
    assert calls.count("/api/v1/clips/user/") == 2
    assert await count(session, Media) == 4


async def test_rerun_is_idempotent(session: AsyncSession) -> None:
    await seed_account(session)
    transport, _ = instagram()
    for _ in range(2):
        await run(
            session, await make_task(session, q.TaskType.BACKFILL, user_pk=OWNER_PK), transport
        )
        await session.execute(text("DELETE FROM scrape_task"))
        await session.commit()
    assert await count(session, Media) == 6
    assert await count(session, MetricSnapshot) == 6  # один снимок на ролик в сутки


async def test_crash_mid_backfill_resumes_from_cursor(session: AsyncSession) -> None:
    await seed_account(session)
    task = await make_task(session, q.TaskType.BACKFILL, user_pk=OWNER_PK)

    def broken_page_3(request: httpx.Request) -> httpx.Response:
        if dict(httpx.QueryParams(request.content.decode())).get("max_id") == "p3":
            raise httpx.ConnectTimeout("proxy timeout")
        return httpx.Response(
            200, json=PAGES[dict(httpx.QueryParams(request.content.decode())).get("max_id")]
        )

    transport, _ = instagram({"/api/v1/clips/user/": broken_page_3})
    assert await run(session, task, transport) == "retry"
    t = await session.get(ScrapeTask, task.id, populate_existing=True)
    assert t is not None and t.cursor == "p3" and t.pages_done == 2
    assert await count(session, Media) == 4

    await session.execute(text("UPDATE scrape_task SET run_after = now() - interval '1 second'"))
    await session.commit()
    again = await q.claim(session)
    await session.commit()
    assert again is not None and again.id == task.id
    transport, calls = instagram()
    assert await run(session, again, transport) == "succeeded"
    assert calls == ["/api/v1/clips/user/"]  # только недостающая страница
    assert await count(session, Media) == 6


async def test_format_change_writes_nothing_and_keeps_raw(session: AsyncSession) -> None:
    await seed_account(session)
    task = await make_task(session, q.TaskType.FEED_HEAD, user_pk=OWNER_PK)
    broken = reels_page(reel(1, 2, 50_000))
    del broken["items"][0]["media"]["play_count"]
    transport, _ = instagram({"/api/v1/clips/user/": lambda r: httpx.Response(200, json=broken)})
    assert await run(session, task, transport) == "failed"
    assert await count(session, Media) == 0
    raw = (await session.execute(select(RawResponse))).scalars().one()
    assert raw.parse_status == "invalid" and "play_count" in (raw.parse_error or "")
    t = await session.get(ScrapeTask, task.id, populate_existing=True)
    assert t is not None and t.status == "failed"


async def test_zero_views_on_old_reel_invalidates_page(session: AsyncSession) -> None:
    await seed_account(session)
    task = await make_task(session, q.TaskType.FEED_HEAD, user_pk=OWNER_PK)
    page = reels_page(reel(1, 2, 50_000), reel(2, 3, 0))
    transport, _ = instagram({"/api/v1/clips/user/": lambda r: httpx.Response(200, json=page)})
    assert await run(session, task, transport) == "failed"
    assert await count(session, Media) == 0  # первый ролик тоже не записан


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429),
        httpx.Response(302, headers={"location": "https://www.instagram.com/accounts/login/"}),
    ],
)
async def test_block_defers_without_spending_attempt(
    session: AsyncSession, response: httpx.Response
) -> None:
    await seed_account(session)
    task = await make_task(session, q.TaskType.FEED_HEAD, user_pk=OWNER_PK)
    transport, _ = instagram({"/api/v1/clips/user/": lambda r: response})
    assert await run(session, task, transport) == "deferred"
    t = await session.get(ScrapeTask, task.id, populate_existing=True)
    assert t is not None and t.status == "deferred" and t.attempts == 0
    raw = (await session.execute(select(RawResponse))).scalars().one()
    assert raw.parse_status == "blocked"


async def test_not_found_three_days_becomes_deleted(session: AsyncSession) -> None:
    await seed_account(session)
    await session.execute(text("UPDATE account SET not_found_since = now() - interval '4 days'"))
    await session.commit()
    task = await make_task(session, q.TaskType.PROFILE, user_pk=OWNER_PK)
    transport, _ = instagram({"/api/v1/users/web_profile_info/": lambda r: httpx.Response(404)})
    assert await run(session, task, transport) == "succeeded"
    acc = await session.get(Account, OWNER_PK, populate_existing=True)
    assert acc is not None and acc.status == "deleted"


async def test_collab_owner_gets_stub_account(session: AsyncSession) -> None:
    await seed_account(session)
    task = await make_task(session, q.TaskType.FEED_HEAD, user_pk=OWNER_PK)
    page = reels_page(
        reel(
            1,
            2,
            50_000,
            user={"pk": 777, "username": "Partner_Brand"},
            coauthor_producers=[{"pk": OWNER_PK}],
        )
    )
    transport, _ = instagram({"/api/v1/clips/user/": lambda r: httpx.Response(200, json=page)})
    assert await run(session, task, transport) == "succeeded"
    stub = await session.get(Account, 777)
    assert stub is not None and stub.username == "partner_brand"


async def test_brand_tagged_creates_candidates(session: AsyncSession) -> None:
    session.add(
        Account(
            user_pk=900,
            username="waistline_shop",
            is_private=False,
            is_verified=False,
            is_business=True,
        )
    )
    await session.flush()
    session.add(
        Brand(id=1, name="WAISTLINE", hashtags=["waistline"], username_masks=[], shop_user_pk=900)
    )
    await session.commit()
    task = await make_task(
        session, q.TaskType.BRAND_TAGGED, username="brand1", payload={"brand_id": 1}
    )
    tagged = {
        "items": [
            reel(
                10,
                1,
                9000,
                user={"pk": 555, "username": "fan_one"},
                usertags={"in": [{"user": {"pk": 900}}]},
            )
        ],
        "more_available": False,
    }
    transport, _ = instagram({"/api/v1/usertags/": lambda r: httpx.Response(200, json=tagged)})
    assert await run(session, task, transport) == "succeeded"
    link = await session.get(BrandAccount, (1, 555))
    assert link is not None and link.status == "candidate" and float(link.confidence or 0) == 0.25
    probe = await session.scalar(select(ScrapeTask).where(ScrapeTask.type == "candidate_probe"))
    assert probe is not None and probe.payload == {"brand_id": 1}
