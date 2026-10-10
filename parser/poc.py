"""PoC (этап 1): что Instagram отдаёт без логина и на какую глубину.

Критерии go (продуктовая спецификация, «PoC»): play_count есть у ≥ 95% роликов;
пагинация достаёт ≥ 90% истории аккаунта; ≥ 98% успешных запросов.

Все ответы сохраняются как есть в каталог out/raw — из них собирается
библиотека записанных ответов для тестов. При стене логина, капче или 429
ничего не обходим: аккаунт останавливается, после нескольких блокировок
подряд останавливается весь прогон.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from core.config import Settings
from parser.parse.classify import Outcome
from parser.parse.errors import InvalidResponse
from parser.parse.profile import is_profile_not_found
from parser.raw.fingerprint import fingerprint
from parser.sources.base import RawPage
from parser.sources.web import WebSource

MAX_CONSECUTIVE_BLOCKS = 3


@dataclass
class AccountResult:
    username: str
    user_pk: int | None = None
    status: str = "pending"
    media_count: int | None = None
    reels_endpoint: str | None = None
    pages: int = 0
    reels: int = 0
    non_reels: int = 0
    with_play_count: int = 0
    pinned: int = 0
    reached_end: bool = False
    oldest_taken_at: str | None = None
    error: str | None = None


@dataclass
class PocRun:
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    outcomes: Counter[str] = field(default_factory=Counter)
    invalid: int = 0
    bytes: int = 0
    seconds: float = 0.0
    fingerprints: dict[str, set[str]] = field(default_factory=dict)
    accounts: list[AccountResult] = field(default_factory=list)
    probes: dict[str, str] = field(default_factory=dict)
    aborted: str | None = None


class Blocked(Exception):
    pass


class Poc:
    def __init__(self, settings: Settings, out_dir: Path, max_pages: int) -> None:
        self.settings = settings
        self.out = out_dir
        self.max_pages = max_pages
        self.run = PocRun()
        self._consecutive_blocks = 0

    def _record(self, page: RawPage, label: str, n: int) -> Any:
        """Сохранить ответ как есть до разбора и учесть его в статистике."""
        path = self.out / "raw" / label / f"{n:04d}-{page.request_kind}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(page.body)
        meta = {
            "url": page.url,
            "status": page.http_status,
            "location": page.location,
            "received_at": page.received_at.isoformat(),
            "elapsed_s": round(page.elapsed_s, 3),
        }
        path.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))

        outcome = page.outcome
        self.run.outcomes[f"{page.request_kind}:{outcome}"] += 1
        self.run.bytes += len(page.body)
        self.run.seconds += page.elapsed_s
        body = page.json()
        if isinstance(body, dict):
            self.run.fingerprints.setdefault(page.request_kind, set()).add(fingerprint(body))

        if outcome in (Outcome.RATE_LIMITED, Outcome.LOGIN_WALL):
            self._consecutive_blocks += 1
            if self._consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
                self.run.aborted = f"{MAX_CONSECUTIVE_BLOCKS} blocks in a row ({outcome})"
            raise Blocked(str(outcome))
        self._consecutive_blocks = 0
        return body

    async def account(self, src: WebSource, username: str) -> AccountResult:
        res = AccountResult(username=username)
        self.run.accounts.append(res)
        try:
            page = await src.fetch_profile(username)
            body = self._record(page, username, 0)
            if page.outcome == Outcome.NOT_FOUND or is_profile_not_found(body):
                res.status = "not_found"
                return res
            profile = src.parse_profile(page)
            res.user_pk, res.media_count = profile.user_pk, profile.media_count
            if profile.is_private:
                res.status = "private"
                return res
            await self._reels(src, res, profile.user_pk)
            res.status = "ok"
        except Blocked as e:
            res.status, res.error = "blocked", str(e)
        except InvalidResponse as e:
            self.run.invalid += 1
            res.status, res.error = "invalid", str(e)
        return res

    async def _reels(self, src: WebSource, res: AccountResult, user_pk: int) -> None:
        fetchers = {"clips/user": src.fetch_reels, "feed/user": src.fetch_feed}
        for endpoint, fetch in fetchers.items():
            first = await fetch(user_pk, None)
            self._record(first, res.username, 1)
            if first.outcome != Outcome.OK:
                continue
            try:
                parsed = src.parse_reels(first)
            except InvalidResponse as e:
                self.run.invalid += 1
                res.error = f"{endpoint}: {e}"
                continue
            res.reels_endpoint = endpoint
            self._count(res, parsed.items)
            cursor, n = parsed.next_cursor, 1
            while cursor and n < self.max_pages:
                n += 1
                page = await fetch(user_pk, cursor)
                self._record(page, res.username, n)
                parsed = src.parse_reels(page)
                self._count(res, parsed.items)
                cursor = parsed.next_cursor
            res.pages = n
            res.reached_end = cursor is None
            return
        res.error = res.error or "no reels endpoint answered without login"

    @staticmethod
    def _count(res: AccountResult, items: list[Any]) -> None:
        for it in items:
            if it.media.is_reel:
                res.reels += 1
                res.with_play_count += it.metrics.play_count is not None
            else:
                res.non_reels += 1
            res.pinned += it.media.is_pinned
            taken = it.media.taken_at.isoformat()
            if res.oldest_taken_at is None or taken < res.oldest_taken_at:
                res.oldest_taken_at = taken

    async def probes(self, src: WebSource, brand_query: str | None) -> None:
        """Отметки бренда и поиск по упоминанию — доступны ли без логина."""
        ok = [a for a in self.run.accounts if a.user_pk]
        if ok:
            try:
                page = await src.fetch_tagged(ok[0].user_pk or 0, None)
                self._record(page, "_probe", 1)
                self.run.probes["tagged"] = f"{page.http_status} {page.outcome}"
            except Blocked as e:
                self.run.probes["tagged"] = f"blocked: {e}"
        if brand_query:
            try:
                page = await src.search(brand_query)
                self._record(page, "_probe", 2)
                body = page.json()
                users = len(body.get("users", [])) if isinstance(body, dict) else 0
                self.run.probes["search"] = f"{page.http_status} {page.outcome}, users={users}"
            except Blocked as e:
                self.run.probes["search"] = f"blocked: {e}"

    def report(self) -> str:
        r = self.run
        total = sum(r.outcomes.values())
        ok = sum(v for k, v in r.outcomes.items() if k.endswith(":ok"))
        reels = sum(a.reels for a in r.accounts)
        with_play = sum(a.with_play_count for a in r.accounts)
        lines = [
            f"# Отчёт PoC — {r.started_at}",
            "",
            "## Критерии go / no-go",
            "",
            "| Критерий | Порог | Факт |",
            "|---|---|---|",
            f"| play_count у роликов | ≥ 95% | {_pct(with_play, reels)} ({with_play}/{reels}) |",
            f"| успешные запросы | ≥ 98% | {_pct(ok, total)} ({ok}/{total}) |",
            "| глубина истории | ≥ 90% | см. таблицу аккаунтов: дошли ли до конца ленты |",
            "",
            f"Трафик: {r.bytes / 1024:.0f} КБ, время в запросах: {r.seconds:.0f} с, "
            f"невалидных ответов: {r.invalid}",
        ]
        if r.aborted:
            lines += ["", f"**Прогон остановлен:** {r.aborted}"]
        lines += [
            "",
            "## Аккаунты",
            "",
            "| ник | user_pk | статус | постов | эндпоинт | страниц | Reels | play_count | "
            "до конца | самый старый | ошибка |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for a in r.accounts:
            lines.append(
                f"| {a.username} | {a.user_pk or ''} | {a.status} | {a.media_count or ''} | "
                f"{a.reels_endpoint or ''} | {a.pages} | {a.reels} | {a.with_play_count} | "
                f"{'да' if a.reached_end else 'нет'} | {(a.oldest_taken_at or '')[:10]} | "
                f"{a.error or ''} |"
            )
        lines += ["", "## Исходы запросов", ""]
        lines += [f"- `{k}`: {v}" for k, v in sorted(r.outcomes.items())]
        lines += ["", "## Пробы", ""]
        lines += [f"- {k}: {v}" for k, v in r.probes.items()] or ["- не выполнялись"]
        lines += ["", "## Отпечатки структуры", ""]
        lines += [f"- {k}: {', '.join(sorted(v))}" for k, v in r.fingerprints.items()]
        return "\n".join(lines) + "\n"


def _pct(a: int, b: int) -> str:
    return f"{a / b:.1%}" if b else "—"


async def run_poc(
    settings: Settings,
    usernames: list[str],
    out_dir: Path,
    *,
    max_pages: int,
    brand_query: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Path:
    poc = Poc(settings, out_dir, max_pages)
    async with WebSource(settings, transport=transport) as src:
        for username in usernames:
            if poc.run.aborted:
                break
            await poc.account(src, username)
        if not poc.run.aborted:
            await poc.probes(src, brand_query)
    return _write_report(out_dir, poc.report())


def _write_report(out_dir: Path, text: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "poc_report.md"
    report.write_text(text)
    return report
