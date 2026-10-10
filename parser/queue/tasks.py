"""Очередь задач на таблице scrape_task (техспека §4, Ф-7).

PostgreSQL — источник истины, Redis — только транспорт: после потери Redis
или падения воркера очередь восстанавливается из таблицы.

- Приоритеты P0 > P1 > P2 > P3, внутри — по времени постановки; ≥ 20% слотов
  воркеров берут только низшие приоритеты (P2–P3), чтобы те не голодали.
- Один аккаунт — одна задача за раз (advisory lock по user_pk при взятии +
  проверка живой аренды).
- Ключ идемпотентности type:user_pk:окно — повторная постановка игнорируется.
- Аренда 10 мин с продлением на каждой странице; курсор пишется после страницы.
"""

import random
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import ScrapeTask

LEASE = timedelta(minutes=10)
RETRY_DELAYS_MIN = (1, 5, 20, 60, 180)
RETRY_JITTER = 0.2
MAX_ATTEMPTS = len(RETRY_DELAYS_MIN) + 1  # первая попытка + 5 повторов


class Priority(IntEnum):
    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3


class TaskType(StrEnum):
    MANUAL_REFRESH = "manual_refresh"
    BACKFILL = "backfill"
    PROFILE = "profile"
    FEED_HEAD = "feed_head"
    FEED_DEEP = "feed_deep"
    MEDIA_COVER = "media_cover"
    BRAND_TAGGED = "brand_tagged"
    CANDIDATE_PROBE = "candidate_probe"
    REPARSE = "reparse"
    CANARY = "canary"


DEFAULT_PRIORITY = {
    TaskType.MANUAL_REFRESH: Priority.P0,
    TaskType.BACKFILL: Priority.P1,
    TaskType.REPARSE: Priority.P1,
    TaskType.PROFILE: Priority.P2,
    TaskType.FEED_HEAD: Priority.P2,
    TaskType.MEDIA_COVER: Priority.P2,
    TaskType.CANARY: Priority.P0,
    TaskType.FEED_DEEP: Priority.P3,
    TaskType.BRAND_TAGGED: Priority.P3,
    TaskType.CANDIDATE_PROBE: Priority.P3,
}


def idempotency_key(task_type: TaskType, subject: int | str, window: str) -> str:
    """Напр. feed_head:4601217:2026-10-04T01."""
    return f"{task_type}:{subject}:{window}"


def retry_delay(attempt: int, rng: random.Random | None = None) -> timedelta | None:
    """Пауза после неудачной попытки №attempt: 1/5/20/60/180 мин ±20%; None — попытки исчерпаны."""
    if attempt >= MAX_ATTEMPTS:
        return None
    base = RETRY_DELAYS_MIN[max(attempt, 1) - 1] * 60
    jitter = (rng or random).uniform(-RETRY_JITTER, RETRY_JITTER)
    return timedelta(seconds=base * (1 + jitter))


