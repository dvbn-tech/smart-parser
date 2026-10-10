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
def seed_demo(
    force: Annotated[bool, typer.Option(help="стереть и реальные данные")] = False,
) -> None:
    """Заполнить базу демо-данными (стирает текущие данные!) и пересчитать всплески."""
    from sqlalchemy import text

    from parser.demo import seed_demo as seed

    async def run() -> None:
        async with session_scope() as session:
            real = await session.scalar(
                text("SELECT count(*) FROM account WHERE username NOT LIKE 'demo\\_%'")
            )
            queued = await session.scalar(
                text("SELECT count(*) FROM scrape_task WHERE username IS NOT NULL")
            )
            if (real or queued) and not force:
                typer.echo(
                    f"В базе реальные данные ({real} аккаунтов, {queued} задач по никам). "
                    "Демо их сотрёт — запустите с --force, если это точно нужно."
                )
                raise typer.Exit(1)
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
    types: Annotated[str | None, typer.Option(help="только эти типы задач, через запятую")] = None,
) -> None:
    """Воркер: выполняет задачи из очереди. Источник — SP_SOURCE: graph (по умолчанию) или web."""
    from contextlib import asynccontextmanager

    from parser.raw.store import RawStore
    from parser.sources.graph import GraphApiSource
    from parser.sources.web import WebSource
    from parser.worker import work as run_work

    settings = get_settings()

    @asynccontextmanager
    async def source(session_id: str):  # type: ignore[no-untyped-def]
        if settings.source == "graph":
            async with GraphApiSource(settings) as g:
                yield g
        else:
            async with WebSource(settings, session_id=session_id) as w:
                yield w

    async def run() -> None:
        raw = RawStore(settings)
        await raw.ensure_bucket()
        type_list = [t.strip() for t in types.split(",")] if types else None
        for r in await run_work(
            settings, source, raw, once=once, max_tasks=max_tasks, types=type_list
        ):
            typer.echo(r)

    asyncio.run(run())


@app.command("plan")
def plan_cmd(slot: Annotated[str, typer.Argument(help="night | day | tagged")]) -> None:
    """Поставить задачи суточного цикла (запускать по cron: 01:00, 10:00, 14:00 МСК)."""
    from datetime import UTC, datetime

    from parser.planner import plan

    async def run() -> None:
        async with session_scope() as session:
            typer.echo(await plan(session, slot, datetime.now(UTC), get_settings().source))

    asyncio.run(run())


@app.command("import-lists")
def import_lists(
    path: Annotated[Path, typer.Argument(help="таблица заказчика .xlsx")],
    dry_run: Annotated[bool, typer.Option(help="только отчёт, без записи")] = False,
    report: Annotated[Path, typer.Option(help="куда записать отчёт")] = Path(
        "docs/import_report.md"
    ),
    replace_demo: Annotated[bool, typer.Option(help="сначала убрать демо-данные")] = False,
) -> None:
    """Импорт брендов, креаторов, масок ников и артикулов из таблицы заказчика."""
    from sqlalchemy import text

    from parser.importers.customer_xlsx import apply_plan, plan_summary, read_workbook

    plan = read_workbook(path)
    summary = plan_summary(plan)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(summary)
    typer.echo(summary)
    if dry_run:
        return

    async def run() -> None:
        async with session_scope() as session:
            demo = await session.scalar(
                text("SELECT count(*) FROM account WHERE username LIKE 'demo\\_%'")
            )
            if demo and not replace_demo:
                typer.echo(
                    f"В базе {demo} демо-аккаунтов. Запустите с --replace-demo, чтобы убрать их перед импортом."
                )
                raise typer.Exit(1)
            if demo:
                real = await session.scalar(
                    text("SELECT count(*) FROM account WHERE username NOT LIKE 'demo\\_%'")
                )
                if real:
                    typer.echo(
                        "В базе вперемешку демо и реальные данные — убирать автоматически не будем."
                    )
                    raise typer.Exit(1)
                await session.execute(
                    text(
                        "TRUNCATE metric_snapshot, metric_quarantine, media_signal, media_brand, media_stats,"
                        " media_daily_views, account_stats, media, account_snapshot, account_username_history,"
                        " brand_article, brand_account, brand, account, scrape_task, raw_response,"
                        " shape_fingerprint RESTART IDENTITY CASCADE"
                    )
                )
                await session.commit()
                typer.echo("Демо-данные удалены.")
            typer.echo(await apply_plan(session, plan))

    asyncio.run(run())


