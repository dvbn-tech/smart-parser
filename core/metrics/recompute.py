"""Ночной пересчёт (техспека §9): media_brand, media_stats, media_daily_views, account_stats.

Полный пересчёт: при ~75 тыс. роликов и ~5 млн снимков укладывается в
минуты. Инкрементальный режим (только ролики с новыми снимками) — следующий шаг.
"""

import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.db.models import (
    Account,
    AccountStats,
    Brand,
    BrandAccount,
    Media,
    MediaBrand,
    MediaDailyViews,
    MediaStats,
)
from core.metrics.creators import ReelFacts, creator_stats
from core.metrics.daily import daily_increments
from core.metrics.spikes import MediaViews, compute_spike
from parser.signals.extract import extract_hashtags, extract_mentions


@dataclass(frozen=True)
class RecomputeResult:
    media: int
    media_brand: int
    daily_rows: int
    accounts: int
    seconds: float


async def recompute_all(session: AsyncSession, now: datetime | None = None) -> RecomputeResult:
    """Порядок из техспеки §9: media_brand → media_stats + media_daily_views → креаторы."""
    started = time.monotonic()
    now = now or datetime.now(UTC)
    links = await _media_brand(session)
    stats, daily = await _media_stats(session, now)
    accounts = await _account_stats(session, now)
    await session.commit()
    return RecomputeResult(stats, links, daily, accounts, round(time.monotonic() - started, 2))


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

    # Известные артикулы брендов: WW-код или артикул WB в подписи → ролик бренда
    brand_by_article: dict[tuple[str, str], set[int]] = defaultdict(set)
    for bid, kind, value in await session.execute(
        text("SELECT brand_id, kind, value FROM brand_article")
    ):
        brand_by_article[("ww_code" if kind == "ww" else "wb_article", value)].add(bid)
    article_brands: dict[int, set[int]] = defaultdict(set)
    if brand_by_article:
        for media_pk, kind, value in await session.execute(
            text(
                "SELECT media_pk, kind, value FROM media_signal"
                " WHERE kind IN ('ww_code', 'wb_article')"
            )
        ):
            article_brands[media_pk] |= brand_by_article.get((kind, value), set())

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
            elif b.id in article_brands.get(pk, set()):
                found[b.id] = "article"
            elif tags[b.id] & hashtags:
                found[b.id] = "hashtag"
        rows_out += [{"media_pk": pk, "brand_id": bid, "reason": r} for bid, r in found.items()]

    await session.execute(delete(MediaBrand))
    for i in range(0, len(rows_out), 5000):
        await session.execute(insert(MediaBrand).values(rows_out[i : i + 5000]))
    return len(rows_out)


async def _media_stats(session: AsyncSession, now: datetime) -> tuple[int, int]:
    """media_stats и media_daily_views. Возвращает (роликов, строк прироста)."""
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
    daily_rows: list[dict[str, object]] = []
    for reels in by_owner.values():
        for m in reels:
            r = compute_spike(
                m, reels, now=now, spike_min_views=s.spike_min_views, rocket_views=s.rocket_views
            )
            daily = daily_increments(m.taken_at.date(), m.snapshots)
            daily_rows += [
                {"media_pk": m.media_pk, "date": d, "views_increment": v}
                for d, v in daily.increments.items()
            ]
            likes, comments, reshares = latest.get(m.media_pk, (None, None, None))
            age_days = max((now - m.taken_at).total_seconds() / 86400, 1)
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
                    "likes": likes,
                    "comments": comments,
                    "reshares": reshares,
                    "views_per_day": Decimal(r.views / age_days).quantize(Decimal("0.01"))
                    if r.views is not None
                    else None,
                    "views_before_observation": daily.before_observation or None,
                    "computed_at": now,
                }
            )
    await session.execute(delete(MediaStats))
    for i in range(0, len(out), 2000):
        await session.execute(insert(MediaStats).values(out[i : i + 2000]))
    await session.execute(delete(MediaDailyViews))
    for i in range(0, len(daily_rows), 10000):
        await session.execute(insert(MediaDailyViews).values(daily_rows[i : i + 10000]))
    return len(out), len(daily_rows)


async def _account_stats(session: AsyncSession, now: datetime) -> int:
    rows = await session.execute(
        text(
            """
            SELECT m.owner_user_pk, m.taken_at, s.views, s.likes, s.comments, s.er,
                   s.spike_category, s.spike_ratio, m.duration_s, m.is_paid_partnership,
                   m.is_original_audio
              FROM media m JOIN media_stats s USING (media_pk)
             WHERE m.product_type = 'clips' AND m.missing_since IS NULL
            """
        )
    )
    reels: dict[int, list[ReelFacts]] = defaultdict(list)
    for owner, *facts in rows:
        reels[owner].append(ReelFacts(*facts))

    daily = await session.execute(
        text(
            """
            SELECT m.owner_user_pk, sum(d.views_increment)::bigint
              FROM media_daily_views d JOIN media m USING (media_pk)
             WHERE d.date > :since GROUP BY 1
            """
        ),
        {"since": (now - timedelta(days=30)).date()},
    )
    # не dict(result): у результата SQLAlchemy 2.1 есть keys(), и dict() считает его словарём
    views_30d: dict[int, int] = {pk: views for pk, views in daily}
    followers: dict[int, dict[int, int]] = defaultdict(dict)
    snap_rows = await session.execute(
        text(
            """
            SELECT DISTINCT ON (user_pk, bucket) user_pk, bucket, followers_count FROM (
                SELECT user_pk, followers_count, snapshot_date,
                       CASE WHEN snapshot_date >= :d0 THEN 0
                            WHEN snapshot_date <= :d7 AND snapshot_date > :d14 THEN 7
                            WHEN snapshot_date <= :d30 AND snapshot_date > :d45 THEN 30
                       END AS bucket
                  FROM account_snapshot) x
             WHERE bucket IS NOT NULL
             ORDER BY user_pk, bucket, snapshot_date DESC
            """
        ),
        {
            "d0": (now - timedelta(days=3)).date(),
            "d7": (now - timedelta(days=7)).date(),
            "d14": (now - timedelta(days=14)).date(),
            "d30": (now - timedelta(days=30)).date(),
            "d45": (now - timedelta(days=45)).date(),
        },
    )
    for user_pk, bucket, count in snap_rows:
        followers[user_pk][bucket] = count

    out = []
    for user_pk in set(reels) | set(followers):
        f = followers.get(user_pk, {})
        stats = creator_stats(
            reels.get(user_pk, []),
            now=now,
            views_30d=views_30d.get(user_pk),
            followers=f.get(0),
            followers_7d_ago=f.get(7),
            followers_30d_ago=f.get(30),
        )
        out.append({"user_pk": user_pk, **stats, "computed_at": now})
    await session.execute(delete(AccountStats))
    for i in range(0, len(out), 1000):
        await session.execute(insert(AccountStats).values(out[i : i + 1000]))
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
