"""Запись разобранных данных в базу. Всё — upsert по user_pk / media_pk (идемпотентность)."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Text, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import (
    Account,
    AccountSnapshot,
    AccountUsernameHistory,
    Media,
    MediaSignal,
    MetricQuarantine,
    MetricSnapshot,
)
from parser.parse.models import IgMedia, IgMetrics, IgProfile
from parser.signals.extract import Signal
from parser.validate.metrics import Action, PrevSnapshot, Verdict


async def upsert_account(session: AsyncSession, p: IgProfile, now: datetime) -> bool:
    """Профиль по user_pk. Смена ника пишется в историю. Возвращает True, если ник сменился."""
    existing = await session.get(Account, p.user_pk)
    renamed = existing is not None and existing.username != p.username

    # Ник мог перейти от другого аккаунта, который сам переименовался:
    # освобождаем ник, чтобы не нарушить уникальность (история остаётся по user_pk).
    await session.execute(
        update(Account)
        .where(func.lower(Account.username) == p.username, Account.user_pk != p.user_pk)
        .values(username=func.concat(Account.username, "#", cast(Account.user_pk, Text)))
        .execution_options(synchronize_session=False)
    )

    status = "private" if p.is_private else "active"
    values: dict[str, Any] = {
        "user_pk": p.user_pk,
        "username": p.username,
        "full_name": p.full_name,
        "biography": p.biography,
        "external_url": p.external_url,
        "category": p.category,
        "is_private": p.is_private,
        "is_verified": p.is_verified,
        "is_business": p.is_business,
        "status": status,
        "not_found_since": None,
        "last_scraped_at": now,
    }
    stmt = insert(Account).values(**values)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Account.user_pk],
            set_={k: stmt.excluded[k] for k in values if k != "user_pk"},
        )
    )

    if existing is None or renamed:
        await session.execute(
            update(AccountUsernameHistory)
            .where(
                AccountUsernameHistory.user_pk == p.user_pk,
                AccountUsernameHistory.seen_to.is_(None),
            )
            .values(seen_to=now)
        )
        session.add(AccountUsernameHistory(user_pk=p.user_pk, username=p.username, seen_from=now))
    return renamed


async def write_account_snapshot(
    session: AsyncSession, p: IgProfile, snapshot_date: date, raw_response_id: int
) -> None:
    values = {
        "user_pk": p.user_pk,
        "snapshot_date": snapshot_date,
        "followers_count": p.followers_count,
        "following_count": p.following_count,
        "media_count": p.media_count,
        "raw_response_id": raw_response_id,
    }
    stmt = insert(AccountSnapshot).values(**values)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_pk", "snapshot_date"],
            set_={k: stmt.excluded[k] for k in values if k not in ("user_pk", "snapshot_date")},
        )
    )


_MEDIA_MUTABLE = (
    "caption",
    "duration_s",
    "is_pinned",
    "coauthors",
    "usertags",
    "is_paid_partnership",
    "sponsor_user_pks",
    "audio_id",
    "audio_title",
    "is_original_audio",
)


async def upsert_media(session: AsyncSession, m: IgMedia, now: datetime) -> tuple[bool, bool]:
    """Ролик по media_pk. Возвращает (новый ли ролик, изменилась ли подпись)."""
    old_caption = (
        await session.execute(select(Media.caption).where(Media.media_pk == m.media_pk))
    ).first()
    is_new = old_caption is None
    values: dict[str, Any] = {
        "media_pk": m.media_pk,
        "shortcode": m.shortcode,
        "owner_user_pk": m.owner_user_pk,
        "product_type": m.product_type,
        "media_type": m.media_type,
        "taken_at": m.taken_at,
        **{k: getattr(m, k) for k in _MEDIA_MUTABLE},
        "first_seen_at": now,
        "missing_since": None,
        "missing_passes": 0,
    }
    if m.video_url:
        values["video_url"] = m.video_url
        values["video_url_seen_at"] = now
    stmt = insert(Media).values(**values)
    update_cols = [*_MEDIA_MUTABLE, "missing_since", "missing_passes", "shortcode"]
    if m.video_url:
        update_cols += ["video_url", "video_url_seen_at"]
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Media.media_pk], set_={k: stmt.excluded[k] for k in update_cols}
        )
    )
    caption_changed = old_caption is None or old_caption[0] != m.caption
    return is_new, caption_changed


async def replace_signals(session: AsyncSession, media_pk: int, signals: list[Signal]) -> None:
    """Сигналы пересчитываются целиком при первом появлении ролика и при смене подписи."""
    await session.execute(delete(MediaSignal).where(MediaSignal.media_pk == media_pk))
    if signals:
        await session.execute(
            insert(MediaSignal).values(
                [
                    {
                        "media_pk": media_pk,
                        "kind": s.kind,
                        "value": s.value,
                        "confidence": s.confidence,
                    }
                    for s in signals
                ]
            )
        )


async def previous_snapshot(
    session: AsyncSession, media_pk: int, before: date
) -> PrevSnapshot | None:
    row = (
        await session.execute(
            select(MetricSnapshot.snapshot_date, MetricSnapshot.play_count)
            .where(MetricSnapshot.media_pk == media_pk, MetricSnapshot.snapshot_date < before)
            .order_by(MetricSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).first()
    return PrevSnapshot(row[0], row[1]) if row else None


async def write_metrics(
    session: AsyncSession,
    x: IgMetrics,
    verdict: Verdict,
    *,
    snapshot_date: date,
    source: str,
    raw_response_id: int,
) -> str:
    """Снимок (один на ролик в сутки, последний побеждает) или карантин."""
    if verdict.action == Action.INVALID:
        raise ValueError("invalid verdict must abort the whole response before writing")
    if x.play_count is None:
        return "skipped"
    values: dict[str, Any] = {
        "media_pk": x.media_pk,
        "snapshot_date": snapshot_date,
        "captured_at": x.captured_at,
        "play_count": x.play_count,
        "like_count": x.like_count,
        "comment_count": x.comment_count,
        "reshare_count": x.reshare_count,
        "likes_hidden": x.likes_hidden,
        "comments_disabled": x.comments_disabled,
        "flags": verdict.flags,
        "source": source,
        "raw_response_id": raw_response_id,
    }
    if verdict.action == Action.QUARANTINE:
        session.add(MetricQuarantine(**values, reason=verdict.reason or "unknown"))
        return "quarantined"
    stmt = insert(MetricSnapshot).values(**values)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["media_pk", "snapshot_date"],
            set_={k: stmt.excluded[k] for k in values if k not in ("media_pk", "snapshot_date")},
        )
    )
    return "written"
