"""Воркер: берёт задачи из очереди и выполняет их по одной (техспека §4).

Перед каждой задачей возвращает в очередь задачи с истёкшей арендой (упавший
воркер). Каждый пятый слот берёт только P2–P3, чтобы фоновые задачи не голодали.
Одна задача — одна sticky-сессия прокси на все её страницы.
"""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import structlog

from core.config import Settings
from core.db.session import session_scope
from parser.pipeline import RawSink, Runner, Source, describe
from parser.queue import tasks as q

log = structlog.get_logger()
LOW_PRIORITY_EVERY = 5  # 20% слотов — низшим приоритетам
# Предохранитель: столько блокировок подряд (429, стена логина) — воркер останавливается.
# Не обходим защиту, а прекращаем нагрузку (техспека §6).
MAX_CONSECUTIVE_BLOCKS = 3

SourceFactory = Callable[[str], AbstractAsyncContextManager[Source]]


async def work(
    settings: Settings,
    source_factory: SourceFactory,
    raw: RawSink,
    *,
    once: bool = False,
    max_tasks: int | None = None,
    idle_sleep_s: float = 5.0,
    types: list[str] | None = None,
) -> list[dict[str, Any]]:
    done: list[dict[str, Any]] = []
    slot = 0
    blocks = 0
    while max_tasks is None or len(done) < max_tasks:
        async with session_scope() as s:
            await q.recover_expired_leases(s)
            await s.commit()
            low = slot % LOW_PRIORITY_EVERY == LOW_PRIORITY_EVERY - 1
            task = await q.claim(s, low_priority_slot=low, types=types)
            if task is None and low:
                task = await q.claim(s, types=types)
            await s.commit()
            slot += 1
            if task is None:
                if once:
                    break
                await asyncio.sleep(idle_sleep_s)
                continue
            async with source_factory(f"task{task.id}") as src:
                runner = Runner(s, src, raw, settings)
                status = await runner.run(task)
            result = {
                "task_id": task.id,
                "type": task.type,
                "user_pk": task.user_pk,
                "status": status,
                **describe(runner.stats),
            }
            log.info("task_done", **result)
            done.append(result)
            if status == "auth_error":
                log.error(
                    "meta_auth_error",
                    hint="проверьте SP_META_ACCESS_TOKEN: smart-parser meta-check",
                )
                break
            blocks = blocks + 1 if status == "deferred" else 0
            if blocks >= MAX_CONSECUTIVE_BLOCKS:
                log.warning("circuit_breaker_open", consecutive_blocks=blocks)
                break
    return done
