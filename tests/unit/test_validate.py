from datetime import UTC, date, datetime, timedelta

from parser.parse.models import IgMetrics
from parser.validate.metrics import Action, PrevSnapshot, check_snapshot

NOW = datetime(2026, 10, 10, 1, 0, tzinfo=UTC)
YESTERDAY = date(2026, 10, 9)


def metrics(views: int) -> IgMetrics:
    return IgMetrics(
        media_pk=1,
        play_count=views,
        like_count=None,
        comment_count=None,
        reshare_count=None,
        likes_hidden=False,
        comments_disabled=False,
        captured_at=NOW,
    )


def check(views: int, prev: int | None, age: timedelta = timedelta(days=30)):  # type: ignore[no-untyped-def]
    p = PrevSnapshot(YESTERDAY, prev) if prev is not None else None
    return check_snapshot(metrics(views), taken_at=NOW - age, is_reel=True, prev=p)


def test_normal_growth() -> None:
    assert check(1100, 1000).action == Action.WRITE


def test_small_drop_is_flagged() -> None:
    v = check(960, 1000)
    assert v.action == Action.WRITE and v.flags == ["metric_drop"]


def test_drop_over_5_percent_is_quarantined() -> None:
    assert check(940, 1000).action == Action.QUARANTINE


def test_jump_1000x_on_old_reel_is_quarantined() -> None:
    assert check(1_000_001, 1000).action == Action.QUARANTINE


def test_jump_on_young_reel_is_ok() -> None:
    assert check(1_000_001, 1000, age=timedelta(days=2)).action == Action.WRITE


def test_zero_views_after_1h_is_invalid() -> None:
    assert check(0, None, age=timedelta(hours=2)).action == Action.INVALID


def test_zero_views_in_first_hour_is_ok() -> None:
    assert check(0, None, age=timedelta(minutes=30)).action == Action.WRITE


def test_non_reel_is_not_checked() -> None:
    v = check_snapshot(metrics(0), taken_at=NOW - timedelta(days=3), is_reel=False, prev=None)
    assert v.action == Action.WRITE
