"""Демо-данные для интерфейса до PoC. Все аккаунты вымышленные, ники начинаются с demo_.

Модель похожа на реальный сбор: наблюдение началось 30 дней назад и с тех пор
ежедневные снимки (часть дней пропущена — проверяется интерполяция); ролики
старше 30 дней — история, их просмотры до начала наблюдения по дням не
распределяются. В данные заложены закономерности, которые должен находить
экран «Что работает»: вечерние публикации, ролики 15–35 с, трендовый звук,
хэштег #распаковка работают лучше; платные интеграции — немного хуже.
"""

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import (
    Account,
    AccountSnapshot,
    Brand,
    BrandAccount,
    Media,
    MediaSignal,
    MetricQuarantine,
    MetricSnapshot,
    RawResponse,
    ScrapeTask,
)
from parser.parse.models import IgMedia
from parser.signals.extract import extract_signals

MSK = ZoneInfo("Europe/Moscow")
OBSERVATION_DAYS = 30
HISTORY_DAYS = 240

BRANDS = [
    ("Munique Base", True, ["muniquebase", "munique"]),
    ("WAISTLINE", False, ["waistline", "wline"]),
    ("Nordica Wear", False, ["nordicawear"]),
    ("Velvet Room", False, ["velvetroom", "vroom"]),
]
FIRST = [
    "anna",
    "katya",
    "masha",
    "sonya",
    "lera",
    "dasha",
    "vika",
    "alina",
    "polina",
    "nastya",
    "liza",
    "yana",
]
HOOKS = [
    "Примерка нового платья",
    "3 образа на неделю",
    "Распаковка заказа",
    "До и после",
    "Честный отзыв",
    "Собираюсь на свидание",
    "Капсула на осень",
    "Что надеть в офис",
    "Ошибки в образе, которые все делают",
    "Нашла идеальные джинсы",
]
TOPICS = {  # хэштег → множитель просмотров
    "распаковка": 1.45,
    "образ": 1.0,
    "ootd": 1.05,
    "стиль": 0.95,
    "платье": 1.1,
    "wb": 1.0,
    "капсула": 1.15,
    "осень": 1.0,
    "находкиwb": 1.25,
}
TREND_SOUNDS = [
    ("Midnight Drive", "DJ Polar"),
    ("Soft Focus", "Luma"),
    ("Runway", "KAYA"),
    ("Golden Hour", "Mira Sun"),
]
LOCATIONS = [
    (213385402, "Москва", 55.7558, 37.6173),
    (213131048, "Санкт-Петербург", 59.9343, 30.3351),
    (215418, "Казань", 55.7963, 49.1088),
]


def hour_effect(h: int) -> float:
    """Вечер (18–22) лучше, ночь и раннее утро хуже."""
    return {
        7: 0.7,
        8: 0.8,
        9: 0.85,
        10: 0.9,
        11: 0.95,
        12: 1.0,
        13: 1.0,
        14: 0.95,
        15: 0.95,
        16: 1.0,
        17: 1.1,
        18: 1.25,
        19: 1.35,
        20: 1.3,
        21: 1.2,
        22: 1.05,
        23: 0.85,
    }.get(h, 0.7)


def duration_effect(d: float) -> float:
    if d < 10:
        return 0.85
    if d < 15:
        return 1.0
    if d <= 35:
        return 1.2
    if d <= 60:
        return 0.9
    return 0.7


def curve(age_days: float) -> float:
    """Доля итоговых просмотров к возрасту: быстрый рост в первые дни, длинный хвост."""
    if age_days <= 0:
        return 0.0
    return (1 - math.exp(-age_days / 2.2)) * (0.85 + 0.15 * (1 - math.exp(-age_days / 60)))


