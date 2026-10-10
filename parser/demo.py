"""Демо-данные для интерфейса до PoC. Все аккаунты вымышленные, ники начинаются с demo_.

Ролики старше 30 дней — «история» с одним снимком на сегодня, молодые —
ежедневные снимки с рождения, как будет при реальном сборе.
"""

import math
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import (
    Account,
    AccountSnapshot,
    Brand,
    BrandAccount,
    Media,
    MetricQuarantine,
    MetricSnapshot,
    RawResponse,
    ScrapeTask,
)

BRANDS = [
    ("Munique Base", True, ["muniquebase", "munique"]),
    ("WAISTLINE", False, ["waistline", "wline"]),
    ("Nordica Wear", False, ["nordicawear"]),
    ("Velvet Room", False, ["velvetroom", "vroom"]),
]
FIRST = ["anna", "katya", "masha", "sonya", "lera", "dasha", "vika", "alina", "polina", "nastya"]
HOOKS = [
    "Примерка нового платья",
    "3 образа на неделю",
    "Распаковка заказа",
    "До и после",
    "Честный отзыв",
    "Собираюсь на свидание",
    "Капсула на осень",
]


async def seed_demo(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    rnd = random.Random(42)
    now = now or datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    today = now.date()
    await session.execute(
        text(
            "TRUNCATE metric_snapshot, metric_quarantine, media_signal, media_brand, media_stats,"
            " media, account_snapshot, account_username_history, brand_account, brand, account,"
            " scrape_task, raw_response RESTART IDENTITY CASCADE"
        )
    )

    pk_seq = iter(range(71_000_000_000, 72_000_000_000, 7919))
    media_seq = iter(range(3_400_000_000_000_000_000, 3_500_000_000_000_000_000, 104_729))
    accounts: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    medias: list[dict[str, Any]] = []
    snaps: list[dict[str, Any]] = []
    raw_id = 1

    def account(username: str, followers: int, business: bool = False) -> int:
        pk = next(pk_seq)
        accounts.append(
            dict(
                user_pk=pk,
                username=username,
                full_name=username.replace("demo_", "").replace("_", " ").title(),
                biography=None,
                is_private=False,
                is_verified=False,
                is_business=business,
                status="active",
                added_at=now - timedelta(days=40),
                last_scraped_at=now - timedelta(hours=rnd.randint(1, 20)),
                followers=followers,
            )
        )
        return pk

    def reels(owner: int, median: float, count: int, brand_tag: str, shop: int | None) -> None:
        nonlocal raw_id
        for _ in range(count):
            age = rnd.uniform(0.3, 180)
            taken = now - timedelta(days=age)
            mult = math.exp(rnd.gauss(0, 0.45))
            if rnd.random() < 0.08:
                mult *= rnd.choice([2.5, 4, 6, 8, 13, 20])
            final = max(int(median * mult), 300)
            pk = next(media_seq)
            caption = f"{rnd.choice(HOOKS)} #{brand_tag}"
            if rnd.random() < 0.3:
                caption += f" арт. {rnd.randint(100_000_000, 999_999_999)}"
            paid = shop is not None and rnd.random() < 0.1
            medias.append(
                dict(
                    media_pk=pk,
                    shortcode=f"DEMO{pk % 10**9:09d}",
                    owner_user_pk=owner,
                    product_type="clips",
                    media_type="video",
                    taken_at=taken,
                    caption=caption,
                    duration_s=Decimal(str(round(rnd.uniform(7, 60), 2))),
                    is_pinned=False,
                    is_paid_partnership=paid,
                    sponsor_user_pks=[shop] if paid else None,
                    coauthors=[shop] if shop and not paid and rnd.random() < 0.06 else None,
                    audio_title=rnd.choice(["Original audio", "Trend sound", None]),
                    first_seen_at=max(taken, now - timedelta(days=30)),
                )
            )
            likes_hidden = rnd.random() < 0.05

            def snap(d: date, plays: int) -> None:
                snaps.append(
                    dict(
                        media_pk=pk,
                        snapshot_date=d,
                        captured_at=datetime.combine(d, now.timetz()),
                        play_count=plays,
                        like_count=None if likes_hidden else int(plays * rnd.uniform(0.02, 0.06)),
                        comment_count=int(plays * rnd.uniform(0.0005, 0.003)),
                        reshare_count=None,
                        likes_hidden=likes_hidden,
                        source="web",
                        raw_response_id=raw_id,
                    )
                )

            if age > 30:
                snap(today, final)  # история: один снимок
            else:
                days = int(age)
                for d in range(1, days + 1):
                    curve = 1 - math.exp(-d / 2.2)
                    snap(taken.date() + timedelta(days=d), max(int(final * curve), 1))
                if days == 0:
                    snap(today, max(int(final * 0.25), 1))
            raw_id += 1

    brand_rows = []
    for i, (name, own, tags) in enumerate(BRANDS, start=1):
        shop = account(f"demo_{tags[0]}_shop", rnd.randint(40_000, 400_000), business=True)
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
                first_seen=today - timedelta(days=40),
            )
        )
        reels(shop, rnd.uniform(15_000, 60_000), 25, tags[0], None)

        for _ in range(rnd.randint(5, 8)):
            name_ = f"demo_{rnd.choice(FIRST)}_{rnd.randint(10, 99)}"
            median = math.exp(rnd.uniform(math.log(8_000), math.log(250_000)))
            pk = account(name_, int(median * rnd.uniform(3, 12)))
            reels(pk, median, rnd.randint(20, 55), tags[0], shop)
            links.append(
                dict(
                    brand_id=i,
                    user_pk=pk,
                    role="creator",
                    link_type=rnd.choice(["ambassador", "paid", "ugc"]),
                    status="tracked",
                    is_own_creator=own,
                    confidence=Decimal("0.950"),
                    evidence=[
                        {"kind": "collab", "media_pk": None, "value": name, "weight": 50},
                        {"kind": "hashtag", "media_pk": None, "value": tags[0], "weight": 15},
                    ],
                    all_posts_count_for_brand=True,
                    first_seen=today - timedelta(days=40),
                )
            )

        for _ in range(3):
            name_ = f"demo_{rnd.choice(FIRST)}_{rnd.randint(100, 999)}"
            pk = account(name_, rnd.randint(2_000, 90_000))
            evidence = rnd.sample(
                [
                    {"kind": "usertag", "media_pk": None, "value": name, "weight": 25},
                    {"kind": "hashtag", "media_pk": None, "value": tags[0], "weight": 15},
                    {"kind": "collab", "media_pk": None, "value": name, "weight": 50},
                    {"kind": "paid_partnership", "media_pk": None, "value": name, "weight": 60},
                    {"kind": "brand_name", "media_pk": None, "value": "biography", "weight": 20},
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

    snapshots_acc = [
        dict(
            user_pk=a["user_pk"],
            snapshot_date=today,
            followers_count=a["followers"],
            following_count=rnd.randint(100, 900),
            media_count=rnd.randint(50, 900),
            raw_response_id=1,
        )
        for a in accounts
    ]
    for a in accounts:
        a.pop("followers")
    await _bulk(session, Account, (accounts))
    await _bulk(session, Brand, (brand_rows))
    await session.execute(text("SELECT setval('brand_id_seq', (SELECT max(id) FROM brand))"))
    await _bulk(session, BrandAccount, (links))
    await _bulk(session, AccountSnapshot, (snapshots_acc))
    await _bulk(session, Media, medias)
    await _bulk(session, MetricSnapshot, snaps)

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
    for group in groups.values():
        for i in range(0, len(group), 2000):
            await session.execute(insert(model).values(group[i : i + 2000]))
