"""Просмотры по дням (техспека §9.1).

P(m, d) — снимок за дату d; если его нет — линейная интерполяция между
ближайшими снимками. До публикации P = 0; первый снимок интерполируется от 0
в день публикации — но только если ролик начали наблюдать молодым.

Ролик из истории (первый снимок сделан позже, чем через 2 дня после
публикации): его просмотры до первого снимка — «до начала наблюдения» и по
дням не распределяются, иначе график покажет фальшивый всплеск в день запуска.

views_increment(m, d) = P(m, d) − P(m, d − 1); отрицательный прирост
(списание накрутки) обрезается до 0.
"""

import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

OBSERVED_FROM_BIRTH_DAYS = 2


@dataclass(frozen=True)
class DailyViews:
    increments: dict[date, int]
    before_observation: int  # просмотры, набранные до первого снимка (ролик из истории)


def daily_increments(taken: date, snapshots: Mapping[date, int]) -> DailyViews:
    if not snapshots:
        return DailyViews({}, 0)
    points = sorted(snapshots.items())
    first_day, first_views = points[0]
    before = 0
    if (first_day - taken).days <= OBSERVED_FROM_BIRTH_DAYS:
        if first_day > taken:
            points.insert(0, (taken, 0))
        else:
            # снимок в день публикации: всё набранное — прирост этого дня
            points.insert(0, (taken - timedelta(days=1), 0))
    else:
        before = first_views

    out: dict[date, int] = {}
    for (d0, v0), (d1, v1) in itertools.pairwise(points):
        span = (d1 - d0).days
        prev = float(v0)
        for i in range(1, span + 1):
            cur = v0 + (v1 - v0) * i / span
            inc = round(cur) - round(prev)
            out[d0 + timedelta(days=i)] = max(inc, 0)
            prev = cur
    return DailyViews(out, before)