@app.command("meta-check")
def meta_check(
    username: Annotated[str, typer.Option(help="чей профиль запросить для проверки")] = "instagram",
) -> None:
    """Проверить настройку Graph API: токен, права, бизнес-аккаунт и один запрос Business Discovery."""
    import httpx

    s = get_settings()
    if not s.meta_access_token or not s.meta_ig_user_id:
        typer.echo(
            "Нет SP_META_ACCESS_TOKEN или SP_META_IG_USER_ID в .env — см. docs/META_SETUP.md"
        )
        raise typer.Exit(1)
    base = f"https://graph.facebook.com/{s.meta_graph_version}"
    with httpx.Client(timeout=30) as c:
        me = c.get(
            f"{base}/{s.meta_ig_user_id}",
            params={
                "fields": "username,followers_count,media_count",
                "access_token": s.meta_access_token,
            },
        ).json()
        typer.echo(f"бизнес-аккаунт: {me}")
        perms = c.get(f"{base}/me/permissions", params={"access_token": s.meta_access_token}).json()
        granted = sorted(
            p["permission"] for p in perms.get("data", []) if p.get("status") == "granted"
        )
        typer.echo(f"права: {', '.join(granted) or perms}")
        need = {"instagram_basic", "pages_read_engagement"}
        if not need <= set(granted):
            typer.echo(f"не хватает прав: {', '.join(sorted(need - set(granted)))}")
        if s.meta_app_id and s.meta_app_secret:
            dbg = (
                c.get(
                    f"{base}/debug_token",
                    params={
                        "input_token": s.meta_access_token,
                        "access_token": f"{s.meta_app_id}|{s.meta_app_secret}",
                    },
                )
                .json()
                .get("data", {})
            )
            exp = dbg.get("data_access_expires_at") or dbg.get("expires_at")
            typer.echo(f"токен действителен: {dbg.get('is_valid')}, истекает (unix): {exp}")
        bd = c.get(
            f"{base}/{s.meta_ig_user_id}",
            params={
                "fields": f"business_discovery.username({username}){{username,followers_count,media_count,media.limit(3){{shortcode,media_product_type,view_count,like_count}}}}",
                "access_token": s.meta_access_token,
            },
        ).json()
        typer.echo(f"Business Discovery @{username}: {bd}")


@app.command("meta-token")
def meta_token(
    short_token: Annotated[str, typer.Argument(help="короткий токен из Graph API Explorer")],
    save: Annotated[bool, typer.Option(help="записать токен и id в .env")] = False,
) -> None:
    """Обменять короткий токен на долгоживущий (60 дней) и найти id бизнес-аккаунта Instagram."""
    import httpx

    s = get_settings()
    if not s.meta_app_id or not s.meta_app_secret:
        typer.echo(
            "Нужны SP_META_APP_ID и SP_META_APP_SECRET в .env (Настройки приложения → Основное)"
        )
        raise typer.Exit(1)
    base = f"https://graph.facebook.com/{s.meta_graph_version}"
    with httpx.Client(timeout=30) as c:
        r = c.get(
            f"{base}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": s.meta_app_id,
                "client_secret": s.meta_app_secret,
                "fb_exchange_token": short_token,
            },
        ).json()
        token = r.get("access_token")
        if not token:
            typer.echo(f"Не удалось обменять токен: {r}")
            raise typer.Exit(1)
        pages = c.get(
            f"{base}/me/accounts",
            params={
                "fields": "name,instagram_business_account{id,username}",
                "access_token": token,
            },
        ).json()
    ig = [
        (p["name"], p["instagram_business_account"])
        for p in pages.get("data", [])
        if p.get("instagram_business_account")
    ]
    if not ig:
        typer.echo(f"Нет страницы Facebook с привязанным бизнес-аккаунтом Instagram: {pages}")
        raise typer.Exit(1)
    for page_name, acc in ig:
        typer.echo(f"страница «{page_name}» → Instagram @{acc.get('username')} id={acc['id']}")
    ig_id = ig[0][1]["id"]
    typer.echo(f"долгоживущий токен получен (действует ~60 дней), id бизнес-аккаунта: {ig_id}")
    if save:
        env = Path(".env")
        old = env.read_text().splitlines() if env.exists() else []
        keys = ("SP_META_ACCESS_TOKEN=", "SP_META_IG_USER_ID=")
        lines = [ln for ln in old if not ln.startswith(keys)]
        lines += [f"SP_META_ACCESS_TOKEN={token}", f"SP_META_IG_USER_ID={ig_id}"]
        env.write_text("\n".join(lines) + "\n")
        typer.echo("записано в .env")
    else:
        typer.echo(
            "Добавьте в .env строки SP_META_ACCESS_TOKEN и SP_META_IG_USER_ID (или запустите с --save)"
        )


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