async def enqueue(
    session: AsyncSession,
    task_type: TaskType,
    *,
    window: str,
    user_pk: int | None = None,
    username: str | None = None,
    priority: Priority | None = None,
    run_after: datetime | None = None,
    payload: dict[str, Any] | None = None,
) -> int | None:
    """Поставить задачу. Возвращает id или None, если такая уже стоит (идемпотентность)."""
    subject = user_pk if user_pk is not None else username
    if subject is None:
        raise ValueError("task needs user_pk or username")
    values: dict[str, Any] = {
        "type": str(task_type),
        "user_pk": user_pk,
        "username": username,
        "priority": int(priority if priority is not None else DEFAULT_PRIORITY[task_type]),
        "idempotency_key": idempotency_key(task_type, subject, window),
        "status": "pending",
        "payload": payload or {},
    }
    if run_after is not None:
        values["run_after"] = run_after
    stmt = (
        insert(ScrapeTask)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(ScrapeTask.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


_CLAIM = text(
    """
    UPDATE scrape_task t
       SET status = 'running',
           attempts = t.attempts + 1,
           lease_until = now() + make_interval(secs => :lease_s)
     WHERE t.id = (
        SELECT c.id FROM scrape_task c
         WHERE c.status IN ('pending', 'retry', 'deferred')
           AND c.run_after <= now()
           AND c.priority >= :min_priority
           AND (CAST(:types AS text[]) IS NULL OR c.type = ANY(CAST(:types AS text[])))
           AND (c.user_pk IS NULL OR (
                NOT EXISTS (
                    SELECT 1 FROM scrape_task r
                     WHERE r.user_pk = c.user_pk AND r.status = 'running'
                       AND r.lease_until > now())
                AND pg_try_advisory_xact_lock(c.user_pk)))
         ORDER BY c.priority, c.run_after, c.id
         LIMIT 1
         FOR UPDATE SKIP LOCKED)
    RETURNING t.id
    """
)


async def claim(
    session: AsyncSession, *, low_priority_slot: bool = False, types: list[str] | None = None
) -> ScrapeTask | None:
    """Взять следующую задачу. Слоты низшего приоритета берут только P2–P3."""
    min_priority = Priority.P2 if low_priority_slot else Priority.P0
    task_id = (
        await session.execute(
            _CLAIM,
            {"lease_s": LEASE.total_seconds(), "min_priority": int(min_priority), "types": types},
        )
    ).scalar_one_or_none()
    if task_id is None:
        return None
    return await session.get(ScrapeTask, task_id, populate_existing=True)


async def heartbeat(session: AsyncSession, task_id: int, *, cursor: str | None) -> None:
    """После каждой страницы: курсор и продление аренды."""
    await session.execute(
        text(
            "UPDATE scrape_task SET cursor = :cursor, pages_done = pages_done + 1,"
            " lease_until = now() + make_interval(secs => :lease_s) WHERE id = :id"
        ),
        {"cursor": cursor, "lease_s": LEASE.total_seconds(), "id": task_id},
    )


async def succeed(session: AsyncSession, task_id: int) -> None:
    await session.execute(
        text(
            "UPDATE scrape_task SET status = 'succeeded', finished_at = now(),"
            " lease_until = NULL, last_error = NULL WHERE id = :id"
        ),
        {"id": task_id},
    )


async def fail_or_retry(session: AsyncSession, task: ScrapeTask, error: str) -> str:
    """Временная ошибка: повтор по расписанию, курсор сохраняется."""
    delay = retry_delay(task.attempts)
    if delay is None:
        return await fail(session, task.id, error)
    await session.execute(
        text(
            "UPDATE scrape_task SET status = 'retry', lease_until = NULL, last_error = :err,"
            " run_after = now() + make_interval(secs => :delay) WHERE id = :id"
        ),
        {"err": error, "delay": delay.total_seconds(), "id": task.id},
    )
    return "retry"


async def fail(session: AsyncSession, task_id: int, error: str) -> str:
    """Непонятный ответ или исчерпаны попытки — без повторов."""
    await session.execute(
        text(
            "UPDATE scrape_task SET status = 'failed', finished_at = now(), lease_until = NULL,"
            " last_error = :err WHERE id = :id"
        ),
        {"err": error, "id": task_id},
    )
    return "failed"


async def defer(session: AsyncSession, task_id: int, until: datetime, reason: str) -> None:
    """Блокировка (429, стена логина): отложить без траты попытки."""
    await session.execute(
        text(
            "UPDATE scrape_task SET status = 'deferred', attempts = greatest(attempts - 1, 0),"
            " lease_until = NULL, last_error = :err, run_after = :until WHERE id = :id"
        ),
        {"err": reason, "until": until, "id": task_id},
    )


async def recover_expired_leases(session: AsyncSession) -> int:
    """Истёкшая аренда = упавший воркер: задача возвращается в очередь с курсором."""
    result = await session.execute(
        text(
            "UPDATE scrape_task SET status = 'retry', lease_until = NULL,"
            " last_error = 'lease expired' WHERE status = 'running' AND lease_until < now()"
        )
    )
    return int(result.rowcount)  # type: ignore[attr-defined]
