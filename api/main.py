"""Внутренний API для веб-интерфейса: списки брендов и креаторов, аномалии, парсер.

Тяжёлое считается ночью (core/metrics/recompute); здесь — только выборки и суммы.
"""

import csv
import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.analytics import router as analytics_router
from core.db.models import Account, Brand, BrandAccount
from core.db.session import session_scope
from core.discovery.confidence import level
from core.metrics.recompute import recompute_all
from parser.cli import normalize_username
from parser.queue import tasks as q

app = FastAPI(
    title="smart-parser", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
)
app.include_router(analytics_router)


async def db() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


Db = Annotated[AsyncSession, Depends(db)]
Days = Annotated[int, Query(ge=1, le=3650)]


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in result.mappings().all()]


async def _data_as_of(session: AsyncSession) -> datetime | None:
    value: datetime | None = await session.scalar(
        text("SELECT max(finished_at) FROM scrape_task WHERE status = 'succeeded'")
    )
    return value


# --- Аномалии --------------------------------------------------------------------------

_CATEGORY_RANK = {"high": 1, "strong": 2, "viral": 3}
_SORTS = {
    "ratio": "s.spike_ratio DESC NULLS LAST",
    "views": "s.views DESC NULLS LAST",
    "date": "md.taken_at DESC",
}


@app.get("/api/v1/anomalies", response_model=None)
async def anomalies(
    session: Db,
    days: Days = 30,
    brand_id: Annotated[list[int] | None, Query()] = None,
    scope: Annotated[str, Query(pattern="^(all|own|competitors)$")] = "all",
    min_category: Annotated[str, Query(pattern="^(high|strong|viral)$")] = "high",
    sort: Annotated[str, Query(pattern="^(ratio|views|date)$")] = "ratio",
    owner: int | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 200,
    format: Annotated[str, Query(pattern="^(json|csv)$")] = "json",
) -> Any:
    cats = [c for c, r in _CATEGORY_RANK.items() if r >= _CATEGORY_RANK[min_category]]
    where = ["md.taken_at >= :since", "s.spike_category = ANY(:cats)"]
    params: dict[str, Any] = {
        "since": datetime.now(UTC) - timedelta(days=days),
        "cats": cats,
        "limit": limit,
    }
    if brand_id:
        where.append("mb.brand_id = ANY(:brand_ids)")
        params["brand_ids"] = brand_id
    if scope != "all":
        where.append("b.is_own = :own")
        params["own"] = scope == "own"
    if owner is not None:
        where.append("md.owner_user_pk = :owner")
        params["owner"] = owner
    rows = _rows(
        await session.execute(
            text(
                f"""
                SELECT md.media_pk::text AS media_pk, md.shortcode, md.taken_at, md.caption, md.duration_s,
                       md.audio_title, md.is_paid_partnership,
                       a.user_pk AS owner_user_pk, a.username AS owner_username,
                       s.views, s.views_7d, s.baseline_median, s.spike_ratio, s.spike_category,
                       s.spike_method, s.is_early, s.is_rocket, s.er, s.likes, s.comments, s.reshares,
                       s.views_per_day, md.audio_artist, md.location_name,
                       json_agg(json_build_object('id', b.id, 'name', b.name, 'is_own', b.is_own,
                                                  'reason', mb.reason) ORDER BY b.name) AS brands
                  FROM media_stats s
                  JOIN media md ON md.media_pk = s.media_pk
                  JOIN account a ON a.user_pk = md.owner_user_pk
                  JOIN media_brand mb ON mb.media_pk = s.media_pk
                  JOIN brand b ON b.id = mb.brand_id
                 WHERE {" AND ".join(where)}
                 GROUP BY md.media_pk, a.user_pk, s.media_pk
                 ORDER BY {_SORTS[sort]}
                 LIMIT :limit
                """
            ),
            params,
        )
    )
    if format == "csv":
        return _csv_response(
            "anomalies.csv",
            [
                {
                    "url": f"https://www.instagram.com/reel/{r['shortcode']}/",
                    "owner": r["owner_username"],
                    "brands": ", ".join(b["name"] for b in r["brands"]),
                    "taken_at": r["taken_at"].isoformat(),
                    "views": r["views"],
                    "baseline_median": r["baseline_median"],
                    "spike_ratio": r["spike_ratio"],
                    "category": r["spike_category"],
                    "method": r["spike_method"],
                    "er": r["er"],
                    "caption": (r["caption"] or "").replace("\n", " "),
                }
                for r in rows
            ],
        )
    return {"items": rows}


