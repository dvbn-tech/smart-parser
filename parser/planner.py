"""Расписание суточного цикла (техспека §4). Запускается по cron:

01:00  plan night   — profile + feed_head всех отслеживаемых,
                        feed_deep для user_pk mod 7 = день недели
10:00  plan tagged  — brand_tagged для брендов с официальным аккаунтом
14:00  plan day     — feed_head, только первая страница
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parser.queue import tasks as q

MSK = ZoneInfo("Europe/Moscow")


async def tracked_accounts(session: AsyncSession) -> list[int]:
    rows = await session.execute(
        text(
            """
            SELECT DISTINCT a.user_pk FROM account a
              JOIN brand_account ba ON ba.user_pk = a.user_pk AND ba.status = 'tracked'
             WHERE a.status IN ('active', 'not_found')
            """
        )
    )
    return [r[0] for r in rows]


async def plan(
    session: AsyncSession, slot: str, now: datetime, source: str = "web"
) -> dict[str, int]:
    """source="graph": один запрос Business Discovery = профиль + 50 последних публикаций
    с просмотрами, поэтому отдельный feed_head не нужен, а отметок бренда API не даёт."""
    msk = now.astimezone(MSK)
    day = msk.date().isoformat()
    created: dict[str, int] = {}

    async def put(task_type: q.TaskType, window: str, **kw: object) -> None:
        if await q.enqueue(session, task_type, window=window, **kw) is not None:  # type: ignore[arg-type]
            created[task_type] = created.get(task_type, 0) + 1

    graph = source == "graph"
    if slot == "night":
        for pk in await tracked_accounts(session):
            await put(q.TaskType.PROFILE, f"{day}T01", user_pk=pk)
            if not graph:
                await put(q.TaskType.FEED_HEAD, f"{day}T01", user_pk=pk)
            if pk % 7 == msk.weekday():
                await put(q.TaskType.FEED_DEEP, day, user_pk=pk)
    elif slot == "day":
        for pk in await tracked_accounts(session):
            if graph:
                await put(q.TaskType.PROFILE, f"{day}T14", user_pk=pk)
            else:
                await put(q.TaskType.FEED_HEAD, f"{day}T14", user_pk=pk, payload={"max_pages": 1})
    elif slot == "tagged":
        if graph:
            await session.commit()
            return created
        rows = await session.execute(text("SELECT id FROM brand WHERE shop_user_pk IS NOT NULL"))
        for (brand_id,) in rows:
            await put(
                q.TaskType.BRAND_TAGGED,
                f"{day}T10",
                user_pk=None,
                username=f"brand{brand_id}",
                payload={"brand_id": brand_id},
            )
    else:
        raise ValueError(f"unknown slot {slot}")
    await session.commit()
    return created
