"""Выполнение задачи парсера (техспека §3): один путь для каждого ответа Instagram.

    запрос → сырой ответ (S3 + raw_response) → классификация → разбор → проверка → запись

Сырой ответ сохраняется и фиксируется в базе ДО разбора: если разбор упал,
ответ остаётся для reparse, а данных из него в базе нет. Данные страницы
пишутся одной транзакцией вместе с курсором, поэтому повтор после падения
воркера продолжает с той же страницы без дублей.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from core.db.models import (
    Account,
    Brand,
    BrandAccount,
    BrandArticle,
    Media,
    RawResponse,
    ScrapeTask,
    ShapeFingerprint,
)
from core.discovery.confidence import (
    BrandRef,
    Evidence,
    collect_evidence,
    link_type,
    score,
    should_resurface,
)
from parser.parse.classify import Outcome
from parser.parse.errors import InvalidResponse
from parser.parse.models import IgMedia, IgProfile, ParsedItem, ReelsPage
from parser.parse.profile import is_profile_not_found, parse_profile_timeline
from parser.queue import tasks as q
from parser.raw.fingerprint import fingerprint, key_paths
from parser.raw.store import raw_key
from parser.signals.extract import extract_signals
from parser.sources.base import RawPage
from parser.store import repo
from parser.validate.metrics import Action, check_snapshot

MSK = ZoneInfo("Europe/Moscow")
FEED_HEAD_WINDOW = timedelta(days=30)
BLOCK_DEFER = timedelta(minutes=30)
NOT_FOUND_TO_DELETED = timedelta(days=3)
MAX_PAGES = {
    q.TaskType.FEED_HEAD: 20,
    q.TaskType.MANUAL_REFRESH: 20,
    q.TaskType.CANDIDATE_PROBE: 2,
    q.TaskType.BRAND_TAGGED: 2,
    q.TaskType.BACKFILL: 2000,
    q.TaskType.FEED_DEEP: 2000,
}


class RawSink(Protocol):
    async def put(self, key: str, body: bytes) -> None: ...


class Source(Protocol):
    name: str

    async def fetch_profile(self, username: str) -> RawPage: ...

    async def fetch_reels(self, user_pk: int, cursor: str | None) -> RawPage: ...

    async def fetch_tagged(self, user_pk: int, cursor: str | None) -> RawPage: ...

    def parse_profile(self, page: RawPage) -> IgProfile: ...

    def parse_reels(self, page: RawPage) -> ReelsPage: ...


class Blocked(Exception):
    """429, стена логина, капча: задача откладывается, не тратя попытку."""


class Transient(Exception):
    """Сеть, таймаут, 5xx: повтор по расписанию."""


@dataclass
class RunStats:
    pages: int = 0
    media: int = 0
    snapshots: int = 0
    quarantined: int = 0
    new_media: int = 0
    log: list[str] = field(default_factory=list)


def snapshot_day(ts: datetime) -> date:
    """Один снимок на ролик в сутки — по московской дате."""
    return ts.astimezone(MSK).date()


class Runner:
    def __init__(
        self,
        session: AsyncSession,
        source: Source,
        raw: RawSink,
        settings: Settings,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.s = session
        self.src = source
        self.raw = raw
        self.settings = settings
        self.now = now
        self.stats = RunStats()

    async def run(self, task: ScrapeTask) -> str:
        """Выполнить задачу и записать её итог. Возвращает новый статус задачи."""
        try:
            handler = self._handlers()[q.TaskType(task.type)]
            await handler(task)
            await q.succeed(self.s, task.id)
            await self.s.commit()
            return "succeeded"
        except Blocked as e:
            await self.s.rollback()
            await q.defer(self.s, task.id, self.now() + BLOCK_DEFER, f"blocked: {e}")
            await self.s.commit()
            return "deferred"
        except InvalidResponse as e:
            await self.s.rollback()
            await q.fail(self.s, task.id, f"invalid response: {e}")
            await self.s.commit()
            return "failed"
        except Exception as e:
            await self.s.rollback()
            fresh = await self.s.get(ScrapeTask, task.id, populate_existing=True)
            status = await q.fail_or_retry(self.s, fresh or task, f"{type(e).__name__}: {e}")
            await self.s.commit()
            return status

    def _handlers(self) -> dict[q.TaskType, Callable[[ScrapeTask], Awaitable[None]]]:
        return {
            q.TaskType.PROFILE: self.profile,
            q.TaskType.FEED_HEAD: self.feed,
            q.TaskType.FEED_DEEP: self.feed,
            q.TaskType.BACKFILL: self.feed,
            q.TaskType.MANUAL_REFRESH: self.manual_refresh,
            q.TaskType.CANDIDATE_PROBE: self.candidate_probe,
            q.TaskType.BRAND_TAGGED: self.brand_tagged,
        }

    # --- сырой ответ ------------------------------------------------------------------

    async def _fetch(
        self, task: ScrapeTask, page_no: int, kind: str, call: Awaitable[RawPage]
    ) -> tuple[RawPage, RawResponse]:
        try:
            page = await call
        except Exception as e:
            raise Transient(f"{kind}: {type(e).__name__}: {e}") from e
        key = raw_key(page.received_at, task.id, page_no, kind)
        await self.raw.put(key, page.body)
        body = page.json()
        fp = fingerprint(body) if isinstance(body, dict) else None
        row = RawResponse(
            task_id=task.id,
            page=page_no,
            request_kind=kind,
            source=self.src.name,
            http_status=page.http_status,
            bytes=len(page.body),
            shape_fingerprint=fp,
            parse_status="pending",
            s3_key=key,
            received_at=page.received_at,
        )
        self.s.add(row)
        await self.s.flush()
        if fp and isinstance(body, dict):
            await self.s.execute(
                insert(ShapeFingerprint)
                .values(
                    fingerprint=fp,
                    request_kind=kind,
                    first_seen_at=page.received_at,
                    sample_raw_response_id=row.id,
                    paths=sorted(key_paths(body)),
                )
                .on_conflict_do_nothing()
            )
        self.stats.pages += 1

        outcome = page.outcome
        if outcome in (Outcome.RATE_LIMITED, Outcome.LOGIN_WALL):
            row.parse_status = "blocked"
            await self.s.commit()
            raise Blocked(f"{kind}: {outcome}")
        if outcome == Outcome.SERVER_ERROR:
            row.parse_status = "error"
            await self.s.commit()
            raise Transient(f"{kind}: HTTP {page.http_status}")
        await self.s.commit()  # ответ зафиксирован до разбора
        return page, row

    async def _invalid(self, row: RawResponse, e: InvalidResponse) -> None:
        await self.s.rollback()
        await self.s.execute(
            update(RawResponse)
            .where(RawResponse.id == row.id)
            .values(parse_status="invalid", parse_error=str(e)[:1000])
        )
        await self.s.commit()

    # --- профиль ----------------------------------------------------------------------

    async def profile(self, task: ScrapeTask) -> None:
        await self._profile(task, page_no=0)

    async def _profile(self, task: ScrapeTask, page_no: int) -> IgProfile | None:
        username = task.username
        if username is None and task.user_pk is not None:
            username = await self.s.scalar(
                select(Account.username).where(Account.user_pk == task.user_pk)
            )
        if not username or username.startswith("#"):
            raise InvalidResponse("task.username", "username is unknown for this account")

        page, row = await self._fetch(task, page_no, "profile", self.src.fetch_profile(username))
        body = page.json()
        if page.outcome == Outcome.NOT_FOUND or is_profile_not_found(body):
            await self._not_found(task, row)
            return None
        try:
            profile = self.src.parse_profile(page)
            timeline = parse_profile_timeline(body, captured_at=page.received_at)
        except InvalidResponse as e:
            await self._invalid(row, e)
            raise

        now = self.now()
        await repo.upsert_account(self.s, profile, now)
        await repo.write_account_snapshot(self.s, profile, snapshot_day(page.received_at), row.id)
        for item in timeline:
            await self._store_item(item, row, partial=True)
        row.parse_status = "ok"
        if task.user_pk is None:
            task.user_pk = profile.user_pk
            await self.s.execute(
                update(ScrapeTask).where(ScrapeTask.id == task.id).values(user_pk=profile.user_pk)
            )
        await self._apply_link(task, profile)
        await self.s.commit()
        return profile

    async def _not_found(self, task: ScrapeTask, row: RawResponse) -> None:
        row.parse_status = "ok"
        if task.user_pk is not None:
            acc = await self.s.get(Account, task.user_pk)
            if acc is not None:
                now = self.now()
                acc.not_found_since = acc.not_found_since or now
                acc.status = (
                    "deleted" if now - acc.not_found_since >= NOT_FOUND_TO_DELETED else "not_found"
                )
        self.stats.log.append("not_found")
        await self.s.commit()

    async def _apply_link(self, task: ScrapeTask, profile: IgProfile) -> None:
        """Аккаунт добавили по нику: после сбора профиля связываем с брендом и ставим историю."""
        link = (task.payload or {}).get("link")
        if not link:
            return
        brand_id, role = int(link["brand_id"]), str(link.get("role", "creator"))
        if role == "shop":
            await self.s.execute(
                update(Brand).where(Brand.id == brand_id).values(shop_user_pk=profile.user_pk)
            )
        extra = {k: link.get(k) for k in ("person_name", "curator", "link_type")}
        await self.s.execute(
            insert(BrandAccount)
            .values(
                brand_id=brand_id,
                user_pk=profile.user_pk,
                role=role,
                status="tracked",
                is_own_creator=bool(link.get("is_own_creator")),
                confidence=1,
                evidence=[],
                all_posts_count_for_brand=role == "creator",
                first_seen=snapshot_day(self.now()),
                **extra,
            )
            .on_conflict_do_update(
                index_elements=["brand_id", "user_pk"],
                set_={"status": "tracked", "role": role, **extra},
            )
        )
        if not profile.is_private:
            await q.enqueue(self.s, q.TaskType.BACKFILL, user_pk=profile.user_pk, window="initial")

    # --- лента ------------------------------------------------------------------------

    async def manual_refresh(self, task: ScrapeTask) -> None:
        profile = await self._profile(task, page_no=0)
        if profile is not None and not profile.is_private:
            await self._feed(task, first_page_no=1, kind=q.TaskType.FEED_HEAD)

    async def feed(self, task: ScrapeTask) -> None:
        await self._feed(task, first_page_no=task.pages_done, kind=q.TaskType(task.type))

    async def _user_pk(self, task: ScrapeTask) -> int:
        if task.user_pk is not None:
            return task.user_pk
        profile = await self._profile(task, page_no=0)
        if profile is None:
            raise InvalidResponse("profile", "account not found")
        return profile.user_pk

    async def _feed(self, task: ScrapeTask, *, first_page_no: int, kind: q.TaskType) -> None:
        user_pk = await self._user_pk(task)
        acc = await self.s.get(Account, user_pk)
        if acc is not None and acc.status in ("private", "deleted", "not_found"):
            self.stats.log.append(f"skip: account {acc.status}")
            return
        # backfill и feed_deep продолжают с сохранённого курсора; feed_head всегда с начала
        resume = kind in (q.TaskType.BACKFILL, q.TaskType.FEED_DEEP)
        cursor = task.cursor if resume else None
        started_fresh = cursor is None
        page_no = first_page_no
        max_pages = int((task.payload or {}).get("max_pages") or MAX_PAGES.get(kind, 20))
        horizon = self.now() - FEED_HEAD_WINDOW
        seen: set[int] = set()
        pages_this_run = 0
        while True:
            page, row = await self._fetch(
                task, page_no, "reels", self.src.fetch_reels(user_pk, cursor)
            )
            try:
                parsed = self.src.parse_reels(page)
                await self._validate_page(parsed)
            except InvalidResponse as e:
                await self._invalid(row, e)
                raise
            for item in parsed.items:
                await self._store_item(item, row)
                seen.add(item.media.media_pk)
            row.parse_status = "ok"
            cursor = parsed.next_cursor
            page_no += 1
            pages_this_run += 1
            # курсор и продление аренды — вместе с данными страницы, одной транзакцией
            await q.heartbeat(self.s, task.id, cursor=cursor)
            await self.s.commit()

            if cursor is None:
                break
            if pages_this_run >= max_pages:
                break
            if kind in (
                q.TaskType.FEED_HEAD,
                q.TaskType.MANUAL_REFRESH,
                q.TaskType.CANDIDATE_PROBE,
            ):
                unpinned = [i for i in parsed.items if not i.media.is_pinned]
                # закреплённые идут первыми независимо от даты — в условии остановки не учитываются
                if unpinned and min(i.media.taken_at for i in unpinned) < horizon:
                    break

        reached_end = cursor is None
        now = self.now()
        if kind == q.TaskType.BACKFILL and reached_end:
            await self.s.execute(
                update(Account).where(Account.user_pk == user_pk).values(backfill_done_at=now)
            )
        if kind == q.TaskType.FEED_DEEP and reached_end and started_fresh:
            await self._mark_missing(user_pk, seen, now)
        await self.s.execute(
            update(Account).where(Account.user_pk == user_pk).values(last_scraped_at=now)
        )
        await self.s.commit()

    async def _validate_page(self, parsed: ReelsPage) -> None:
        """Проверить всю страницу до записи: невалидный снимок делает невалидным весь ответ."""
        for item in parsed.items:
            verdict = check_snapshot(
                item.metrics,
                taken_at=item.media.taken_at,
                is_reel=item.media.is_reel,
                prev=None,
            )
            if verdict.action == Action.INVALID:
                raise InvalidResponse(
                    f"media {item.media.media_pk}", verdict.reason or "invalid metrics"
                )

    async def _store_item(
        self, item: ParsedItem, row: RawResponse, *, partial: bool = False
    ) -> None:
        m, x = item.media, item.metrics
        now = self.now()
        if await self.s.get(Account, m.owner_user_pk) is None:
            await repo.ensure_account_stub(self.s, m.owner_user_pk, m.owner_username)
        is_new, caption_changed = await repo.upsert_media(self.s, m, now, partial=partial)
        if not partial or caption_changed:
            await repo.replace_signals(self.s, m.media_pk, extract_signals(m))
        self.stats.media += 1
        self.stats.new_media += is_new
        if x.play_count is None:
            return
        day = snapshot_day(x.captured_at)
        prev = await repo.previous_snapshot(self.s, m.media_pk, day)
        verdict = check_snapshot(x, taken_at=m.taken_at, is_reel=m.is_reel, prev=prev)
        result = await repo.write_metrics(
            self.s, x, verdict, snapshot_date=day, source=self.src.name, raw_response_id=row.id
        )
        if result == "written":
            self.stats.snapshots += 1
        elif result == "quarantined":
            self.stats.quarantined += 1

    async def _mark_missing(self, user_pk: int, seen: set[int], now: datetime) -> None:
        """Удалённые и скрытые: missing_since — только после двух полных проходов без ролика."""
        await self.s.execute(
            text(
                """
                UPDATE media SET missing_passes = missing_passes + 1,
                       missing_since = CASE WHEN missing_passes + 1 >= 2
                                            THEN coalesce(missing_since, :now)
                                            ELSE missing_since END
                 WHERE owner_user_pk = :u AND NOT (media_pk = ANY(:seen))
                """
            ),
            {"u": user_pk, "seen": list(seen), "now": now},
        )

    # --- поиск креаторов --------------------------------------------------------------

    async def _brand_ref(self, brand_id: int) -> BrandRef:
        brand = await self.s.get(Brand, brand_id)
        if brand is None:
            raise InvalidResponse("payload.brand_id", f"brand {brand_id} not found")
        pks = {brand.shop_user_pk} if brand.shop_user_pk else set()
        names: set[str] = set()
        if pks:
            rows = await self.s.execute(select(Account.username).where(Account.user_pk.in_(pks)))
            names = {r[0] for r in rows}
        articles = await self.s.execute(
            select(BrandArticle.kind, BrandArticle.value).where(BrandArticle.brand_id == brand_id)
        )
        by_kind: dict[str, set[str]] = {"wb": set(), "ww": set()}
        for kind, value in articles:
            by_kind.setdefault(kind, set()).add(value)
        return BrandRef(
            name=brand.name,
            account_pks=frozenset(pks),
            account_usernames=frozenset(names),
            hashtags=frozenset(brand.hashtags),
            wb_articles=frozenset(by_kind["wb"]),
            ww_codes=frozenset(by_kind["ww"]),
            username_masks=tuple(brand.username_masks or ()),
            domains=frozenset(brand.domains or ()),
        )

    async def candidate_probe(self, task: ScrapeTask) -> None:
        """Профиль + 2 страницы ленты кандидата, поиск сигналов бренда (техспека §13)."""
        brand_id = int((task.payload or {}).get("brand_id", 0))
        profile = await self._profile(task, page_no=0)
        if profile is None or profile.is_private:
            return
        await self._feed(task, first_page_no=1, kind=q.TaskType.CANDIDATE_PROBE)
        brand = await self._brand_ref(brand_id)
        rows = (
            await self.s.execute(
                select(Media)
                .where(Media.owner_user_pk == profile.user_pk)
                .order_by(Media.taken_at.desc())
                .limit(60)
            )
        ).scalars()
        medias = [_media_from_row(r) for r in rows]
        found = collect_evidence(brand, profile, medias, self.settings.weights)
        await self._update_candidate(brand_id, profile.user_pk, found)

    async def _update_candidate(self, brand_id: int, user_pk: int, found: list[Evidence]) -> None:
        link = await self.s.get(BrandAccount, (brand_id, user_pk))
        evidence = [e.to_json() for e in found]
        conf = score(found, self.settings.weights)
        if link is None:
            self.s.add(
                BrandAccount(
                    brand_id=brand_id,
                    user_pk=user_pk,
                    role="creator",
                    status="candidate",
                    confidence=conf,
                    evidence=evidence,
                    link_type=link_type(found),
                    first_seen=snapshot_day(self.now()),
                    last_seen=snapshot_day(self.now()),
                )
            )
            return
        old = [Evidence(**e) for e in link.evidence or []]
        if link.status == "hidden" and should_resurface(old, found):
            link.status = "candidate"
            link.hidden_at = None
        if link.status != "tracked":
            link.confidence = conf
            link.evidence = evidence
            link.link_type = link_type(found)
        link.last_seen = snapshot_day(self.now())

    async def _probes_left(self) -> int:
        """Не больше candidate_probe_daily_limit проверок кандидатов в сутки (техспека §13)."""
        used = await self.s.scalar(
            text(
                "SELECT count(*) FROM scrape_task WHERE type = 'candidate_probe'"
                " AND created_at >= date_trunc('day', now())"
            )
        )
        return self.settings.candidate_probe_daily_limit - int(used or 0)

    async def brand_tagged(self, task: ScrapeTask) -> None:
        """Посты с отметкой аккаунта бренда: их авторы — кандидаты в креаторы."""
        brand_id = int((task.payload or {}).get("brand_id", 0))
        brand = await self.s.get(Brand, brand_id)
        if brand is None or brand.shop_user_pk is None:
            raise InvalidResponse("payload.brand_id", "brand has no official account")
        cursor: str | None = None
        for page_no in range(MAX_PAGES[q.TaskType.BRAND_TAGGED]):
            page, row = await self._fetch(
                task, page_no, "tagged", self.src.fetch_tagged(brand.shop_user_pk, cursor)
            )
            try:
                parsed = self.src.parse_reels(page)
            except InvalidResponse as e:
                await self._invalid(row, e)
                raise
            row.parse_status = "ok"
            probes_left = await self._probes_left()
            for item in parsed.items:
                owner = item.media.owner_user_pk
                if owner == brand.shop_user_pk:
                    continue
                await self._store_item(item, row)
                link = await self.s.get(BrandAccount, (brand_id, owner))
                if link is None:
                    ev = [
                        Evidence(
                            "usertag",
                            item.media.media_pk,
                            brand.name,
                            self.settings.weights.usertag,
                        )
                    ]
                    await self._update_candidate(brand_id, owner, ev)
                    if probes_left <= 0:
                        continue  # лимит проверок на сутки: кандидат останется с одной отметкой
                    probes_left -= 1
                    await q.enqueue(
                        self.s,
                        q.TaskType.CANDIDATE_PROBE,
                        user_pk=owner,
                        username=item.media.owner_username,
                        window=f"brand{brand_id}",
                        payload={"brand_id": brand_id},
                    )
            await self.s.commit()
            cursor = parsed.next_cursor
            if cursor is None:
                break


def _media_from_row(r: Media) -> IgMedia:
    return IgMedia(
        media_pk=r.media_pk,
        shortcode=r.shortcode,
        owner_user_pk=r.owner_user_pk,
        product_type=r.product_type,
        media_type=r.media_type,
        taken_at=r.taken_at,
        caption=r.caption,
        duration_s=r.duration_s,
        is_pinned=r.is_pinned,
        coauthors=r.coauthors,
        usertags=r.usertags,
        is_paid_partnership=r.is_paid_partnership,
        sponsor_user_pks=r.sponsor_user_pks,
        audio_id=r.audio_id,
        audio_title=r.audio_title,
        is_original_audio=r.is_original_audio,
        video_url=None,
        cover_url=None,
    )


def describe(stats: RunStats) -> dict[str, Any]:
    return {
        "pages": stats.pages,
        "media": stats.media,
        "new_media": stats.new_media,
        "snapshots": stats.snapshots,
        "quarantined": stats.quarantined,
        "log": stats.log,
    }