def _csv_response(filename: str, rows: list[dict[str, Any]]) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("﻿")  # BOM, чтобы Excel открыл кириллицу
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Бренды ----------------------------------------------------------------------------


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_own: bool = False
    instagram: str | None = None
    hashtags: list[str] = []
    spike_min_views: int = Field(50_000, ge=0)
    rocket_views: int = Field(500_000, ge=0)


class BrandPatch(BaseModel):
    name: str | None = None
    is_own: bool | None = None
    instagram: str | None = None
    hashtags: list[str] | None = None
    spike_min_views: int | None = Field(None, ge=0)
    rocket_views: int | None = Field(None, ge=0)


def _clean_tags(tags: list[str]) -> list[str]:
    return sorted({t.strip().lstrip("#").lower() for t in tags if t.strip().lstrip("#")})


async def _attach_account(
    session: AsyncSession, brand_id: int, instagram: str, *, role: str, is_own_creator: bool = False
) -> dict[str, Any]:
    """Связать аккаунт с брендом. Неизвестный ник — задача profile, связь появится после неё."""
    username = normalize_username(instagram)
    if not username:
        raise HTTPException(422, "Не удалось разобрать ник или ссылку Instagram")
    acc = await session.scalar(select(Account).where(Account.username == username))
    if acc is None:
        task_id = await q.enqueue(
            session,
            q.TaskType.PROFILE,
            username=username,
            window=f"link-{brand_id}",
            priority=q.Priority.P1,
            payload={
                "link": {"brand_id": brand_id, "role": role, "is_own_creator": is_own_creator}
            },
        )
        return {"username": username, "status": "queued", "task_id": task_id}
    if role == "shop":
        await session.execute(
            update(Brand).where(Brand.id == brand_id).values(shop_user_pk=acc.user_pk)
        )
    await session.execute(
        text(
            """
            INSERT INTO brand_account (brand_id, user_pk, role, status, is_own_creator,
                                       confidence, evidence, all_posts_count_for_brand, first_seen)
            VALUES (:b, :u, :role, 'tracked', :own, 1, '[]', :all_posts, current_date)
            ON CONFLICT (brand_id, user_pk) DO UPDATE
               SET status = 'tracked', role = excluded.role, is_own_creator = excluded.is_own_creator
            """
        ),
        {
            "b": brand_id,
            "u": acc.user_pk,
            "role": role,
            "own": is_own_creator,
            "all_posts": role == "creator",
        },
    )
    if acc.backfill_done_at is None:
        await q.enqueue(session, q.TaskType.BACKFILL, user_pk=acc.user_pk, window="initial")
    return {"username": username, "status": "linked", "user_pk": acc.user_pk}


@app.get("/api/v1/brands")
async def list_brands(session: Db) -> list[dict[str, Any]]:
    return _rows(
        await session.execute(
            text(
                """
                SELECT b.*, a.username AS shop_username,
                       count(ba.*) FILTER (WHERE ba.role = 'creator' AND ba.status = 'tracked') AS creators,
                       count(ba.*) FILTER (WHERE ba.status = 'candidate') AS candidates
                  FROM brand b
                  LEFT JOIN account a ON a.user_pk = b.shop_user_pk
                  LEFT JOIN brand_account ba ON ba.brand_id = b.id
                 GROUP BY b.id, a.username ORDER BY b.is_own DESC, b.name
                """
            )
        )
    )


