"""WebSource: публичные веб-эндпоинты Instagram без логина.

Заголовки — один набор из конфига; маскировку под разные устройства и обход
защит не делаем (техспека §6, принцип 7). Какие из эндпоинтов реально
работают без логина и на какую глубину — выясняет PoC.
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from core.config import Settings
from parser.parse.models import IgProfile, ReelsPage
from parser.parse.profile import parse_web_profile_info
from parser.parse.reels import parse_reels_page
from parser.sources.base import RawPage
from parser.sources.pacing import PACER

BASE = "https://www.instagram.com"
IG_APP_ID = "936619743392459"  # публичный id веб-клиента Instagram
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "X-IG-App-ID": IG_APP_ID,
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE}/",
}
REELS_PAGE_SIZE = 12


class WebSource:
    name = "web"

    def __init__(
        self,
        settings: Settings,
        *,
        session_id: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        proxy = None
        if settings.proxy_url:
            # sticky-сессия: одна задача — один IP на все её страницы
            proxy = settings.proxy_url.replace("{session}", session_id or uuid.uuid4().hex[:12])
        self._client = httpx.AsyncClient(
            headers=HEADERS,
            proxy=proxy,
            follow_redirects=False,
            transport=transport,
            timeout=httpx.Timeout(settings.read_timeout_s, connect=settings.connect_timeout_s),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "WebSource":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _request(self, kind: str, method: str, path: str, **kwargs: Any) -> RawPage:
        await PACER.wait(
            self._settings.min_pause_between_requests_s, self._settings.global_requests_per_hour
        )
        started = time.monotonic()
        try:
            resp = await self._client.request(method, f"{BASE}{path}", **kwargs)
        finally:
            PACER.done()
        return RawPage(
            request_kind=kind,
            source=self.name,
            url=str(resp.request.url),
            http_status=resp.status_code,
            body=resp.content,
            received_at=datetime.now(UTC),
            elapsed_s=time.monotonic() - started,
            location=resp.headers.get("location"),
        )

    async def fetch_profile(self, username: str) -> RawPage:
        return await self._request(
            "profile", "GET", "/api/v1/users/web_profile_info/", params={"username": username}
        )

    async def fetch_reels(
        self, user_pk: int, cursor: str | None, username: str | None = None
    ) -> RawPage:
        data = {
            "target_user_id": str(user_pk),
            "page_size": str(REELS_PAGE_SIZE),
            "include_feed_video": "true",
        }
        if cursor:
            data["max_id"] = cursor
        return await self._request("reels", "POST", "/api/v1/clips/user/", data=data)

    async def fetch_feed(self, user_pk: int, cursor: str | None) -> RawPage:
        """Альтернатива ленте Reels для PoC: лента профиля в формате API v1."""
        params = {"count": str(REELS_PAGE_SIZE)}
        if cursor:
            params["max_id"] = cursor
        return await self._request("feed", "GET", f"/api/v1/feed/user/{user_pk}/", params=params)

    async def fetch_tagged(self, user_pk: int, cursor: str | None) -> RawPage:
        params = {"count": str(REELS_PAGE_SIZE)}
        if cursor:
            params["max_id"] = cursor
        return await self._request(
            "tagged", "GET", f"/api/v1/usertags/{user_pk}/feed/", params=params
        )

    async def search(self, query: str) -> RawPage:
        """Поиск аккаунтов по упоминанию бренда — PoC проверяет, доступен ли он без логина."""
        return await self._request(
            "search", "GET", "/web/search/topsearch/", params={"context": "blended", "query": query}
        )

    def parse_profile(self, page: RawPage) -> IgProfile:
        return parse_web_profile_info(page.json())

    def parse_reels(self, page: RawPage) -> ReelsPage:
        return parse_reels_page(page.json(), captured_at=page.received_at)
