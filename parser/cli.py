"""Командная строка парсера (управление без UI, ТЗ §2)."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from core.config import get_settings
from core.db.session import session_scope
from core.metrics.recompute import recompute_all

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def poc(
    accounts: Annotated[Path, typer.Option(help="файл: один ник или ссылка на строку")],
    out: Annotated[Path, typer.Option(help="каталог для ответов и отчёта")] = Path("poc_out"),
    max_pages: Annotated[int, typer.Option(help="страниц ленты на аккаунт")] = 200,
    brand_query: Annotated[str | None, typer.Option(help="запрос для пробы поиска")] = None,
) -> None:
    """PoC: профиль и вся лента Reels без логина, отчёт go / no-go."""
    from parser.poc import run_poc

    usernames = [u for line in accounts.read_text().splitlines() if (u := normalize_username(line))]
    report = asyncio.run(
        run_poc(get_settings(), usernames, out, max_pages=max_pages, brand_query=brand_query)
    )
    typer.echo(report.read_text())


@app.command("seed-demo")
def seed_demo() -> None:
    """Заполнить базу демо-данными (стирает текущие данные!) и пересчитать всплески."""
    from parser.demo import seed_demo as seed

    async def run() -> None:
        async with session_scope() as session:
            typer.echo(await seed(session))
            typer.echo(await recompute_all(session))

    asyncio.run(run())


@app.command()
def recompute() -> None:
    """Ночной пересчёт: связи ролик–бренд и всплески."""

    async def run() -> None:
        async with session_scope() as session:
            typer.echo(await recompute_all(session))

    asyncio.run(run())


@app.command()
def work(
    once: Annotated[bool, typer.Option(help="выйти, когда очередь опустеет")] = False,
    max_tasks: Annotated[int | None, typer.Option(help="выполнить не больше N задач")] = None,
) -> None:
    """Воркер: выполняет задачи из очереди (запросы к Instagram через WebSource)."""
    from contextlib import asynccontextmanager

    from parser.raw.store import RawStore
    from parser.sources.web import WebSource
    from parser.worker import work as run_work

    settings = get_settings()

    @asynccontextmanager
    async def source(session_id: str):  # type: ignore[no-untyped-def]
        async with WebSource(settings, session_id=session_id) as src:
            yield src

    async def run() -> None:
        raw = RawStore(settings)
        await raw.ensure_bucket()
        for r in await run_work(settings, source, raw, once=once, max_tasks=max_tasks):
            typer.echo(r)

    asyncio.run(run())


@app.command("plan")
def plan_cmd(slot: Annotated[str, typer.Argument(help="night | day | tagged")]) -> None:
    """Поставить задачи суточного цикла (запускать по cron: 01:00, 10:00, 14:00 МСК)."""
    from datetime import UTC, datetime

    from parser.planner import plan

    async def run() -> None:
        async with session_scope() as session:
            typer.echo(await plan(session, slot, datetime.now(UTC)))

    asyncio.run(run())


def normalize_username(value: str) -> str | None:
    """`https://www.instagram.com/Name/?hl=ru`, `@Name`, `name` → `name`."""
    v = value.strip()
    if not v or v.startswith("#"):
        return None
    if "instagram.com/" in v:
        v = v.split("instagram.com/", 1)[1]
    v = v.split("?", 1)[0].strip("/").split("/", 1)[0]
    return v.lstrip("@").lower() or None


if __name__ == "__main__":
    app()