@app.post("/api/v1/brands", status_code=201)
async def create_brand(body: BrandIn, session: Db) -> dict[str, Any]:
    if await session.scalar(select(Brand.id).where(Brand.name == body.name)):
        raise HTTPException(409, f"Бренд «{body.name}» уже есть")
    brand = Brand(
        name=body.name,
        is_own=body.is_own,
        hashtags=_clean_tags(body.hashtags),
        username_masks=[],
        spike_min_views=body.spike_min_views,
        rocket_views=body.rocket_views,
    )
    session.add(brand)
    await session.flush()
    shop = None
    if body.instagram:
        shop = await _attach_account(session, brand.id, body.instagram, role="shop")
    await session.commit()
    return {"id": brand.id, "shop": shop}


@app.patch("/api/v1/brands/{brand_id}")
async def patch_brand(brand_id: int, body: BrandPatch, session: Db) -> dict[str, Any]:
    brand = await session.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(404, "Бренд не найден")
    data = body.model_dump(exclude_unset=True)
    instagram = data.pop("instagram", None)
    if "hashtags" in data:
        data["hashtags"] = _clean_tags(data["hashtags"])
    for k, v in data.items():
        setattr(brand, k, v)
    shop = await _attach_account(session, brand_id, instagram, role="shop") if instagram else None
    await session.commit()
    return {"id": brand_id, "shop": shop}


@app.delete("/api/v1/brands/{brand_id}", status_code=204)
async def delete_brand(brand_id: int, session: Db) -> None:
    await session.execute(text("DELETE FROM media_brand WHERE brand_id = :b"), {"b": brand_id})
    await session.execute(delete(BrandAccount).where(BrandAccount.brand_id == brand_id))
    await session.execute(delete(Brand).where(Brand.id == brand_id))
    await session.commit()


