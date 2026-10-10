"""Результат разбора ответа Instagram (техспека §5).

Модели не знают ни про сеть, ни про базу. Необязательное поле, которого нет
в ответе, — None, никогда не 0 и не пустая строка.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IgProfile(_Model):
    user_pk: int
    username: str  # нижний регистр
    full_name: str | None
    biography: str | None
    external_url: str | None
    followers_count: int
    following_count: int
    media_count: int
    is_private: bool
    is_verified: bool
    is_business: bool
    category: str | None
    avatar_url: str | None  # временная CDN-ссылка, копия уходит в S3


class IgMedia(_Model):
    media_pk: int
    shortcode: str
    owner_user_pk: int
    product_type: str  # clips — Reels
    media_type: str  # video | image | carousel
    taken_at: datetime  # UTC
    caption: str | None
    duration_s: Decimal | None
    is_pinned: bool
    coauthors: list[int] | None
    usertags: list[int] | None
    is_paid_partnership: bool | None
    sponsor_user_pks: list[int] | None
    audio_id: str | None
    audio_title: str | None
    is_original_audio: bool | None
    video_url: str | None  # временная CDN-ссылка
    cover_url: str | None  # временная CDN-ссылка

    @property
    def is_reel(self) -> bool:
        return self.product_type == "clips"


class IgMetrics(_Model):
    media_pk: int
    play_count: int | None  # обязателен для Reels: без него снимок не пишется
    like_count: int | None
    comment_count: int | None
    reshare_count: int | None
    likes_hidden: bool
    comments_disabled: bool
    captured_at: datetime


class ParsedItem(_Model):
    media: IgMedia
    metrics: IgMetrics


class ReelsPage(_Model):
    items: list[ParsedItem]
    next_cursor: str | None
    more_available: bool
