"""Показатели креатора (техспека §9.3) — чистые функции над его роликами."""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

SPIKE_CATEGORIES = {"high", "strong", "viral"}


@dataclass(frozen=True)
class ReelFacts:
    taken_at: datetime
    views: int | None
    likes: int | None
    comments: int | None
    er: Decimal | None
    spike_category: str | None
    spike_ratio: Decimal | None
    duration_s: Decimal | None
    is_paid_partnership: bool | None
    is_original_audio: bool | None


def _median(xs: Sequence[float]) -> float | None:
    return statistics.median(xs) if xs else None


def _mean(xs: Sequence[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def _int(v: float | None) -> int | None:
    return None if v is None else round(v)


def _dec(v: float | None, places: str = "0.0001") -> Decimal | None:
    return None if v is None else Decimal(str(v)).quantize(Decimal(places))


def _share(flags: Sequence[bool | None]) -> Decimal | None:
    known = [f for f in flags if f is not None]
    return _dec(sum(known) / len(known)) if known else None


def creator_stats(
    reels: Sequence[ReelFacts],
    *,
    now: datetime,
    views_30d: int | None,
    followers: int | None,
    followers_7d_ago: int | None,
    followers_30d_ago: int | None,
) -> dict[str, object]:
    """reels — все Reels автора. «Последние 20» — по дате публикации."""
    ordered = sorted(reels, key=lambda r: r.taken_at, reverse=True)
    last20 = ordered[:20]
    prev20 = ordered[20:40]
    v20 = [r.views for r in last20 if r.views is not None]
    vprev = [r.views for r in prev20 if r.views is not None]
    all_views = [r.views for r in ordered if r.views is not None]
    m20, mprev = _median(v20), _median(vprev)
    mean20 = _mean(v20)
    cv = statistics.pstdev(v20) / mean20 if mean20 and len(v20) >= 2 else None

    def since(days: int) -> list[ReelFacts]:
        return [r for r in ordered if r.taken_at >= now - timedelta(days=days)]

    spikes = [r for r in ordered if r.spike_category in SPIKE_CATEGORIES]
    ratios = [float(r.spike_ratio) for r in ordered if r.spike_ratio is not None]
    durations = [float(r.duration_s) for r in ordered if r.duration_s is not None]
    ers = [float(r.er) for r in last20 if r.er is not None]
    p90 = (
        statistics.quantiles(all_views, n=10)[-1]
        if len(all_views) >= 10
        else (max(all_views) if all_views else None)
    )

    return {
        "reels_total": len(ordered),
        "reels_7d": len(since(7)),
        "reels_30d": len(since(30)),
        "reels_90d": len(since(90)),
        "posts_per_week_90d": _dec(len(since(90)) / (90 / 7), "0.01"),
        "avg_views_20": _int(mean20),
        "median_views_20": _int(m20),
        "median_views_prev_20": _int(mprev),
        "trend": _dec(m20 / mprev, "0.001") if m20 is not None and mprev else None,
        "p90_views": _int(p90),
        "max_views": max(all_views) if all_views else None,
        "min_views_20": min(v20) if v20 else None,
        "total_views": sum(all_views) if all_views else None,
        "views_30d": views_30d,
        "views_per_day_30d": round(views_30d / 30) if views_30d is not None else None,
        "cv_views_20": _dec(cv, "0.001"),
        "avg_likes_20": _int(_mean([r.likes for r in last20 if r.likes is not None])),
        "avg_comments_20": _int(_mean([r.comments for r in last20 if r.comments is not None])),
        "er_median_20": _dec(_median(ers)),
        "spikes_total": len(spikes),
        "spikes_90d": len([r for r in spikes if r.taken_at >= now - timedelta(days=90)]),
        "viral_total": len([r for r in spikes if r.spike_category == "viral"]),
        "hit_rate": _dec(len(spikes) / len(ordered)) if ordered else None,
        "best_ratio": _dec(max(ratios), "0.01") if ratios else None,
        "avg_duration_s": _dec(_mean(durations), "0.01"),
        "paid_share": _share([r.is_paid_partnership for r in ordered]),
        "original_audio_share": _share([r.is_original_audio for r in ordered]),
        "followers": followers,
        "followers_delta_7d": followers - followers_7d_ago
        if followers is not None and followers_7d_ago is not None
        else None,
        "followers_delta_30d": followers - followers_30d_ago
        if followers is not None and followers_30d_ago is not None
        else None,
        "views_to_followers": _dec(m20 / followers) if m20 is not None and followers else None,
        "first_reel_at": ordered[-1].taken_at if ordered else None,
        "last_reel_at": ordered[0].taken_at if ordered else None,
    }
