from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from core.metrics.creators import ReelFacts, creator_stats
from core.metrics.daily import daily_increments

D = date(2026, 10, 1)


def test_observed_from_birth_interpolates_from_zero() -> None:
    r = daily_increments(D, {D + timedelta(days=1): 1000, D + timedelta(days=3): 3000})
    assert r.before_observation == 0
    assert r.increments == {
        D + timedelta(days=1): 1000,
        D + timedelta(days=2): 1000,
        D + timedelta(days=3): 1000,
    }


def test_snapshot_on_publication_day() -> None:
    assert daily_increments(D, {D: 500}).increments == {D: 500}


def test_history_reel_is_not_spread_over_days() -> None:
    first = D + timedelta(days=60)
    r = daily_increments(D, {first: 900_000, first + timedelta(days=1): 900_500})
    assert r.before_observation == 900_000
    assert r.increments == {first + timedelta(days=1): 500}


def test_negative_increment_clipped() -> None:
    r = daily_increments(D, {D + timedelta(days=1): 1000, D + timedelta(days=2): 950})
    assert r.increments[D + timedelta(days=2)] == 0


def test_increments_sum_to_last_snapshot() -> None:
    snaps = {D + timedelta(days=1): 333, D + timedelta(days=4): 1000, D + timedelta(days=9): 4321}
    assert sum(daily_increments(D, snaps).increments.values()) == 4321


NOW = datetime(2026, 10, 10, tzinfo=UTC)


def reel(days_ago: int, views: int, cat: str = "none", **kw: object) -> ReelFacts:
    base: dict[str, object] = dict(
        taken_at=NOW - timedelta(days=days_ago),
        views=views,
        likes=views // 20,
        comments=views // 1000,
        er=Decimal("0.05"),
        spike_category=cat,
        spike_ratio=Decimal("1.0"),
        duration_s=Decimal("20"),
        is_paid_partnership=False,
        is_original_audio=True,
    )
    base.update(kw)
    return ReelFacts(**base)  # type: ignore[arg-type]


def test_creator_stats() -> None:
    reels = [reel(i * 3, 100_000) for i in range(20)] + [
        reel(60 + i * 3, 50_000) for i in range(20)
    ]
    reels[0] = reel(0, 1_000_000, "viral", spike_ratio=Decimal("10"), is_paid_partnership=True)
    st = creator_stats(
        reels,
        now=NOW,
        views_30d=600_000,
        followers=200_000,
        followers_7d_ago=190_000,
        followers_30d_ago=150_000,
    )
    assert st["reels_total"] == 40
    assert st["reels_7d"] == 3 and st["reels_30d"] == 11  # 0, 3, …, 30 дней назад
    assert st["median_views_20"] == 100_000 and st["median_views_prev_20"] == 50_000
    assert st["trend"] == Decimal("2.000")
    assert st["avg_views_20"] == 145_000
    assert st["max_views"] == 1_000_000 and st["viral_total"] == 1 and st["spikes_total"] == 1
    assert st["hit_rate"] == Decimal("0.0250")
    assert st["views_per_day_30d"] == 20_000
    assert st["followers_delta_7d"] == 10_000 and st["followers_delta_30d"] == 50_000
    assert st["views_to_followers"] == Decimal("0.5000")
    assert st["paid_share"] == Decimal("0.0250") and st["original_audio_share"] == Decimal("1.0000")
    assert st["avg_likes_20"] == 7_250


def test_creator_without_reels() -> None:
    st = creator_stats(
        [], now=NOW, views_30d=None, followers=1000, followers_7d_ago=None, followers_30d_ago=None
    )
    assert st["reels_total"] == 0 and st["median_views_20"] is None and st["hit_rate"] is None
