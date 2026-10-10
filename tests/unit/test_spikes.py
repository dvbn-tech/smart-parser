from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from core.metrics.spikes import Category, MediaViews, Method, categorize, compute_spike

NOW = datetime(2026, 10, 10, 6, 30, tzinfo=UTC)
GLOBAL = {"spike_min_views": 50_000, "rocket_views": 500_000}


def history_reel(pk: int, days_ago: int, views: int) -> MediaViews:
    """Ролик из истории: один снимок, сделанный сегодня."""
    return MediaViews(pk, NOW - timedelta(days=days_ago), {NOW.date(): views})


def test_reference_example_x13_3_viral() -> None:
    """Проверочный пример ТЗ: медиана 180 000, ролик 2,4 млн → ×13,3, viral."""
    prev = [history_reel(i, 30 + i, 180_000) for i in range(1, 21)]
    target = history_reel(100, 10, 2_400_000)
    r = compute_spike(target, [*prev, target], now=NOW, **GLOBAL)
    assert r.baseline_median == 180_000
    assert r.ratio == Decimal("13.33")
    assert r.category == Category.VIRAL
    assert r.method == Method.CURRENT_VIEWS
    assert r.is_rocket and not r.is_early


def test_less_than_8_previous_is_insufficient() -> None:
    prev = [history_reel(i, 30 + i, 100_000) for i in range(1, 8)]
    r = compute_spike(history_reel(100, 10, 900_000), prev, now=NOW, **GLOBAL)
    assert r.category == Category.INSUFFICIENT and r.ratio is None


def test_baseline_uses_only_20_most_recent_previous() -> None:
    recent = [history_reel(i, 20 + i, 100_000) for i in range(1, 21)]
    old = [history_reel(100 + i, 200 + i, 10) for i in range(30)]
    later = [history_reel(500, 1, 1)]  # опубликован позже — не в базе
    r = compute_spike(history_reel(999, 15, 300_000), [*recent, *old, *later], now=NOW, **GLOBAL)
    assert r.baseline_median == 100_000 and r.category == Category.HIGH


def observed(pk: int, taken: date, daily: list[int]) -> MediaViews:
    """Ролик под наблюдением с рождения: снимки на день 1..N после публикации."""
    snaps = {taken + timedelta(days=i + 1): v for i, v in enumerate(daily)}
    return MediaViews(pk, datetime(taken.year, taken.month, taken.day, 12, tzinfo=UTC), snaps)


def test_age_matched_uses_views_at_day_7() -> None:
    start = date(2026, 7, 1)
    # у предыдущих роликов к 7-му дню 100k, потом они растут до 1M — это не должно влиять
    prev = [
        observed(i, start + timedelta(days=i), [50_000] * 6 + [100_000] + [1_000_000] * 20)
        for i in range(20)
    ]
    target = observed(100, date(2026, 9, 1), [100_000] * 6 + [600_000, 700_000])
    r = compute_spike(target, prev, now=NOW, **GLOBAL)
    assert r.method == Method.AGE_MATCHED_7D
    assert r.ratio == Decimal("6.00") and r.category == Category.STRONG
    assert r.views == 700_000


def test_interpolates_missing_day() -> None:
    m = MediaViews(
        1, datetime(2026, 9, 1, tzinfo=UTC), {date(2026, 9, 6): 600, date(2026, 9, 10): 1000}
    )
    assert m.views_at_age(7) == pytest.approx(800)


def test_no_interpolation_before_first_snapshot_of_history_reel() -> None:
    m = history_reel(1, 100, 5000)
    assert m.views_at_age(7) is None


def test_early_spike() -> None:
    taken = NOW.date() - timedelta(days=2)
    prev = [
        observed(i, date(2026, 8, 1) + timedelta(days=i), [10_000, 20_000, 30_000])
        for i in range(10)
    ]
    target = MediaViews(
        100, datetime(taken.year, taken.month, taken.day, 12, tzinfo=UTC), {NOW.date(): 200_000}
    )
    r = compute_spike(target, prev, now=NOW, **GLOBAL)
    assert r.is_early and r.method == Method.EARLY
    assert r.ratio == Decimal("10.00") and r.category == Category.VIRAL


def test_early_not_computed_without_age_matched_baseline() -> None:
    prev = [history_reel(i, 30 + i, 10_000) for i in range(1, 21)]
    r = compute_spike(history_reel(100, 2, 500_000), prev, now=NOW, **GLOBAL)
    assert r.is_early and r.ratio is None


@pytest.mark.parametrize(
    ("ratio", "views", "expected"),
    [
        ("1.99", 100_000, Category.NONE),
        ("2", 100_000, Category.HIGH),
        ("4.99", 100_000, Category.HIGH),
        ("5", 100_000, Category.STRONG),
        ("10", 100_000, Category.VIRAL),
        ("50", 49_999, Category.NONE),  # ниже порога бренда
        (None, 100_000, Category.INSUFFICIENT),
    ],
)
def test_categorize(ratio: str | None, views: int, expected: Category) -> None:
    assert categorize(Decimal(ratio) if ratio else None, views, 50_000) == expected
