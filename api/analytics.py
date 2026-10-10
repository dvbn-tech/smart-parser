"""Аналитика для интерфейса: обзор брендов, рейтинг креаторов, «что работает».

Все показатели — по роликам, отнесённым к бренду (media_brand), без официального
аккаунта бренда (если не попросили обратное). Нормированная эффективность
ролика — spike_ratio: просмотры / медиана 20 предыдущих Reels автора. Она
сравнима между крупными и маленькими креаторами, в отличие от просмотров.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import session_scope

router = APIRouter(prefix="/api/v1")


async def db() -> Any:
    async with session_scope() as session:
        yield session


Db = Annotated[AsyncSession, Depends(db)]
Days = Annotated[int, Query(ge=1, le=3650)]
Scope = Annotated[str, Query(pattern="^(all|own|competitors)$")]
BrandIds = Annotated[list[int] | None, Query()]

SPIKE = "s.spike_category IN ('high','strong','viral')"


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in result.mappings().all()]


def _filters(
    scope: str, brand_id: list[int] | None, include_shop: bool = False
) -> tuple[str, dict[str, Any]]:
    where = ["true"]
    params: dict[str, Any] = {}
    if not include_shop:
        where.append("mb.reason <> 'shop'")
    if brand_id:
        where.append("mb.brand_id = ANY(:brand_ids)")
        params["brand_ids"] = brand_id
    if scope != "all":
        where.append("b.is_own = :own")
        params["own"] = scope == "own"
    return " AND ".join(where), params


# --- Обзор -----------------------------------------------------------------------------

_BRAND_PERIOD = """
WITH bm AS (
    SELECT DISTINCT mb.brand_id, mb.media_pk, md.owner_user_pk, md.taken_at, md.duration_s,
           md.is_paid_partnership, md.is_original_audio,
           s.views, s.likes, s.comments, s.er, s.spike_category, s.spike_ratio
      FROM media_brand mb
      JOIN media md ON md.media_pk = mb.media_pk
      JOIN media_stats s ON s.media_pk = mb.media_pk
     WHERE mb.reason <> 'shop'
),
period AS (
    SELECT brand_id,
           count(*) AS reels,
           count(DISTINCT owner_user_pk) AS active_creators,
           coalesce(sum(views), 0)::bigint AS views,
           round(avg(views))::bigint AS avg_views,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY views)::bigint AS median_views,
           percentile_cont(0.9) WITHIN GROUP (ORDER BY views)::bigint AS p90_views,
           max(views) AS max_views,
           count(*) FILTER (WHERE spike_category IN ('high','strong','viral')) AS spikes,
           count(*) FILTER (WHERE spike_category = 'viral') AS viral,
           count(*) FILTER (WHERE views >= 1000000) AS million_plus,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY er) AS er_median,
           coalesce(sum(likes), 0)::bigint AS likes,
           coalesce(sum(comments), 0)::bigint AS comments,
           avg(duration_s) AS avg_duration_s,
           avg(CASE WHEN is_paid_partnership THEN 1.0 ELSE 0.0 END) AS paid_share,
           avg(CASE WHEN is_original_audio THEN 1.0 ELSE 0.0 END) AS original_audio_share,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY spike_ratio) AS median_ratio
      FROM bm WHERE taken_at >= :since AND taken_at < :until GROUP BY brand_id
),
gained AS (
    SELECT mb.brand_id, sum(d.views_increment)::bigint AS views_gained
      FROM media_daily_views d
      JOIN (SELECT DISTINCT brand_id, media_pk FROM media_brand WHERE reason <> 'shop') mb
        ON mb.media_pk = d.media_pk
     WHERE d.date >= :since_d AND d.date < :until_d GROUP BY mb.brand_id
)
SELECT p.*, g.views_gained FROM period p LEFT JOIN gained g USING (brand_id)
"""


@router.get("/overview")
async def overview(session: Db, days: Days = 30) -> dict[str, Any]:
    now = datetime.now(UTC)
    since, prev_since = now - timedelta(days=days), now - timedelta(days=2 * days)

    async def period(a: datetime, b: datetime) -> dict[int, dict[str, Any]]:
        rows = _rows(
            await session.execute(
                text(_BRAND_PERIOD),
                {
                    "since": a,
                    "until": b,
                    "since_d": a.date(),
                    "until_d": b.date() + timedelta(days=1),
                },
            )
        )
        return {r["brand_id"]: r for r in rows}

    cur, prev = await period(since, now), await period(prev_since, since)
    brands = _rows(
        await session.execute(
            text(
                """
                SELECT b.id, b.name, b.is_own, b.hashtags, b.spike_min_views, b.rocket_views,
                       sa.username AS shop_username, b.shop_user_pk,
                       count(ba.*) FILTER (WHERE ba.role = 'creator' AND ba.status = 'tracked') AS creators,
                       count(ba.*) FILTER (WHERE ba.role = 'creator' AND ba.status = 'tracked' AND ba.is_own_creator) AS own_creators,
                       count(ba.*) FILTER (WHERE ba.status = 'candidate') AS candidates,
                       (SELECT followers_count FROM account_snapshot x WHERE x.user_pk = b.shop_user_pk
                         ORDER BY snapshot_date DESC LIMIT 1) AS shop_followers,
                       (SELECT sum(st.followers) FROM brand_account c JOIN account_stats st USING (user_pk)
                         WHERE c.brand_id = b.id AND c.role = 'creator' AND c.status = 'tracked') AS creators_followers
                  FROM brand b
                  LEFT JOIN account sa ON sa.user_pk = b.shop_user_pk
                  LEFT JOIN brand_account ba ON ba.brand_id = b.id
                 GROUP BY b.id, sa.username
                 ORDER BY b.is_own DESC, b.name
                """
            )
        )
    )
    for b in brands:
        b["cur"] = cur.get(b["id"])
        b["prev"] = prev.get(b["id"])

    window = max(days, 30)
    daily = _rows(
        await session.execute(
            text(
                """
                SELECT mb.brand_id, d.date, sum(d.views_increment)::bigint AS views
                  FROM media_daily_views d
                  JOIN (SELECT DISTINCT brand_id, media_pk FROM media_brand WHERE reason <> 'shop') mb
                    ON mb.media_pk = d.media_pk
                 WHERE d.date >= :since
                 GROUP BY 1, 2 ORDER BY 2
                """
            ),
            {"since": (now - timedelta(days=window)).date()},
        )
    )
    weekly = _rows(
        await session.execute(
            text(
                f"""
                SELECT mb.brand_id, date_trunc('week', md.taken_at)::date AS week,
                       count(*) AS reels, count(*) FILTER (WHERE {SPIKE}) AS spikes,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY s.views)::bigint AS median_views
                  FROM media_brand mb
                  JOIN media md ON md.media_pk = mb.media_pk
                  JOIN media_stats s ON s.media_pk = mb.media_pk
                 WHERE md.taken_at >= :since AND mb.reason <> 'shop'
                 GROUP BY 1, 2 ORDER BY 2
                """
            ),
            {"since": now - timedelta(days=max(days, 90))},
        )
    )
    leaders = _rows(
        await session.execute(
            text(
                """
                WITH cm AS (
                    SELECT DISTINCT ON (md.media_pk) md.media_pk, md.owner_user_pk, md.taken_at, mb.brand_id,
                           s.views, s.spike_category
                      FROM media md
                      JOIN media_brand mb ON mb.media_pk = md.media_pk AND mb.reason <> 'shop'
                      JOIN media_stats s ON s.media_pk = md.media_pk
                     WHERE md.taken_at >= :since
                ),
                g AS (
                    SELECT md.owner_user_pk, sum(d.views_increment)::bigint AS views_gained
                      FROM media_daily_views d JOIN media md USING (media_pk)
                     WHERE d.date >= :since_d GROUP BY 1
                )
                SELECT a.user_pk, a.username, b.id AS brand_id, b.name AS brand_name, b.is_own,
                       count(cm.*) AS reels,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY cm.views)::bigint AS median_views,
                       round(avg(cm.views))::bigint AS avg_views,
                       count(*) FILTER (WHERE cm.spike_category IN ('high','strong','viral')) AS spikes,
                       max(g.views_gained) AS views_gained,
                       st.followers, st.median_views_20, st.trend
                  FROM cm
                  JOIN account a ON a.user_pk = cm.owner_user_pk
                  JOIN brand b ON b.id = cm.brand_id
                  LEFT JOIN g ON g.owner_user_pk = cm.owner_user_pk
                  LEFT JOIN account_stats st ON st.user_pk = cm.owner_user_pk
                 GROUP BY a.user_pk, b.id, st.user_pk
                 ORDER BY max(g.views_gained) DESC NULLS LAST
                 LIMIT 15
                """
            ),
            {"since": since, "since_d": since.date()},
        )
    )
    return {
        "data_as_of": await session.scalar(
            text("SELECT max(finished_at) FROM scrape_task WHERE status = 'succeeded'")
        ),
        "days": days,
        # с какой даты есть ежедневные снимки: раньше «просмотры за период» неизвестны
        "observed_since": await session.scalar(text("SELECT min(date) FROM media_daily_views")),
        "brands": brands,
        "daily": daily,
        "weekly": weekly,
        "leaders": leaders,
    }


# --- Креаторы --------------------------------------------------------------------------


@router.get("/creators")
async def creators(
    session: Db,
    days: Days = 30,
    scope: Scope = "all",
    brand_id: BrandIds = None,
    role: Annotated[str, Query(pattern="^(creator|shop|all)$")] = "creator",
) -> dict[str, Any]:
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    where = ["ba.status = 'tracked'"]
    params: dict[str, Any] = {"since": since, "since_d": since.date()}
    if role != "all":
        where.append("ba.role = :role")
        params["role"] = role
    if brand_id:
        where.append("ba.brand_id = ANY(:brand_ids)")
        params["brand_ids"] = brand_id
    if scope != "all":
        where.append("b.is_own = :own")
        params["own"] = scope == "own"
    rows = _rows(
        await session.execute(
            text(
                f"""
                WITH links AS (
                    SELECT ba.user_pk,
                           json_agg(json_build_object('id', b.id, 'name', b.name, 'is_own', b.is_own,
                                    'role', ba.role, 'link_type', ba.link_type,
                                    'is_own_creator', ba.is_own_creator) ORDER BY b.name) AS brands,
                           bool_or(ba.is_own_creator) AS is_own_creator,
                           bool_or(b.is_own) AS is_own_brand
                      FROM brand_account ba JOIN brand b ON b.id = ba.brand_id
                     WHERE {" AND ".join(where)}
                     GROUP BY ba.user_pk
                ),
                per AS (
                    SELECT md.owner_user_pk AS user_pk,
                           count(*) AS p_reels,
                           round(avg(s.views))::bigint AS p_avg_views,
                           percentile_cont(0.5) WITHIN GROUP (ORDER BY s.views)::bigint AS p_median_views,
                           max(s.views) AS p_max_views,
                           count(*) FILTER (WHERE {SPIKE}) AS p_spikes,
                           count(*) FILTER (WHERE s.spike_category = 'viral') AS p_viral,
                           max(s.spike_ratio) AS p_best_ratio,
                           percentile_cont(0.5) WITHIN GROUP (ORDER BY s.er) AS p_er
                      FROM media md JOIN media_stats s USING (media_pk)
                     WHERE md.taken_at >= :since AND md.product_type = 'clips'
                     GROUP BY 1
                ),
                gained AS (
                    SELECT md.owner_user_pk AS user_pk, sum(d.views_increment)::bigint AS p_views_gained
                      FROM media_daily_views d JOIN media md USING (media_pk)
                     WHERE d.date >= :since_d GROUP BY 1
                )
                SELECT a.user_pk, a.username, a.full_name, a.status AS account_status, a.is_verified,
                       a.category, a.last_scraped_at, l.brands, l.is_own_creator, l.is_own_brand,
                       st.*, per.*, gained.p_views_gained
                  FROM links l
                  JOIN account a ON a.user_pk = l.user_pk
                  LEFT JOIN account_stats st ON st.user_pk = l.user_pk
                  LEFT JOIN per ON per.user_pk = l.user_pk
                  LEFT JOIN gained ON gained.user_pk = l.user_pk
                 ORDER BY gained.p_views_gained DESC NULLS LAST
                """
            ),
            params,
        )
    )
    for r in rows:
        r.pop("computed_at", None)
    return {"days": days, "items": rows}


# --- Что работает ----------------------------------------------------------------------


@router.get("/insights")
async def insights(
    session: Db,
    days: Days = 180,
    scope: Scope = "all",
    brand_id: BrandIds = None,
    min_reels: Annotated[int, Query(ge=1, le=1000)] = 5,
) -> dict[str, Any]:
    where, params = _filters(scope, brand_id)
    params["since"] = datetime.now(UTC) - timedelta(days=days)
    base = f"""
        WITH r AS (
            SELECT DISTINCT ON (md.media_pk) md.*, s.views, s.spike_ratio, s.spike_category, s.er,
                   (md.taken_at AT TIME ZONE 'Europe/Moscow') AS local_at
              FROM media md
              JOIN media_brand mb ON mb.media_pk = md.media_pk
              JOIN brand b ON b.id = mb.brand_id
              JOIN media_stats s ON s.media_pk = md.media_pk
             WHERE md.taken_at >= :since AND md.product_type = 'clips' AND {where}
        )
    """
    agg = """
        count(*) AS reels,
        count(DISTINCT owner_user_pk) AS creators,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY spike_ratio) AS median_ratio,
        avg(spike_ratio) AS avg_ratio,
        avg(CASE WHEN spike_category IN ('high','strong','viral') THEN 1.0 ELSE 0.0 END) AS spike_rate,
        count(*) FILTER (WHERE spike_category IN ('high','strong','viral')) AS spikes,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY views)::bigint AS median_views,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY er) AS median_er
    """

    async def q(select: str, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return _rows(await session.execute(text(base + select), {**params, **(extra or {})}))

    total = (await q(f"SELECT {agg} FROM r"))[0]
    by_hour = await q(
        f"SELECT extract(hour FROM local_at)::int AS key, {agg} FROM r GROUP BY 1 ORDER BY 1"
    )
    by_weekday = await q(
        f"SELECT extract(isodow FROM local_at)::int AS key, {agg} FROM r GROUP BY 1 ORDER BY 1"
    )
    by_duration = await q(
        f"""
        SELECT CASE WHEN duration_s IS NULL THEN 'нет данных'
                    WHEN duration_s < 10 THEN '< 10 с' WHEN duration_s < 15 THEN '10–15 с'
                    WHEN duration_s < 25 THEN '15–25 с' WHEN duration_s < 35 THEN '25–35 с'
                    WHEN duration_s < 60 THEN '35–60 с' ELSE '60 с +' END AS key,
               min(coalesce(duration_s, 9999)) AS ord, {agg}
          FROM r GROUP BY 1 ORDER BY 2
        """
    )
    features = await q(
        f"""
        SELECT key, {agg} FROM (
            SELECT CASE WHEN is_original_audio THEN 'Свой звук' WHEN is_original_audio IS FALSE
                        THEN 'Трендовый / лицензионный звук' ELSE 'Звук неизвестен' END AS key, *
              FROM r
            UNION ALL
            SELECT CASE WHEN is_paid_partnership THEN 'Платное партнёрство' ELSE 'Без пометки партнёрства' END, * FROM r
            UNION ALL
            SELECT CASE WHEN coauthors IS NOT NULL THEN 'Collab (соавторы)' ELSE 'Без соавторов' END, * FROM r
            UNION ALL
            SELECT CASE WHEN location_name IS NOT NULL THEN 'С геометкой' ELSE 'Без геометки' END, * FROM r
            UNION ALL
            SELECT CASE WHEN usertags IS NOT NULL THEN 'С отметками аккаунтов' ELSE 'Без отметок' END, * FROM r
            UNION ALL
            SELECT CASE WHEN caption ~* '(арт\\.?|артикул)\\s*\\d{{6,12}}' THEN 'С артикулом WB' ELSE 'Без артикула' END, * FROM r
        ) x GROUP BY key ORDER BY key
        """
    )
    caption_len = await q(
        f"""
        SELECT CASE WHEN caption IS NULL THEN '0 — без подписи' WHEN length(caption) < 50 THEN '1 — до 50 символов'
                    WHEN length(caption) < 150 THEN '2 — 50–150' WHEN length(caption) < 400 THEN '3 — 150–400'
                    ELSE '4 — 400+' END AS key, {agg}
          FROM r GROUP BY 1 ORDER BY 1
        """
    )
    hashtags = await q(
        f"""
        , t AS (
            SELECT sg.value AS key, r.* FROM r JOIN media_signal sg ON sg.media_pk = r.media_pk AND sg.kind = 'hashtag'
        )
        SELECT key, {agg} FROM t GROUP BY key HAVING count(*) >= :min_reels
         ORDER BY count(*) DESC LIMIT 60
        """,
        {"min_reels": min_reels},
    )
    audio = await q(
        f"""
        SELECT coalesce(audio_title, 'без названия') || coalesce(' — ' || audio_artist, '') AS key,
               bool_or(is_original_audio) AS is_original, {agg}
          FROM r WHERE is_original_audio IS FALSE
         GROUP BY 1 HAVING count(*) >= 2 ORDER BY count(*) DESC LIMIT 20
        """
    )
    locations = await q(
        f"SELECT location_name AS key, {agg} FROM r WHERE location_name IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC LIMIT 15"
    )
    ratio_hist = await q(
        """
        SELECT CASE WHEN spike_ratio IS NULL THEN 'нет базы'
                    WHEN spike_ratio < 0.5 THEN '< ×0,5' WHEN spike_ratio < 1 THEN '×0,5–1'
                    WHEN spike_ratio < 2 THEN '×1–2' WHEN spike_ratio < 5 THEN '×2–5'
                    WHEN spike_ratio < 10 THEN '×5–10' ELSE '×10+' END AS key,
               min(coalesce(spike_ratio, -1)) AS ord, count(*) AS reels
          FROM r GROUP BY 1 ORDER BY 2
        """
    )
    base_rate = float(total["spike_rate"] or 0)
    for h in hashtags:
        h["lift"] = float(h["spike_rate"]) / base_rate if base_rate else None
        h["wilson_low"] = _wilson_low(int(h["spikes"]), int(h["reels"]))
    hashtags.sort(key=lambda h: h["wilson_low"], reverse=True)
    return {
        "days": days,
        "total": total,
        "by_hour": by_hour,
        "by_weekday": by_weekday,
        "by_duration": by_duration,
        "features": features,
        "caption_length": caption_len,
        "hashtags": hashtags,
        "audio": audio,
        "locations": locations,
        "ratio_histogram": ratio_hist,
    }


def _wilson_low(k: int, n: int, z: float = 1.96) -> float:
    """Нижняя граница 95% интервала Уилсона: 2 из 2 не обгонят 40 из 100 (техспека §12)."""
    if n == 0:
        return 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return float((centre - margin) / denom)


# --- Креатор: ряды для графиков --------------------------------------------------------


@router.get("/accounts/{user_pk}/series")
async def account_series(user_pk: int, session: Db, days: Days = 90) -> dict[str, Any]:
    since = (datetime.now(UTC) - timedelta(days=days)).date()
    followers = _rows(
        await session.execute(
            text(
                "SELECT snapshot_date AS date, followers_count AS followers FROM account_snapshot"
                " WHERE user_pk = :u AND snapshot_date >= :since ORDER BY 1"
            ),
            {"u": user_pk, "since": since},
        )
    )
    views = _rows(
        await session.execute(
            text(
                """
                SELECT d.date, sum(d.views_increment)::bigint AS views
                  FROM media_daily_views d JOIN media m USING (media_pk)
                 WHERE m.owner_user_pk = :u AND d.date >= :since GROUP BY 1 ORDER BY 1
                """
            ),
            {"u": user_pk, "since": since},
        )
    )
    stats = (
        (
            await session.execute(
                text("SELECT * FROM account_stats WHERE user_pk = :u"), {"u": user_pk}
            )
        )
        .mappings()
        .first()
    )
    hashtags = _rows(
        await session.execute(
            text(
                """
                SELECT sg.value AS tag, count(*) AS reels,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY s.spike_ratio) AS median_ratio,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY s.views)::bigint AS median_views
                  FROM media_signal sg JOIN media m USING (media_pk) JOIN media_stats s USING (media_pk)
                 WHERE m.owner_user_pk = :u AND sg.kind = 'hashtag'
                 GROUP BY 1 HAVING count(*) >= 2 ORDER BY count(*) DESC LIMIT 15
                """
            ),
            {"u": user_pk},
        )
    )
    by_hour = _rows(
        await session.execute(
            text(
                """
                SELECT extract(hour FROM m.taken_at AT TIME ZONE 'Europe/Moscow')::int AS hour,
                       count(*) AS reels,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY s.views)::bigint AS median_views
                  FROM media m JOIN media_stats s USING (media_pk)
                 WHERE m.owner_user_pk = :u AND m.product_type = 'clips' GROUP BY 1 ORDER BY 1
                """
            ),
            {"u": user_pk},
        )
    )
    return {
        "followers": followers,
        "views": views,
        "stats": dict(stats) if stats else None,
        "hashtags": hashtags,
        "by_hour": by_hour,
    }
