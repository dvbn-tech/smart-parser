"""Настройки из окружения (префикс SP_). Секреты — только через .env / секреты сервера."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DiscoveryWeights(BaseSettings):
    """Стартовые веса сигналов связи креатора с брендом (Ф-19, техспека §13)."""

    model_config = SettingsConfigDict(env_prefix="SP_WEIGHT_")

    paid_partnership: int = 60
    collab: int = 50
    wb_article: int = 30  # за ролик, не больше wb_article_max_media роликов
    wb_article_max_media: int = 2
    usertag: int = 25
    brand_name_in_profile: int = 20  # название бренда в нике или био
    username_mask: int = 20  # ник по маске бренда: «*.base», «*_mela»
    bio_link: int = 40  # ссылка на сайт или @аккаунт бренда в шапке профиля
    ambassador_bio: int = 20  # «амбассадор / креатор / модель» в био рядом с брендом
    hashtag: int = 15


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SP_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://parser:parser@127.0.0.1:5432/parser"
    redis_url: str = "redis://127.0.0.1:6379/0"

    s3_endpoint: str = "http://127.0.0.1:9000"
    s3_bucket: str = "smart-parser"
    s3_access_key: str = "minio"
    s3_secret_key: str = "minio12345"

    # Источник данных: graph — официальный Instagram Graph API (Business Discovery),
    # web — свои запросы к веб-эндпоинтам без логина
    source: str = "graph"
    meta_access_token: str | None = None  # долгоживущий токен пользователя Facebook (60 дней)
    meta_ig_user_id: str | None = (
        None  # id бизнес-аккаунта Instagram, от имени которого запрашиваем
    )
    meta_app_id: str | None = None
    meta_app_secret: str | None = None
    meta_graph_version: str = "v25.0"
    meta_requests_per_hour: int = 150  # с запасом к лимиту Meta ~200 в час
    meta_media_page_size: int = 50

    proxy_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    sentry_dsn: str | None = None

    # Лимиты (техспека §6)
    global_requests_per_hour: int = 600
    per_ip_requests_per_hour: int = 30
    min_pause_between_requests_s: float = 20.0
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 30.0

    # Всплески (техспека §9): глобальные пороги, у бренда — свои
    spike_min_views: int = 50_000
    rocket_views: int = 500_000

    canary_username: str = "munique.base_"
    candidate_probe_daily_limit: int = 50

    weights: DiscoveryWeights = Field(default_factory=DiscoveryWeights)


@lru_cache
def get_settings() -> Settings:
    return Settings()
