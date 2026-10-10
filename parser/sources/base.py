"""Источник данных Instagram (техспека §6).

Сменная часть только одна: свои веб-запросы (WebSource) или платный
провайдер (ProviderSource). Источник отдаёт сырой ответ; разбор — отдельно,
чтобы ответ сохранялся до разбора и его можно было пересобрать (reparse).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from parser.parse.classify import Outcome, classify
from parser.parse.models import IgProfile, ReelsPage


@dataclass(frozen=True)
class RawPage:
    request_kind: str  # profile | reels | tagged | search
    source: str  # web | provider
    url: str
    http_status: int
    body: bytes
    received_at: datetime
    elapsed_s: float
    location: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except (ValueError, UnicodeDecodeError):
            return self.body[:5000].decode(errors="replace")

    @property
    def outcome(self) -> Outcome:
        return classify(self.http_status, self.location, self.json())


class InstagramSource(Protocol):
    name: str

    async def fetch_profile(self, username: str) -> RawPage: ...

    async def fetch_reels(self, user_pk: int, cursor: str | None) -> RawPage: ...

    async def fetch_tagged(self, user_pk: int, cursor: str | None) -> RawPage: ...

    def parse_profile(self, page: RawPage) -> IgProfile: ...

    def parse_reels(self, page: RawPage) -> ReelsPage: ...


class ProviderSource:
    """Резервный платный провайдер — по ТЗ только интерфейс."""

    name = "provider"

    def __init__(self) -> None:
        raise NotImplementedError("ProviderSource is out of scope for this contract")
