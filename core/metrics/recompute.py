"""Ночной пересчёт (техспека §9): media_brand → media_stats.

Полный пересчёт: при ~75 тыс. роликов и ~5 млн снимков укладывается в
минуты. Инкрементальный режим (только ролики с новыми снимками) — следующий шаг.
"""

import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.db.models import Account, Brand, BrandAccount, Media, MediaBrand, MediaStats
from core.metrics.spikes import MediaViews, compute_spike
from parser.signals.extract import extract_hashtags, extract_mentions


@dataclass(frozen=True)
class RecomputeResult:
    media: int
    media_brand: int
    seconds: float


async def recompute_all(session: AsyncSession, now: datetime | None = None) -> RecomputeResult:
    started = time.monotonic()
    now = now or datetime.now(UTC)
    links = await _media_brand(session)
    stats = await _media_stats(session, now)
    await session.commit()
    return RecomputeResult(stats, links, round(time.monotonic() - started, 2))


async def _media_brand(session: AsyncSession) -> int:
    brands = (await session.execute(select(Brand))).scalars().all()
    tracked = (
        await session.execute(
            select(BrandAccount.brand_id, BrandAccount.user_pk).where(
                BrandAccount.status == "tracked", BrandAccount.role == "creator"
            )
        )
    ).all()
    creators: dict[int, set[int]] = defaultdict(set)
    for brand_id, user_pk in tracked:
        creators[user_pk].add(brand_id)

    shop_pk = {b.id: b.shop_user_pk for b in brands if b.shop_user_pk}
    shop_names: dict[int, str] = {}
    if shop_pk:
        rows = await session.execute(
            select(Account.user_pk, Account.username).where(Account.user_pk.in_(shop_pk.values()))
        )
        by_pk = dict(rows.tuples().all())
        shop_names = {bid: by_pk[pk] for bid, pk in shop_pk.items() if pk in by_pk}
    tags = {b.id: {t.lower() for t in b.hashtags} for b in brands}

    rows_out: list[dict[str, object]] = []
    medias = await session.execute(
        select(
            Media.media_pk,
            Media.owner_user_pk,
            Media.caption,
            Media.coauthors,
            Media.usertags,
            Media.sponsor_user_pks,
        ).where(Media.product_type == "clips")
    )
    for pk, owner, caption, coauthors, usertags, sponsors in medias:
        found: dict[int, str] = {}
        for bid in creators.get(owner, ()):
            found[bid] = "creator"
        hashtags = set(extract_hashtags(caption or ""))
        mentions = set(extract_mentions(caption or ""))
        for b in brands:
            if b.id in found:
                continue
            spk = shop_pk.get(b.id)
            if owner == spk:
                found[b.id] = "shop"
            elif spk and spk in (sponsors or []):
                found[b.id] = "partnership"
            elif spk and spk in (coauthors or []):
                found[b.id] = "collab"
            elif spk and spk in (usertags or []):
                found[b.id] = "usertag"
            elif shop_names.get(b.id) in mentions:
                found[b.id] = "mention"
            elif tags[b.id] & hashtags:
                found[b.id] = "hashtag"
        rows_out += [{"media_pk": pk, "brand_id": bid, "reason": r} for bid, r in found.items()]

    await session.execute(delete(MediaBrand))
    for i in range(0, len(rows_out), 5000):
        await session.execute(insert(MediaBrand).values(rows_out[i : i + 5000]))
    return len(rows_out)


async def _media_stats(session: AsyncSession, now: datetime) -> int:
    s = get_settings()
    media = (
        await session.execute(
            select(Media.media_pk, Media.owner_user_pk, Media.taken_at).where(
                Media.product_type == "clips"
            )
        )
    ).all()
    snaps: dict[int, dict[date, int]] = defaultdict(dict)
    latest: dict[int, tuple[int | None, int | None, int | None]] = {}
    rows = await session.execute(
        text(
            "SELECT media_pk, snapshot_date, play_count, like_count, comment_count, reshare_count"
            " FROM metric_snapshot ORDER BY media_pk, snapshot_date"
        )
    )
    for pk, d, plays, likes, comments, reshares in rows:
        snaps[pk][d] = plays
        latest[pk] = (likes, comments, reshares)

    by_owner: dict[int, list[MediaViews]] = defaultdict(list)
    for pk, owner, taken_at in media:
        by_owner[owner].append(MediaViews(pk, taken_at, snaps.get(pk, {})))

    out: list[dict[str, object]] = []
    for reels in by_owner.values():
        for m in reels:
            r = compute_spike(
                m, reels, now=now, spike_min_views=s.spike_min_views, rocket_views=s.rocket_views
            )
            out.append(
                {
                    "media_pk": m.media_pk,
                    "views": r.views,
                    "views_24h": _growth(m.snapshots, 1),
                    "views_7d": _growth(m.snapshots, 7),
                    "baseline_median": r.baseline_median,
                    "spike_ratio": r.ratio,
                    "spike_category": str(r.category),
                    "spike_method": str(r.method) if r.method else None,
                    "is_early": r.is_early,
                    "is_rocket": r.is_rocket,
                    "er": _er(r.views, latest.get(m.media_pk)),
                    "computed_at": now,
                }
            )
    await session.execute(delete(MediaStats))
    for i in range(0, len(out), 3000):
        await session.execute(insert(MediaStats).values(out[i : i + 3000]))
    return len(out)


def _growth(snapshots: Mapping[date, int], days: int) -> int | None:
    if len(snapshots) < 2:
        return None
    dates = sorted(snapshots)
    last = dates[-1]
    base = [d for d in dates if (last - d).days >= days]
    if not base:
        return None
    return max(snapshots[last] - snapshots[base[-1]], 0)


def _er(
    views: int | None, latest: tuple[int | None, int | None, int | None] | None
) -> Decimal | None:
    if not views or latest is None or latest[0] is None:
        return None  # лайки скрыты — ER не считается
    total = sum(v or 0 for v in latest)
    return (Decimal(total) / Decimal(views)).quantize(Decimal("0.0001"))