async def seed_demo(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    rnd = random.Random(42)
    now = now or datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    today = now.date()
    obs_start = today - timedelta(days=OBSERVATION_DAYS)
    await session.execute(
        text(
            "TRUNCATE metric_snapshot, metric_quarantine, media_signal, media_brand, media_stats,"
            " media_daily_views, account_stats, media, account_snapshot, account_username_history,"
            " brand_account, brand, account, scrape_task, raw_response, shape_fingerprint"
            " RESTART IDENTITY CASCADE"
        )
    )

    pk_seq = iter(range(71_000_000_000, 72_000_000_000, 7919))
    media_seq = iter(range(3_400_000_000_000_000_000, 3_500_000_000_000_000_000, 104_729))
    accounts: list[dict[str, Any]] = []
    acc_snaps: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    medias: list[dict[str, Any]] = []
    snaps: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    raw_id = 1
    used_names: set[str] = set()

    def unique_name(suffix_range: tuple[int, int]) -> str:
        while True:
            name = f"demo_{rnd.choice(FIRST)}_{rnd.randint(*suffix_range)}"
            if name not in used_names:
                used_names.add(name)
                return name

    def account(
        username: str, followers: int, *, business: bool = False, bio: str | None = None
    ) -> int:
        pk = next(pk_seq)
        growth = rnd.uniform(-0.02, 0.18)
        accounts.append(
            dict(
                user_pk=pk,
                username=username,
                full_name=username.replace("demo_", "").replace("_", " ").title(),
                biography=bio,
                is_private=False,
                is_verified=followers > 800_000 and rnd.random() < 0.5,
                is_business=business,
                is_professional=True,
                business_category=rnd.choice(
                    ["Creators & Celebrities", "Personal Goods & General Merchandise", None]
                ),
                category=rnd.choice(
                    [
                        "Блогер",
                        "Личный блог",
                        "Одежда (бренд)" if business else "Творец цифрового контента",
                    ]
                ),
                highlight_reel_count=rnd.randint(0, 25),
                bio_links=[f"https://t.me/{username}"] if rnd.random() < 0.6 else None,
                status="active",
                added_at=now - timedelta(days=OBSERVATION_DAYS + 5),
                last_scraped_at=now - timedelta(hours=rnd.randint(1, 20)),
                backfill_done_at=now - timedelta(days=OBSERVATION_DAYS),
            )
        )
        for d in range(0, 46, 1):
            if d % 3 and d > 2:
                continue  # профиль снимается не каждый день — как при пропусках
            day = today - timedelta(days=d)
            f = int(followers * (1 - growth * d / 45))
            acc_snaps.append(
                dict(
                    user_pk=pk,
                    snapshot_date=day,
                    followers_count=f,
                    following_count=rnd.randint(100, 900),
                    media_count=rnd.randint(150, 900),
                    raw_response_id=1,
                )
            )
        return pk

    def reels(
        owner: int, username: str, median: float, count: int, brand_tag: str, shop: int | None
    ) -> None:
        nonlocal raw_id
        for _ in range(count):
            age = rnd.uniform(0.2, HISTORY_DAYS)
            local = (now - timedelta(days=age)).astimezone(MSK)
            hour = rnd.choices(
                range(7, 24), weights=[1, 2, 3, 3, 3, 4, 4, 3, 3, 4, 5, 6, 6, 6, 5, 4, 2]
            )[0]
            taken = local.replace(hour=hour, minute=rnd.randint(0, 59)).astimezone(UTC)
            age = (now - taken).total_seconds() / 86400
            if age <= 0.05:
                continue
            duration = round(min(max(rnd.lognormvariate(math.log(24), 0.55), 5), 90), 2)
            topics = rnd.sample(list(TOPICS), k=rnd.randint(1, 3))
            trend = rnd.random() < 0.35
            paid = shop is not None and rnd.random() < 0.12
            mult = math.exp(rnd.gauss(0, 0.42)) * hour_effect(hour) * duration_effect(duration)
            mult *= (
                math.prod(TOPICS[t] for t in topics)
                * (1.2 if trend else 1.0)
                * (0.85 if paid else 1.0)
            )
            if rnd.random() < 0.06:
                mult *= rnd.choice([2.5, 4, 6, 8, 13, 20])
            final = max(int(median * mult), 300)

            pk = next(media_seq)
            caption = f"{rnd.choice(HOOKS)} #{brand_tag} " + " ".join(f"#{t}" for t in topics)
            if rnd.random() < 0.3:
                caption += f" арт. {rnd.randint(100_000_000, 999_999_999)}"
            if rnd.random() < 0.2 and shop:
                caption += f" @demo_{brand_tag}_shop"
            sound = rnd.choice(TREND_SOUNDS)
            loc = rnd.choice(LOCATIONS) if rnd.random() < 0.25 else None
            row = dict(
                media_pk=pk,
                shortcode=f"DEMO{pk % 10**9:09d}",
                owner_user_pk=owner,
                product_type="clips",
                media_type="video",
                taken_at=taken,
                caption=caption,
                duration_s=Decimal(str(duration)),
                is_pinned=False,
                is_paid_partnership=paid,
                sponsor_user_pks=[shop] if paid else None,
                coauthors=[shop] if shop and not paid and rnd.random() < 0.06 else None,
                usertags=[shop] if shop and rnd.random() < 0.25 else None,
                audio_id=str(abs(hash(sound)) % 10**12) if trend else str(pk % 10**12),
                audio_title=sound[0] if trend else "Original audio",
                audio_artist=sound[1] if trend else username,
                audio_type="licensed_music" if trend else "original_sounds",
                is_original_audio=not trend,
                has_audio=True,
                width=1080,
                height=1920,
                location_pk=loc[0] if loc else None,
                location_name=loc[1] if loc else None,
                location_lat=Decimal(str(loc[2])) if loc else None,
                location_lng=Decimal(str(loc[3])) if loc else None,
                is_shared_to_fb=rnd.random() < 0.3,
                remix_of_media_pk=None,
                first_seen_at=max(taken, datetime.combine(obs_start, now.timetz())),
            )
            medias.append(row)
            ig = IgMedia(
                media_pk=pk,
                shortcode=row["shortcode"],
                owner_user_pk=owner,
                product_type="clips",
                media_type="video",
                taken_at=taken,
                caption=caption,
                duration_s=row["duration_s"],
                is_pinned=False,
                coauthors=row["coauthors"],
                usertags=row["usertags"],
                is_paid_partnership=paid,
                sponsor_user_pks=row["sponsor_user_pks"],
                audio_id=None,
                audio_title=None,
                is_original_audio=None,
                video_url=None,
                cover_url=None,
            )
            signals.extend(
                {"media_pk": pk, "kind": sg.kind, "value": sg.value, "confidence": sg.confidence}
                for sg in extract_signals(ig)
            )

            likes_hidden = rnd.random() < 0.05
            like_rate = rnd.uniform(0.02, 0.07)
            comment_rate = rnd.uniform(0.0005, 0.004)
            total = final / curve(age) if curve(age) else final
            first_day = max(taken.astimezone(MSK).date() + timedelta(days=1), obs_start)
            d = first_day
            while d <= today:
                at_age = (datetime.combine(d, now.timetz()) - taken).total_seconds() / 86400
                skip = rnd.random() < 0.05 and d not in (first_day, today)
                if not skip and at_age > 0:
                    plays = max(int(total * curve(at_age)), 1)
                    snaps.append(
                        dict(
                            media_pk=pk,
                            snapshot_date=d,
                            captured_at=datetime.combine(d, now.timetz()),
                            play_count=plays,
                            like_count=None if likes_hidden else int(plays * like_rate),
                            comment_count=int(plays * comment_rate),
                            reshare_count=int(plays * rnd.uniform(0.001, 0.006)),
                            likes_hidden=likes_hidden,
                            source="web",
                            raw_response_id=raw_id,
                        )
                    )
                d += timedelta(days=1)
            raw_id += 1

    brand_rows = []
    for i, (name, own, tags) in enumerate(BRANDS, start=1):
        shop = account(
            f"demo_{tags[0]}_shop",
            rnd.randint(40_000, 400_000),
            business=True,
            bio=f"Официальный аккаунт {name}",
        )
        brand_rows.append(
            dict(
                id=i,
                name=name,
                is_own=own,
                hashtags=tags,
                shop_user_pk=shop,
                spike_min_views=50_000,
                rocket_views=500_000,
            )
        )
        links.append(
            dict(
                brand_id=i,
                user_pk=shop,
                role="shop",
                link_type=None,
                status="tracked",
                confidence=Decimal(1),
                evidence=[],
                first_seen=obs_start,
            )
        )
        reels(shop, f"demo_{tags[0]}_shop", rnd.uniform(15_000, 60_000), 30, tags[0], None)

        for _ in range(rnd.randint(6, 9)):
            uname = unique_name((10, 99))
            median = math.exp(rnd.uniform(math.log(8_000), math.log(250_000)))
            pk = account(
                uname,
                int(median * rnd.uniform(3, 12)),
                bio=f"амбассадор {name}" if rnd.random() < 0.4 else None,
            )
            reels(pk, uname, median, rnd.randint(25, 70), tags[0], shop)
            links.append(
                dict(
                    brand_id=i,
                    user_pk=pk,
                    role="creator",
                    link_type=rnd.choice(["ambassador", "paid", "ugc", "reviewer"]),
                    status="tracked",
                    is_own_creator=own,
                    confidence=Decimal("0.950"),
                    evidence=[
                        {"kind": "collab", "media_pk": None, "value": name, "weight": 50},
                        {"kind": "hashtag", "media_pk": None, "value": tags[0], "weight": 15},
                    ],
                    all_posts_count_for_brand=True,
                    first_seen=obs_start,
                )
            )

        for _ in range(3):
            uname = unique_name((100, 999))
            pk = account(uname, rnd.randint(2_000, 90_000))
            evidence = rnd.sample(
                [
                    {"kind": "usertag", "media_pk": None, "value": name, "weight": 25},
                    {"kind": "hashtag", "media_pk": None, "value": tags[0], "weight": 15},
                    {"kind": "collab", "media_pk": None, "value": name, "weight": 50},
                    {"kind": "paid_partnership", "media_pk": None, "value": name, "weight": 60},
                    {"kind": "brand_name", "media_pk": None, "value": "biography", "weight": 20},
                    {"kind": "wb_article", "media_pk": None, "value": "847963328", "weight": 30},
                ],
                k=rnd.randint(1, 3),
            )
            conf = min(Decimal(1), Decimal(sum(int(str(e["weight"])) for e in evidence)) / 100)
            links.append(
                dict(
                    brand_id=i,
                    user_pk=pk,
                    role="creator",
                    link_type=None,
                    status="candidate",
                    confidence=conf,
                    evidence=evidence,
                    first_seen=today - timedelta(days=rnd.randint(0, 6)),
                )
            )

    await _bulk(session, Account, accounts)
    await _bulk(session, Brand, brand_rows)
    await session.execute(text("SELECT setval('brand_id_seq', (SELECT max(id) FROM brand))"))
    await _bulk(session, BrandAccount, links)
    await _bulk(session, AccountSnapshot, acc_snaps)
    await _bulk(session, Media, medias)
    await _bulk(session, MetricSnapshot, snaps)
    await _bulk(session, MediaSignal, signals)

    await _demo_parser_state(session, rnd, now, accounts, medias[0]["media_pk"])
    await session.commit()
    return {"accounts": len(accounts), "media": len(medias), "snapshots": len(snaps)}


async def _demo_parser_state(
    session: AsyncSession,
    rnd: random.Random,
    now: datetime,
    accounts: list[dict[str, Any]],
    quarantined_pk: int,
) -> None:
    tasks = []
    for a in accounts:
        for t, hour in (("profile", 1), ("feed_head", 1)):
            tasks.append(
                dict(
                    type=t,
                    user_pk=a["user_pk"],
                    priority=2,
                    status="succeeded",
                    idempotency_key=f"{t}:{a['user_pk']}:{now:%Y-%m-%d}T{hour:02d}",
                    run_after=now - timedelta(hours=5),
                    attempts=1,
                    finished_at=now - timedelta(hours=rnd.uniform(1, 5)),
                )
            )
    picks = rnd.sample(accounts, 4)
    tasks += [
        dict(
            type="feed_deep",
            user_pk=picks[0]["user_pk"],
            priority=3,
            status="pending",
            idempotency_key=f"feed_deep:{picks[0]['user_pk']}:demo",
            run_after=now,
            attempts=0,
        ),
        dict(
            type="backfill",
            user_pk=picks[1]["user_pk"],
            priority=1,
            status="running",
            idempotency_key=f"backfill:{picks[1]['user_pk']}:demo",
            run_after=now,
            attempts=1,
            cursor="QVFDdemo",
            pages_done=14,
            lease_until=now + timedelta(minutes=8),
        ),
        dict(
            type="feed_head",
            user_pk=picks[2]["user_pk"],
            priority=2,
            status="deferred",
            idempotency_key=f"feed_head:{picks[2]['user_pk']}:demo",
            run_after=now + timedelta(minutes=40),
            attempts=1,
            last_error="rate_limited (429)",
        ),
        dict(
            type="profile",
            user_pk=picks[3]["user_pk"],
            priority=2,
            status="failed",
            idempotency_key=f"profile:{picks[3]['user_pk']}:demo",
            run_after=now,
            attempts=1,
            last_error="data.user.edge_followed_by.count: required int missing",
            finished_at=now - timedelta(hours=2),
        ),
    ]
    await _bulk(session, ScrapeTask, (tasks))
    await _bulk(
        session,
        RawResponse,
        (
            [
                dict(
                    task_id=None,
                    page=0,
                    request_kind="profile",
                    source="web",
                    http_status=200,
                    bytes=4210,
                    shape_fingerprint="b6cf69d6c5195e50",
                    parse_status="invalid",
                    parse_error="data.user.edge_followed_by.count: required int missing",
                    s3_key="raw/demo/0000-profile.json.gz",
                    received_at=now - timedelta(hours=2),
                ),
            ]
        ),
    )
    await _bulk(
        session,
        MetricQuarantine,
        (
            [
                dict(
                    media_pk=quarantined_pk,
                    snapshot_date=now.date(),
                    captured_at=now,
                    play_count=120_000,
                    source="web",
                    raw_response_id=1,
                    reason="views dropped 41.2%: 204000 -> 120000",
                ),
            ]
        ),
    )


async def _bulk(session: AsyncSession, model: Any, rows: list[dict[str, Any]]) -> None:
    """Многострочная вставка требует одинаковых ключей: группируем строки по набору ключей."""
    groups: dict[frozenset[str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(frozenset(r), []).append(r)
    # asyncpg: не больше 32 767 параметров в запросе, SQLAlchemy может подставить все колонки
    size = max(1, 30_000 // len(model.__table__.columns))
    for group in groups.values():
        for i in range(0, len(group), size):
            await session.execute(
                insert(model).values(group[i : i + size]).on_conflict_do_nothing()
            )
