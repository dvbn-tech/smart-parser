"""Проверки снимка метрик перед записью (техспека §5, Ф-9).

Принцип: лучше нет данных и алерт, чем неверные данные в расчётах.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum

from parser.parse.models import IgMetrics

DROP_TOLERANCE = 0.05
JUMP_FACTOR = 1000
JUMP_MIN_AGE = timedelta(days=7)
ZERO_VIEWS_MAX_AGE = timedelta(hours=1)


class Action(StrEnum):
    WRITE = "write"
    QUARANTINE = "quarantine"
    INVALID = "invalid"  # весь ответ невалиден: в базу ничего не пишем


@dataclass(frozen=True)
class PrevSnapshot:
    snapshot_date: date
    play_count: int


@dataclass(frozen=True)
class Verdict:
    action: Action
    flags: list[str] = field(default_factory=list)
    reason: str | None = None


def check_snapshot(
    metrics: IgMetrics,
    *,
    taken_at: datetime,
    is_reel: bool,
    prev: PrevSnapshot | None,
) -> Verdict:
    """prev — последний снимок за предыдущие дни (снимок за тот же день перезаписывается)."""
    views = metrics.play_count
    if not is_reel or views is None:
        return Verdict(Action.WRITE)

    age = metrics.captured_at - taken_at
    if views == 0 and age > ZERO_VIEWS_MAX_AGE:
        return Verdict(Action.INVALID, reason="play_count=0 for media older than 1h")

    if prev is None or prev.play_count <= 0:
        return Verdict(Action.WRITE)

    if views < prev.play_count:
        drop = (prev.play_count - views) / prev.play_count
        if drop <= DROP_TOLERANCE:
            return Verdict(Action.WRITE, flags=["metric_drop"])
        return Verdict(
            Action.QUARANTINE,
            reason=f"views dropped {drop:.1%}: {prev.play_count} -> {views}",
        )

    days = max((metrics.captured_at.date() - prev.snapshot_date).days, 1)
    if age > JUMP_MIN_AGE and views > prev.play_count * JUMP_FACTOR * days:
        return Verdict(
            Action.QUARANTINE,
            reason=f"views jumped x{views / prev.play_count:.0f}: {prev.play_count} -> {views}",
        )
    return Verdict(Action.WRITE)