@app.post("/api/v1/import")
async def import_csv(session: Db, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    """CSV (`,` или `;`): brand, is_own, instagram, role (shop|creator), hashtags, own_creator."""
    raw = (await file.read()).decode("utf-8-sig")
    dialect = csv.Sniffer().sniff(raw.splitlines()[0], delimiters=",;") if raw.strip() else "excel"
    report: list[dict[str, Any]] = []
    for n, row in enumerate(csv.DictReader(io.StringIO(raw), dialect=dialect), start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        name = row.get("brand") or row.get("бренд")
        if not name:
            report.append({"line": n, "status": "error", "message": "нет колонки brand"})
            continue
        brand = await session.scalar(select(Brand).where(Brand.name == name))
        if brand is None:
            brand = Brand(
                name=name,
                is_own=row.get("is_own", "").lower() in ("1", "true", "да", "yes"),
                hashtags=_clean_tags(row.get("hashtags", "").replace(",", " ").split()),
                username_masks=[],
            )
            session.add(brand)
            await session.flush()
        if row.get("instagram"):
            role = row.get("role") or "creator"
            own = row.get("own_creator", "").lower() in ("1", "true", "да", "yes")
            try:
                res = await _attach_account(
                    session, brand.id, row["instagram"], role=role, is_own_creator=own
                )
                report.append({"line": n, **res})
            except HTTPException as e:
                report.append({"line": n, "status": "error", "message": e.detail})
        else:
            report.append({"line": n, "status": "brand", "username": name})
    await session.commit()
    return {"rows": report}


@app.get("/api/v1/brands/{brand_id}")
async def brand_detail(brand_id: int, session: Db) -> dict[str, Any]:
    brand = (
        (
            await session.execute(
                text(
                    "SELECT b.*, a.username AS shop_username FROM brand b"
                    " LEFT JOIN account a ON a.user_pk = b.shop_user_pk WHERE b.id = :b"
                ),
                {"b": brand_id},
            )
        )
        .mappings()
        .first()
    )
    if brand is None:
        raise HTTPException(404, "Бренд не найден")
    creators = _rows(
        await session.execute(
            text(
                """
                SELECT a.user_pk, a.username, a.full_name, a.status AS account_status,
                       a.last_scraped_at, a.is_verified, ba.role, ba.link_type, ba.status,
                       ba.is_own_creator, ba.confidence, ba.first_seen, st.*,
                       st.median_views_20 AS median_views, st.reels_total AS reels,
                       st.spikes_total AS spikes, st.best_ratio AS max_ratio,
                       st.last_reel_at, st.trend
                  FROM brand_account ba
                  JOIN account a ON a.user_pk = ba.user_pk
                  LEFT JOIN account_stats st ON st.user_pk = a.user_pk
                 WHERE ba.brand_id = :b AND ba.status = 'tracked'
                 ORDER BY ba.role DESC, st.median_views_20 DESC NULLS LAST
                """
            ),
            {"b": brand_id},
        )
    )
    for c in creators:
        c.pop("computed_at", None)
    return {"brand": dict(brand), "creators": creators}


class CreatorIn(BaseModel):
    instagram: str
    is_own_creator: bool = False


@app.post("/api/v1/brands/{brand_id}/creators", status_code=201)
async def add_creator(brand_id: int, body: CreatorIn, session: Db) -> dict[str, Any]:
    if await session.get(Brand, brand_id) is None:
        raise HTTPException(404, "Бренд не найден")
    res = await _attach_account(
        session, brand_id, body.instagram, role="creator", is_own_creator=body.is_own_creator
    )
    await session.commit()
    return res


@app.delete("/api/v1/brands/{brand_id}/creators/{user_pk}", status_code=204)
async def remove_creator(brand_id: int, user_pk: int, session: Db) -> None:
    """Убирает связь; собранные данные аккаунта остаются."""
    await session.execute(
        delete(BrandAccount).where(
            BrandAccount.brand_id == brand_id, BrandAccount.user_pk == user_pk
        )
    )
    await session.commit()


# --- Кандидаты -------------------------------------------------------------------------


@app.get("/api/v1/candidates")
async def candidates(
    session: Db,
    brand_id: int | None = None,
    status: Annotated[str, Query(pattern="^(candidate|hidden)$")] = "candidate",
) -> list[dict[str, Any]]:
    rows = _rows(
        await session.execute(
            text(
                """
                SELECT ba.brand_id, b.name AS brand_name, a.user_pk, a.username, a.full_name,
                       a.biography, ba.confidence, ba.evidence, ba.link_type, ba.first_seen,
                       ba.status,
                       (SELECT followers_count FROM account_snapshot s WHERE s.user_pk = a.user_pk
                         ORDER BY snapshot_date DESC LIMIT 1) AS followers
                  FROM brand_account ba
                  JOIN account a ON a.user_pk = ba.user_pk
                  JOIN brand b ON b.id = ba.brand_id
                 WHERE ba.status = :status AND (CAST(:brand AS int) IS NULL OR ba.brand_id = :brand)
                 ORDER BY ba.confidence DESC NULLS LAST, ba.first_seen DESC
                """
            ),
            {"status": status, "brand": brand_id},
        )
    )
    for r in rows:
        r["level"] = str(level(r["confidence"])) if r["confidence"] is not None else None
    return rows


@app.post("/api/v1/candidates/{brand_id}/{user_pk}/{action}")
async def decide_candidate(brand_id: int, user_pk: int, action: str, session: Db) -> dict[str, Any]:
    if action not in ("approve", "hide"):
        raise HTTPException(404)
    link = await session.get(BrandAccount, (brand_id, user_pk))
    if link is None:
        raise HTTPException(404, "Кандидат не найден")
    if action == "approve":
        link.status = "tracked"
        link.hidden_at = None
        await q.enqueue(session, q.TaskType.BACKFILL, user_pk=user_pk, window="initial")
    else:
        link.status = "hidden"
        link.hidden_at = datetime.now(UTC)
    await session.commit()
    return {"status": link.status}


# --- Креатор ---------------------------------------------------------------------------


@app.get("/api/v1/accounts/{user_pk}")
async def account_detail(user_pk: int, session: Db) -> dict[str, Any]:
    acc = (
        (await session.execute(text("SELECT * FROM account WHERE user_pk = :u"), {"u": user_pk}))
        .mappings()
        .first()
    )
    if acc is None:
        raise HTTPException(404, "Аккаунт не найден")
    snapshot = (
        (
            await session.execute(
                text(
                    "SELECT * FROM account_snapshot WHERE user_pk = :u ORDER BY snapshot_date DESC LIMIT 1"
                ),
                {"u": user_pk},
            )
        )
        .mappings()
        .first()
    )
    brands = _rows(
        await session.execute(
            text(
                "SELECT b.id, b.name, b.is_own, ba.role, ba.status, ba.link_type, ba.is_own_creator"
                " FROM brand_account ba JOIN brand b ON b.id = ba.brand_id WHERE ba.user_pk = :u"
            ),
            {"u": user_pk},
        )
    )
    media = _rows(
        await session.execute(
            text(
                """
                SELECT md.media_pk::text AS media_pk, md.shortcode, md.taken_at, md.caption, md.duration_s,
                       md.audio_title, md.is_paid_partnership, md.missing_since,
                       s.views, s.views_7d, s.baseline_median, s.spike_ratio, s.spike_category,
                       s.spike_method, s.is_early, s.is_rocket, s.er, s.likes, s.comments, s.reshares,
                       s.views_per_day, s.views_before_observation, md.audio_artist, md.audio_type,
                       md.location_name, md.width, md.height, md.coauthors, md.usertags
                  FROM media md LEFT JOIN media_stats s USING (media_pk)
                 WHERE md.owner_user_pk = :u AND md.product_type = 'clips'
                 ORDER BY md.taken_at DESC
                """
            ),
            {"u": user_pk},
        )
    )
    tasks = _rows(
        await session.execute(
            text(
                "SELECT id, type, status, priority, attempts, last_error, created_at, finished_at"
                " FROM scrape_task WHERE user_pk = :u ORDER BY id DESC LIMIT 10"
            ),
            {"u": user_pk},
        )
    )
    return {
        "account": dict(acc),
        "snapshot": dict(snapshot) if snapshot else None,
        "brands": brands,
        "media": media,
        "tasks": tasks,
    }


@app.post("/api/v1/accounts/{user_pk}/refresh", status_code=202)
async def refresh_account(user_pk: int, session: Db) -> dict[str, Any]:
    window = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
    task_id = await q.enqueue(session, q.TaskType.MANUAL_REFRESH, user_pk=user_pk, window=window)
    await session.commit()
    return {"task_id": task_id, "queued": task_id is not None}


# --- Парсер ----------------------------------------------------------------------------


async def _parser_summary(session: AsyncSession) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                  (SELECT count(*) FROM account WHERE status = 'active') AS active_accounts,
                  (SELECT count(DISTINCT user_pk) FROM scrape_task
                    WHERE type IN ('feed_head', 'manual_refresh', 'backfill') AND status = 'succeeded'
                      AND finished_at > now() - interval '24 hours') AS covered_24h,
                  (SELECT count(*) FROM scrape_task WHERE status IN ('pending','retry','deferred')) AS queued,
                  (SELECT count(*) FROM scrape_task WHERE status = 'running') AS running,
                  (SELECT count(*) FROM scrape_task WHERE status = 'failed'
                    AND finished_at > now() - interval '24 hours') AS failed_24h,
                  (SELECT count(*) FROM metric_quarantine WHERE resolved_at IS NULL) AS quarantine,
                  (SELECT count(*) FROM raw_response WHERE parse_status = 'invalid'
                    AND received_at > now() - interval '24 hours') AS invalid_24h
                """
                )
            )
        )
        .mappings()
        .one()
    )
    out = dict(row)
    active = out["active_accounts"] or 0
    out["coverage"] = out["covered_24h"] / active if active else None
    return out


@app.get("/api/v1/parser/status")
async def parser_status(session: Db) -> dict[str, Any]:
    queue = _rows(
        await session.execute(
            text(
                "SELECT status, priority, count(*) AS n FROM scrape_task"
                " GROUP BY status, priority ORDER BY priority, status"
            )
        )
    )
    problems = _rows(
        await session.execute(
            text(
                """
                SELECT t.id, t.type, t.status, t.priority, t.attempts, t.last_error, t.cursor,
                       t.pages_done, t.run_after, t.lease_until, t.finished_at,
                       t.user_pk, coalesce(a.username, t.username) AS username
                  FROM scrape_task t LEFT JOIN account a ON a.user_pk = t.user_pk
                 WHERE t.status <> 'succeeded'
                 ORDER BY CASE t.status WHEN 'running' THEN 0 WHEN 'failed' THEN 1
                               WHEN 'deferred' THEN 2 ELSE 3 END, t.priority, t.id DESC
                 LIMIT 100
                """
            )
        )
    )
    quarantine = _rows(
        await session.execute(
            text(
                """
                SELECT q.id, q.media_pk::text AS media_pk, md.shortcode, a.username, q.snapshot_date, q.play_count,
                       q.reason, q.raw_response_id
                  FROM metric_quarantine q
                  LEFT JOIN media md ON md.media_pk = q.media_pk
                  LEFT JOIN account a ON a.user_pk = md.owner_user_pk
                 WHERE q.resolved_at IS NULL ORDER BY q.id DESC LIMIT 50
                """
            )
        )
    )
    invalid = _rows(
        await session.execute(
            text(
                "SELECT id, request_kind, http_status, shape_fingerprint, parse_error, s3_key, received_at"
                " FROM raw_response WHERE parse_status <> 'ok' ORDER BY id DESC LIMIT 50"
            )
        )
    )
    accounts = _rows(
        await session.execute(
            text(
                "SELECT user_pk, username, status, last_scraped_at FROM account"
                " WHERE status <> 'active' OR last_scraped_at IS NULL"
                " OR last_scraped_at < now() - interval '26 hours' ORDER BY last_scraped_at NULLS FIRST LIMIT 50"
            )
        )
    )
    return {
        "data_as_of": await _data_as_of(session),
        "summary": await _parser_summary(session),
        "queue": queue,
        "tasks": problems,
        "quarantine": quarantine,
        "invalid_responses": invalid,
        "problem_accounts": accounts,
    }


@app.post("/api/v1/quarantine/{qid}/{action}")
async def resolve_quarantine(qid: int, action: str, session: Db) -> dict[str, Any]:
    if action not in ("accept", "reject"):
        raise HTTPException(404)
    await session.execute(
        text("UPDATE metric_quarantine SET resolved_at = now(), resolution = :r WHERE id = :id"),
        {"r": "accepted" if action == "accept" else "rejected", "id": qid},
    )
    if action == "accept":
        await session.execute(
            text(
                """
                INSERT INTO metric_snapshot (media_pk, snapshot_date, captured_at, play_count, like_count,
                       comment_count, reshare_count, likes_hidden, comments_disabled, flags, source,
                       raw_response_id)
                SELECT media_pk, snapshot_date, captured_at, play_count, like_count, comment_count,
                       reshare_count, likes_hidden, comments_disabled, flags || '{manual_accept}', source,
                       raw_response_id
                  FROM metric_quarantine WHERE id = :id
                ON CONFLICT (media_pk, snapshot_date) DO UPDATE SET play_count = excluded.play_count,
                       flags = excluded.flags
                """
            ),
            {"id": qid},
        )
    await session.commit()
    return {"ok": True}


@app.post("/api/v1/recompute")
async def run_recompute(session: Db) -> dict[str, Any]:
    r = await recompute_all(session)
    return {
        "media": r.media,
        "media_brand": r.media_brand,
        "daily_rows": r.daily_rows,
        "accounts": r.accounts,
        "seconds": r.seconds,
    }


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
