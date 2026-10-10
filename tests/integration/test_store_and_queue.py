import random
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import (
    Account,
    AccountUsernameHistory,
    MediaSignal,
    MetricQuarantine,
    MetricSnapshot,
    ScrapeTask,
)
from parser.parse.profile import parse_web_profile_info
from parser.parse.reels import parse_reels_page
from parser.queue import tasks as q
from parser.signals.extract import extract_signals
from parser.store import repo
from parser.validate.metrics import check_snapshot
from tests.factories import OWNER_PK, profile_response, reel_node, reels_page

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 10, 1, 0, tzinfo=UTC)


async def test_account_upsert_and_rename_history(session: AsyncSession) -> None:
    p = parse_web_profile_info(profile_response())
    assert await repo.upsert_account(session, p, NOW) is False
    await repo.upsert_account(session, p, NOW)  # повтор — без дублей
    renamed = parse_web_profile_info(profile_response(username="yaroslava_new"))
    assert await repo.upsert_account(session, renamed, NOW + timedelta(days=1)) is True
    await session.commit()

    acc = await session.get(Account, OWNER_PK)
    assert acc is not None and acc.username == "yaroslava_new"
    history = (
        (await session.execute(select(AccountUsernameHistory).order_by(AccountUsernameHistory.id)))
        .scalars()
        .all()
    )
    assert [(h.username, h.seen_to is not None) for h in history] == [
        ("yaroslava_line", True),
        ("yaroslava_new", False),
    ]


async def test_username_taken_over_by_other_account(session: AsyncSession) -> None:
    await repo.upsert_account(session, parse_web_profile_info(profile_response()), NOW)
    other = parse_web_profile_info(profile_response(id="777", username="yaroslava_line"))
    await repo.upsert_account(session, other, NOW)
    await session.commit()
    names = dict((await session.execute(select(Account.user_pk, Account.username))).all())
    assert names == {OWNER_PK: f"yaroslava_line#{OWNER_PK}", 777: "yaroslava_line"}


async def write_page(session: AsyncSession, views: int, day: date, raw_id: int) -> str:
    page = parse_reels_page(
        reels_page(reel_node(play_count=views)), captured_at=datetime.combine(day, NOW.timetz())
    )
    item = page.items[0]
    _, caption_changed = await repo.upsert_media(session, item.media, NOW)
    if caption_changed:
        await repo.replace_signals(session, item.media.media_pk, extract_signals(item.media))
    prev = await repo.previous_snapshot(session, item.media.media_pk, day)
    verdict = check_snapshot(item.metrics, taken_at=item.media.taken_at, is_reel=True, prev=prev)
    return await repo.write_metrics(
        session, item.metrics, verdict, snapshot_date=day, source="web", raw_response_id=raw_id
    )


async def test_media_snapshots_signals_and_quarantine(session: AsyncSession) -> None:
    await repo.upsert_account(session, parse_web_profile_info(profile_response()), NOW)
    d1, d2, d3 = date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 10)
    assert await write_page(session, 1_000_000, d1, 1) == "written"
    assert await write_page(session, 1_100_000, d1, 2) == "written"  # тот же день — перезапись
    assert await write_page(session, 1_080_000, d2, 3) == "written"  # падение ≤ 5% — флаг
    assert await write_page(session, 500_000, d3, 4) == "quarantined"
    await session.commit()

    snaps = (
        (await session.execute(select(MetricSnapshot).order_by(MetricSnapshot.snapshot_date)))
        .scalars()
        .all()
    )
    assert [(s.play_count, s.flags, s.raw_response_id) for s in snaps] == [
        (1_100_000, [], 2),
        (1_080_000, ["metric_drop"], 3),
    ]
    assert await session.scalar(select(func.count()).select_from(MetricQuarantine)) == 1
    kinds = set((await session.execute(select(MediaSignal.kind, MediaSignal.value))).all())
    assert ("wb_article", "318221") in kinds and ("mention", "waistline_shop") in kinds


async def test_enqueue_is_idempotent(session: AsyncSession) -> None:
    first = await q.enqueue(session, q.TaskType.FEED_HEAD, user_pk=1, window="2026-10-10T01")
    again = await q.enqueue(session, q.TaskType.FEED_HEAD, user_pk=1, window="2026-10-10T01")
    assert first is not None and again is None


async def test_claim_order_and_one_task_per_account(session: AsyncSession) -> None:
    await q.enqueue(session, q.TaskType.FEED_DEEP, user_pk=1, window="w")
    await q.enqueue(session, q.TaskType.PROFILE, user_pk=1, window="w")
    await q.enqueue(session, q.TaskType.MANUAL_REFRESH, user_pk=2, window="w")
    await session.commit()

    t1 = await q.claim(session)
    await session.commit()
    assert t1 is not None and t1.type == "manual_refresh"
    t2 = await q.claim(session)
    await session.commit()
    assert t2 is not None and t2.type == "profile" and t2.user_pk == 1
    # у аккаунта 1 уже идёт задача — feed_deep ждёт
    assert await q.claim(session) is None


async def test_low_priority_slot_skips_p0_p1(session: AsyncSession) -> None:
    await q.enqueue(session, q.TaskType.BACKFILL, user_pk=1, window="w")
    await q.enqueue(session, q.TaskType.BRAND_TAGGED, user_pk=2, window="w")
    await session.commit()
    t = await q.claim(session, low_priority_slot=True)
    assert t is not None and t.type == "brand_tagged"


async def test_crashed_worker_resumes_from_cursor(session: AsyncSession) -> None:
    await q.enqueue(session, q.TaskType.BACKFILL, user_pk=1, window="w")
    await session.commit()
    t = await q.claim(session)
    assert t is not None
    await q.heartbeat(session, t.id, cursor="page-7")
    # воркер упал: аренда истекла
    await session.execute(text("UPDATE scrape_task SET lease_until = now() - interval '1 minute'"))
    assert await q.recover_expired_leases(session) == 1
    await session.commit()

    again = await q.claim(session)
    assert again is not None and again.id == t.id
    assert again.cursor == "page-7" and again.pages_done == 1 and again.attempts == 2


async def test_retry_then_fail(session: AsyncSession) -> None:
    await q.enqueue(session, q.TaskType.PROFILE, user_pk=1, window="w")
    await session.commit()
    t = await q.claim(session)
    assert t is not None
    assert await q.fail_or_retry(session, t, "timeout") == "retry"
    await session.execute(text("UPDATE scrape_task SET attempts = 6"))
    await session.refresh(t)
    assert await q.fail_or_retry(session, t, "timeout") == "failed"
    await session.commit()
    assert (await session.get(ScrapeTask, t.id, populate_existing=True)).status == "failed"  # type: ignore[union-attr]


def test_retry_schedule() -> None:
    rng = random.Random(1)
    delays = [q.retry_delay(a, rng) for a in range(1, 7)]
    minutes = [d.total_seconds() / 60 if d else None for d in delays]
    for got, base in zip(minutes[:5], (1, 5, 20, 60, 180), strict=True):
        assert got is not None and base * 0.8 <= got <= base * 1.2
    assert minutes[5] is None
