"""Командная строка парсера (управление без UI, ТЗ §2)."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from core.config import get_settings

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
