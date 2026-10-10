"""GraphApiSource: официальный Instagram Graph API, функция Business Discovery.

Бизнес-аккаунт заказчика (meta_ig_user_id) запрашивает публичные данные других
бизнес- и авторских аккаунтов по нику: профиль и публикации с просмотрами Reels
(view_count), лайками и комментариями. Личные и закрытые аккаунты API не видит.

Один запрос = профиль + первая страница публикаций (до 50), поэтому ежедневный
цикл — это примерно один запрос на аккаунт.

Отличия от веб-формата, которые учитывает разбор:
  • id аккаунта — id Instagram в Graph API (не тот pk, что в веб-ответах);
  • id ролика берём из shortcode — это тот же media_pk, что в вебе;
  • в подписи Meta вырезает «@» у упоминаний;
  • закреплённых роликов, отметок, соавторов и геометок API не отдаёт.
"""

import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from core.config import Settings
from parser.parse import fields as f
from parser.parse.classify import Outcome
from parser.parse.errors import InvalidResponse
from parser.parse.models import IgMedia, IgMetrics, IgProfile, ParsedItem, ReelsPage
from parser.sources.base import RawPage
from parser.sources.pacing import PACER

GRAPH = "https://graph.facebook.com"
USER_FIELDS = (
    "id,username,name,biography,website,followers_count,follows_count,media_count,"
    "profile_picture_url"
)
MEDIA_FIELDS = (
    "id,shortcode,permalink,caption,timestamp,media_type,media_product_type,media_audio_type,"
    "like_count,comments_count,view_count,thumbnail_url,is_shared_to_feed,alt_text"
)
_SHORTCODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_MEDIA_TYPES = {"VIDEO": "video", "IMAGE": "image", "CAROUSEL_ALBUM": "carousel"}
_PRODUCT_TYPES = {"REELS": "clips", "FEED": "feed", "AD": "ad", "STORY": "story"}

# Коды ошибок Graph API: https://developers.facebook.com/docs/graph-api/guides/error-handling
_RATE_LIMIT_CODES = {4, 17, 32, 613, 80001, 80002}
_AUTH_CODES = {102, 190, 200, 10}


class SourceNotSupported(Exception):
    """Этот тип запроса источник не умеет (например, отметки бренда в Graph API)."""


def shortcode_to_pk(shortcode: str) -> int:
    """Shortcode ролика → media_pk (тот же числовой id, что в веб-ответах Instagram)."""
    pk = 0
    for ch in shortcode[:11]:
        pk = pk * 64 + _SHORTCODE_ALPHABET.index(ch)
    return pk


def graph_outcome(status: int, body: Any) -> Outcome:
    if status == 429:
        return Outcome.RATE_LIMITED
    if status >= 500:
        return Outcome.SERVER_ERROR
    err = body.get("error") if isinstance(body, dict) else None
    if not isinstance(err, dict):
        return Outcome.OK if status < 400 else Outcome.SERVER_ERROR
    code = err.get("code")
    message = str(err.get("message", "")).lower()
    if code in _RATE_LIMIT_CODES or ("limit" in message and "reached" in message):
        return Outcome.RATE_LIMITED
    if code in _AUTH_CODES or (err.get("type") == "OAuthException" and code != 100):
        return Outcome.AUTH_ERROR
    # code 100 / 110: нет такого ника, или аккаунт личный, или ограничен по возрасту
    if code in (100, 110):
        return Outcome.NOT_FOUND
    return Outcome.SERVER_ERROR


class GraphApiSource:
    name = "graph"
    timeline_is_full = True  # ответ профиля уже содержит публикации с метриками
    supports_tagged = False

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if not settings.meta_access_token or not settings.meta_ig_user_id:
            raise RuntimeError(
                "Не настроен Graph API: задайте SP_META_ACCESS_TOKEN и SP_META_IG_USER_ID в .env "
                "(см. docs/META_SETUP.md)"
            )
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=f"{GRAPH}/{settings.meta_graph_version}",
            timeout=httpx.Timeout(settings.read_timeout_s, connect=settings.connect_timeout_s),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "GraphApiSource":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _fields(self, username: str, after: str | None, with_user: bool) -> str:
        media = f"media.limit({self._settings.meta_media_page_size})"
        if after:
            media = f"media.after({after}).limit({self._settings.meta_media_page_size})"
        inner = f"{USER_FIELDS + ',' if with_user else 'id,username,'}{media}{{{MEDIA_FIELDS}}}"
        return f"business_discovery.username({username}){{{inner}}}"

    async def _discover(
        self, kind: str, username: str, after: str | None, with_user: bool
    ) -> RawPage:
        s = self._settings
        await PACER.wait(3600 / s.meta_requests_per_hour, s.meta_requests_per_hour)
        started = time.monotonic()
        try:
            resp = await self._client.get(
                f"/{s.meta_ig_user_id}",
                params={
                    "fields": self._fields(username, after, with_user),
                    "access_token": s.meta_access_token,
                },
            )
        finally:
            PACER.done()
        try:
            body: Any = resp.json()
        except ValueError:
            body = None
        outcome = graph_outcome(resp.status_code, body)
        return RawPage(
            request_kind=kind,
            source=self.name,
            # токен в адрес не попадает: url сохраняется в журналах и отчётах
            url=str(resp.request.url).split("access_token=")[0].rstrip("&?"),
            http_status=resp.status_code,
            body=resp.content,
            received_at=datetime.now(UTC),
            elapsed_s=time.monotonic() - started,
            meta={"outcome": str(outcome), "username": username, "error": _error_text(body)},
        )

    async def fetch_profile(self, username: str) -> RawPage:
        return await self._discover("profile", username, None, with_user=True)

    async def fetch_reels(
        self, user_pk: int, cursor: str | None, username: str | None = None
    ) -> RawPage:
        if not username:
            raise InvalidResponse(
                "task.username", "Graph API ищет аккаунт по нику, а ник неизвестен"
            )
        return await self._discover("reels", username, cursor, with_user=False)

    async def fetch_tagged(self, user_pk: int, cursor: str | None) -> RawPage:
        raise SourceNotSupported("отметки чужого аккаунта в Graph API недоступны")

    def parse_profile(self, page: RawPage) -> IgProfile:
        return parse_discovery_profile(page.json())

    def parse_reels(self, page: RawPage) -> ReelsPage:
        return parse_discovery_media(
            page.json(), captured_at=page.received_at, page_size=self._settings.meta_media_page_size
        )

    def parse_timeline(self, page: RawPage) -> list[ParsedItem]:
        return self.parse_reels(page).items


