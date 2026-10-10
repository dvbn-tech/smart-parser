"""Всплески (техспека §9.2, Ф-21).

spike(m) = P(m, t_m + a) / median(P(x, t_x + a) for x in prev20(m))

prev20 — 20 предыдущих Reels того же автора по taken_at, без самого m;
меньше 8 — insufficient_data. Финальный всплеск: a = 7 дней для роликов старше
7 дней. Ранний: a = текущий возраст. Если у предыдущих роликов нет снимков на
возрасте a (история до начала сбора), финальный считается по текущим
просмотрам обоих, а ранний не считается. Метод пишется в media_stats.
"""

import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

BASELINE_SIZE = 20
MIN_BASELINE = 8
FINAL_AGE_DAYS = 7
# Нулевая точка в момент публикации используется, только если ролик
# начали наблюдать молодым — иначе история «до наблюдения» исказит кривую.
BIRTH_ANCHOR_MAX_AGE_DAYS = 2


class Category(StrEnum):
    NONE = "none"
    HIGH = "high"
    STRONG = "strong"
    VIRAL = "viral"
    INSUFFICIENT = "insufficient_data"


class Method(StrEnum):
    AGE_MATCHED_7D = "age_matched_7d"
    EARLY = "early"
    CURRENT_VIEWS = "current_views"


@dataclass(frozen=True)
class MediaViews:
    media_pk: int
    taken_at: datetime
    snapshots: Mapping[date, int]  # дата снимка → play_count

    @property
    def current_views(self) -> int | None:
        return self.snapshots[max(self.snapshots)] if self.snapshots else None

    def views_at_age(self, age_days: int) -> float | None:
        """P(m, t_m + age): снимок на дату или линейная интерполяция между соседними."""
        if not self.snapshots:
            return None
        target = self.taken_at.date() + timedelta(days=age_days)
        if target in self.snapshots:
            return float(self.snapshots[target])

        points = sorted(self.snapshots.items())
        first_date = points[0][0]
        if (first_date - self.taken_at.date()).days <= BIRTH_ANCHOR_MAX_AGE_DAYS:
            points.insert(0, (self.taken_at.date(), 0))

        before = [(d, v) for d, v in points if d < target]
        after = [(d, v) for d, v in points if d > target]
        if not before or not after:
            return None
        (d0, v0), (d1, v1) = before[-1], after[0]
        frac = (target - d0).days / (d1 - d0).days
        return v0 + (v1 - v0) * frac


@dataclass(frozen=True)
class SpikeResult:
    views: int | None
    baseline_median: int | None
    ratio: Decimal | None
    category: Category
    method: Method | None
    is_early: bool
    is_rocket: bool


def categorize(ratio: Decimal | None, views: int | None, min_views: int) -> Category:
    """×2–5 high, ×5–10 strong, ×10+ viral — только при просмотрах ≥ порога."""
    if ratio is None:
        return Category.INSUFFICIENT
    if views is None or views < min_views:
        return Category.NONE
    if ratio >= 10:
        return Category.VIRAL
    if ratio >= 5:
        return Category.STRONG
    if ratio >= 2:
        return Category.HIGH
    return Category.NONE


def compute_spike(
    media: MediaViews,
    author_reels: Sequence[MediaViews],
    *,
    now: datetime,
    spike_min_views: int,
    rocket_views: int,
) -> SpikeResult:
    """author_reels — Reels автора (можно все, включая сам ролик): prev20 выбирается здесь."""
    views = media.current_views
    is_rocket = views is not None and views >= rocket_views
    prev = sorted(
        (x for x in author_reels if x.taken_at < media.taken_at and x.media_pk != media.media_pk),
        key=lambda x: x.taken_at,
        reverse=True,
    )[:BASELINE_SIZE]

    def result(
        ratio: Decimal | None, baseline: int | None, method: Method | None, early: bool
    ) -> SpikeResult:
        return SpikeResult(
            views=views,
            baseline_median=baseline,
            ratio=ratio,
            category=categorize(ratio, views, spike_min_views),
            method=method,
            is_early=early,
            is_rocket=is_rocket,
        )

    if len(prev) < MIN_BASELINE or views is None:
        return result(None, None, None, False)

    age_days = (now.date() - media.taken_at.date()).days
    if age_days >= FINAL_AGE_DAYS:
        own = media.views_at_age(FINAL_AGE_DAYS)
        base = [v for x in prev if (v := x.views_at_age(FINAL_AGE_DAYS)) is not None]
        if own is not None and len(base) >= MIN_BASELINE:
            return _ratio_result(own, base, Method.AGE_MATCHED_7D, early=False, result=result)
        current = [v for x in prev if (v := x.current_views) is not None]
        if len(current) < MIN_BASELINE:
            return result(None, None, None, False)
        return _ratio_result(
            float(views), current, Method.CURRENT_VIEWS, early=False, result=result
        )

    base = [v for x in prev if (v := x.views_at_age(age_days)) is not None]
    if len(base) < MIN_BASELINE:
        # Ранний всплеск без снимков предыдущих роликов на том же возрасте не считается
        return result(None, None, None, True)
    return _ratio_result(float(views), base, Method.EARLY, early=True, result=result)


_ResultFn = Callable[[Decimal | None, int | None, Method | None, bool], SpikeResult]


def _ratio_result(
    own: float, base: list[float] | list[int], method: Method, *, early: bool, result: _ResultFn
) -> SpikeResult:
    median = statistics.median(base)
    if median <= 0:
        return result(None, None, None, early)
    ratio = (Decimal(str(own)) / Decimal(str(median))).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return result(ratio, round(median), method, early)
