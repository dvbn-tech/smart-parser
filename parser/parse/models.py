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
    # Всё ниже — необязательное: Instagram отдаёт не всегда и не всем
    pronouns: list[str] | None = None
    bio_links: list[str] | None = None
    is_professional: bool | None = None
    business_category: str | None = None
    highlight_reel_count: int | None = None
    has_clips: bool | None = None
    hide_like_and_view_counts: bool | None = None
    fbid: str | None = None
    transparency_label: str | None = None


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
    owner_username: str | None = None
    # Всё ниже — необязательное: для будущего разбора «почему залетело» (Ф-23)
    audio_artist: str | None = None
    audio_type: str | None = None
    has_audio: bool | None = None
    caption_is_edited: bool | None = None
    accessibility_caption: str | None = None
    location_pk: int | None = None
    location_name: str | None = None
    location_lat: Decimal | None = None
    location_lng: Decimal | None = None
    width: int | None = None
    height: int | None = None
    remix_of_media_pk: int | None = None
    is_shared_to_fb: bool | None = None
    carousel_media_count: int | None = None
    commerciality_status: str | None = None
    is_in_profile_grid: bool | None = None

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
    video_view_count: int | None = None
    fb_play_count: int | None = None
    fb_like_count: int | None = None


class ParsedItem(_Model):
    media: IgMedia
    metrics: IgMetrics


class ReelsPage(_Model):
    items: list[ParsedItem]
    next_cursor: str | None
    more_available: bool