def _error_text(body: Any) -> str | None:
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        e = body["error"]
        return f"{e.get('code')}/{e.get('error_subcode')}: {e.get('message')}"
    return None


def parse_discovery_profile(raw: Any) -> IgProfile:
    u = f.req_dict(raw, "business_discovery")
    website = f.opt_str(u, "website")
    return IgProfile(
        user_pk=f.req_int(u, "id"),
        username=f.req_str(u, "username").lower(),
        full_name=f.opt_str(u, "name"),
        biography=f.opt_str(u, "biography"),
        external_url=website,
        followers_count=f.req_int(u, "followers_count"),
        following_count=f.req_int(u, "follows_count"),
        media_count=f.req_int(u, "media_count"),
        is_private=False,  # Business Discovery видит только публичные профессиональные аккаунты
        is_verified=False,  # API этого не отдаёт
        is_business=True,
        category=None,
        avatar_url=f.opt_str(u, "profile_picture_url"),
        bio_links=[website] if website else None,
        is_professional=True,
    )


def parse_discovery_media(raw: Any, *, captured_at: datetime, page_size: int) -> ReelsPage:
    u = f.req_dict(raw, "business_discovery")
    owner_pk = f.req_int(u, "id")
    owner_username = f.req_str(u, "username").lower()
    media = f.opt_dict(u, "media")
    if media is None:  # у аккаунта нет публикаций
        return ReelsPage(items=[], next_cursor=None, more_available=False)
    data = f.req_list(media, "data")
    items: list[ParsedItem] = []
    for i, node in enumerate(data):
        try:
            items.append(_parse_media(node, owner_pk, owner_username, captured_at))
        except InvalidResponse as e:
            raise InvalidResponse(f"media[{i}].{e.path}", e.reason) from e
    after = f.opt_str(media, "paging.cursors.after")
    more = bool(after) and len(data) >= page_size
    return ReelsPage(items=items, next_cursor=after if more else None, more_available=more)


def _parse_media(
    node: Any, owner_pk: int, owner_username: str, captured_at: datetime
) -> ParsedItem:
    shortcode = f.opt_str(node, "shortcode")
    if shortcode is None:
        permalink = f.req_str(node, "permalink")
        shortcode = permalink.rstrip("/").rsplit("/", 1)[-1]
    media_pk = shortcode_to_pk(shortcode)
    product = f.opt_str(node, "media_product_type") or "FEED"
    media_type = f.req_str(node, "media_type")
    if media_type not in _MEDIA_TYPES:
        raise InvalidResponse("media_type", f"unknown {media_type}")
    ts = f.req_str(node, "timestamp")
    taken_at = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(UTC)
    audio = f.opt_str(node, "media_audio_type")
    is_reel = product == "REELS"
    m = IgMedia(
        media_pk=media_pk,
        shortcode=shortcode,
        owner_user_pk=owner_pk,
        owner_username=owner_username,
        product_type=_PRODUCT_TYPES.get(product, product.lower()),
        media_type=_MEDIA_TYPES[media_type],
        taken_at=taken_at,
        caption=f.opt_str(node, "caption"),
        duration_s=None,
        is_pinned=False,  # API не отдаёт закреп
        coauthors=None,
        usertags=None,
        is_paid_partnership=None,
        sponsor_user_pks=None,
        audio_id=None,
        audio_title=None,
        is_original_audio=None if audio is None else audio == "ORIGINAL_SOUND",
        audio_type={"ORIGINAL_SOUND": "original_sounds", "MUSIC": "licensed_music"}.get(
            audio or ""
        ),
        accessibility_caption=f.opt_str(node, "alt_text"),
        video_url=None,
        cover_url=f.opt_str(node, "thumbnail_url"),
    )
    likes = f.opt_int(node, "like_count")
    x = IgMetrics(
        media_pk=media_pk,
        # Просмотры есть только у Reels; если автор их скрыл — None, снимок просмотров не пишется
        play_count=f.opt_int(node, "view_count") if is_reel else None,
        like_count=likes,
        comment_count=f.opt_int(node, "comments_count"),
        reshare_count=None,
        likes_hidden=likes is None,
        comments_disabled=False,
        captured_at=captured_at,
    )
    return ParsedItem(media=m, metrics=x)


def dump_error(page: RawPage) -> str:
    return page.meta.get("error") or json.dumps(page.json())[:300]
