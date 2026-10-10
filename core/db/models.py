"""Схема БД (техспека §8). Ключи — идентификаторы Instagram: user_pk, media_pk.

Время — в UTC (timestamptz). Служебные created_at/updated_at добавлены там,
где они нужны для работы, а не везде подряд.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TIMESTAMP


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: TIMESTAMP(timezone=True)}


# --- Списки: бренды и креаторы брендов -------------------------------------------------


class Brand(Base):
    __tablename__ = "brand"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    is_own: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    shop_user_pk: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("account.user_pk", use_alter=True)
    )
    wb_seller_id: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    username_masks: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    spike_min_views: Mapped[int] = mapped_column(Integer, server_default="50000")
    rocket_views: Mapped[int] = mapped_column(Integer, server_default="500000")


class Account(Base):
    __tablename__ = "account"

    user_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str | None] = mapped_column(Text)
    biography: Mapped[str | None] = mapped_column(Text)
    external_url: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    is_private: Mapped[bool] = mapped_column(Boolean)
    is_verified: Mapped[bool] = mapped_column(Boolean)
    is_business: Mapped[bool] = mapped_column(Boolean)
    avatar_key: Mapped[str | None] = mapped_column(Text)
    # active | private | not_found | deleted | paused
    status: Mapped[str] = mapped_column(Text, server_default="active")
    not_found_since: Mapped[datetime | None]
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_scraped_at: Mapped[datetime | None]
    backfill_done_at: Mapped[datetime | None]

    __table_args__ = (Index("account_username_lower_uq", func.lower(username), unique=True),)


class AccountUsernameHistory(Base):
    __tablename__ = "account_username_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_pk: Mapped[int] = mapped_column(BigInteger, ForeignKey("account.user_pk"), index=True)
    username: Mapped[str] = mapped_column(Text)
    seen_from: Mapped[datetime]
    seen_to: Mapped[datetime | None]


class AccountSnapshot(Base):
    __tablename__ = "account_snapshot"

    user_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    followers_count: Mapped[int] = mapped_column(Integer)
    following_count: Mapped[int] = mapped_column(Integer)
    media_count: Mapped[int] = mapped_column(Integer)
    raw_response_id: Mapped[int] = mapped_column(BigInteger)


class BrandAccount(Base):
    """Креатор бренда. Цикл: candidate → tracked (ставится backfill) | hidden."""

    __tablename__ = "brand_account"

    brand_id: Mapped[int] = mapped_column(ForeignKey("brand.id"), primary_key=True)
    user_pk: Mapped[int] = mapped_column(ForeignKey("account.user_pk"), primary_key=True)
    role: Mapped[str] = mapped_column(Text)  # creator | shop | satellite
    link_type: Mapped[str | None] = mapped_column(Text)  # ambassador|paid|ugc|reviewer|satellite
    status: Mapped[str] = mapped_column(Text)  # tracked | candidate | hidden
    is_own_creator: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    all_posts_count_for_brand: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    first_seen: Mapped[date | None] = mapped_column(Date)
    last_seen: Mapped[date | None] = mapped_column(Date)
    hidden_at: Mapped[datetime | None]


# --- Ролики и метрики ------------------------------------------------------------------


class Media(Base):
    __tablename__ = "media"

    media_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    shortcode: Mapped[str] = mapped_column(Text, unique=True)
    owner_user_pk: Mapped[int] = mapped_column(ForeignKey("account.user_pk"))
    product_type: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)
    taken_at: Mapped[datetime]
    caption: Mapped[str | None] = mapped_column(Text)
    duration_s: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    is_pinned: Mapped[bool] = mapped_column(Boolean)
    coauthors: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    usertags: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    is_paid_partnership: Mapped[bool | None] = mapped_column(Boolean)
    sponsor_user_pks: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    audio_id: Mapped[str | None] = mapped_column(Text)
    audio_title: Mapped[str | None] = mapped_column(Text)
    is_original_audio: Mapped[bool | None] = mapped_column(Boolean)
    # Ссылка на видео протухает; хранится для будущей разметки (Ф-23)
    video_url: Mapped[str | None] = mapped_column(Text)
    video_url_seen_at: Mapped[datetime | None]
    cover_key: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    missing_since: Mapped[datetime | None]
    missing_passes: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    __table_args__ = (Index("media_owner_taken_idx", owner_user_pk, text("taken_at DESC")),)


class MetricSnapshot(Base):
    """Один снимок на ролик в сутки; партиции по месяцам создаются миграцией."""

    __tablename__ = "metric_snapshot"

    media_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    captured_at: Mapped[datetime]
    play_count: Mapped[int] = mapped_column(BigInteger)
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    comment_count: Mapped[int | None] = mapped_column(BigInteger)
    reshare_count: Mapped[int | None] = mapped_column(BigInteger)
    likes_hidden: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    comments_disabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    source: Mapped[str] = mapped_column(Text)  # web | provider
    raw_response_id: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = ({"postgresql_partition_by": "RANGE (snapshot_date)"},)


class MetricQuarantine(Base):
    __tablename__ = "metric_quarantine"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    media_pk: Mapped[int] = mapped_column(BigInteger, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date)
    captured_at: Mapped[datetime]
    play_count: Mapped[int] = mapped_column(BigInteger)
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    comment_count: Mapped[int | None] = mapped_column(BigInteger)
    reshare_count: Mapped[int | None] = mapped_column(BigInteger)
    likes_hidden: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    comments_disabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    source: Mapped[str] = mapped_column(Text)
    raw_response_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime | None]
    resolution: Mapped[str | None] = mapped_column(Text)  # accepted | rejected


class MediaSignal(Base):
    __tablename__ = "media_signal"

    media_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    # hashtag | mention | wb_article | usertag | coauthor | sponsor
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, primary_key=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))

    __table_args__ = (Index("media_signal_kind_value_idx", kind, value),)


class MediaBrand(Base):
    __tablename__ = "media_brand"

    media_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brand.id"), primary_key=True)
    reason: Mapped[str] = mapped_column(Text)


class MediaStats(Base):
    """Пересчитывается каждую ночь (техспека §9)."""

    __tablename__ = "media_stats"

    media_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    views: Mapped[int | None] = mapped_column(BigInteger)
    views_24h: Mapped[int | None] = mapped_column(BigInteger)
    views_7d: Mapped[int | None] = mapped_column(BigInteger)
    baseline_median: Mapped[int | None] = mapped_column(BigInteger)
    spike_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    # none | high | strong | viral | insufficient_data
    spike_category: Mapped[str] = mapped_column(Text)
    spike_method: Mapped[str | None] = mapped_column(Text)  # age_matched_7d|early|current_views
    is_early: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_rocket: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    er: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    computed_at: Mapped[datetime]


# --- Парсер ----------------------------------------------------------------------------


class ScrapeTask(Base):
    """Источник истины очереди. Redis — только транспорт (техспека §4)."""

    __tablename__ = "scrape_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(Text)
    user_pk: Mapped[int | None] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(Text)  # для задач до того, как известен user_pk
    priority: Mapped[int] = mapped_column(SmallInteger)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    # pending | running | succeeded | retry | deferred | failed
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    cursor: Mapped[str | None] = mapped_column(Text)
    pages_done: Mapped[int] = mapped_column(Integer, server_default="0")
    run_after: Mapped[datetime] = mapped_column(server_default=func.now())
    lease_until: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="web")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]

    __table_args__ = (Index("scrape_task_pick_idx", status, priority, run_after),)


class RawResponse(Base):
    __tablename__ = "raw_response"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    page: Mapped[int] = mapped_column(SmallInteger)
    request_kind: Mapped[str] = mapped_column(Text)  # profile | reels | tagged | ...
    source: Mapped[str] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    bytes: Mapped[int | None] = mapped_column(Integer)
    shape_fingerprint: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(Text)  # ok | invalid | blocked | pending
    parse_error: Mapped[str | None] = mapped_column(Text)
    s3_key: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime]


class ShapeFingerprint(Base):
    """Журнал отпечатков структуры ответов (техспека §7)."""

    __tablename__ = "shape_fingerprint"

    fingerprint: Mapped[str] = mapped_column(Text, primary_key=True)
    request_kind: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime]
    sample_raw_response_id: Mapped[int] = mapped_column(BigInteger)
    paths: Mapped[list[str]] = mapped_column(ARRAY(Text))
