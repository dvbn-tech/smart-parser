"""Уверенность в связи аккаунта с брендом (техспека §13, Ф-18, Ф-19).

confidence = min(1, Σ весов / 100). Уровни: Confirmed ≥ 0,9; Likely 0,6–0,89;
Possible < 0,6. Доказательства хранятся в brand_account.evidence списком
{kind, media_pk, value, weight}.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from core.config import DiscoveryWeights
from parser.parse.models import IgMedia, IgProfile
from parser.signals.extract import extract_hashtags, extract_mentions, extract_wb_articles

RESURFACE_MIN_WEIGHT = 50


class Level(StrEnum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    POSSIBLE = "possible"


@dataclass(frozen=True)
class Evidence:
    kind: str  # paid_partnership | collab | usertag | wb_article | brand_name | hashtag
    media_pk: int | None
    value: str
    weight: int

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrandRef:
    """То, по чему узнаём бренд: его аккаунты, хэштеги, название и артикулы продавца."""

    name: str
    account_pks: frozenset[int]
    account_usernames: frozenset[str]
    hashtags: frozenset[str]
    wb_articles: frozenset[str] = frozenset()


def name_token(name: str) -> str:
    """WAISTLINE, Waist Line, waist_line → waistline."""
    return re.sub(r"[\W_]+", "", name.lower())


def collect_evidence(
    brand: BrandRef,
    profile: IgProfile | None,
    medias: Iterable[IgMedia],
    weights: DiscoveryWeights,
) -> list[Evidence]:
    """Доказательства связи аккаунта с брендом из его профиля и роликов."""
    out: list[Evidence] = []
    token = name_token(brand.name)
    tags = {t.lower() for t in brand.hashtags}

    if profile is not None and len(token) >= 3:
        if token in name_token(profile.username):
            out.append(
                Evidence(
                    "brand_name",
                    None,
                    f"username:{profile.username}",
                    weights.brand_name_in_profile,
                )
            )
        elif profile.biography and token in name_token(profile.biography):
            out.append(Evidence("brand_name", None, "biography", weights.brand_name_in_profile))

    for m in medias:
        if m.owner_user_pk in brand.account_pks:
            continue  # ролики самого бренда — не доказательство чужой связи
        if m.is_paid_partnership and brand.account_pks & set(m.sponsor_user_pks or []):
            out.append(
                Evidence("paid_partnership", m.media_pk, brand.name, weights.paid_partnership)
            )
        if brand.account_pks & set(m.coauthors or []):
            out.append(Evidence("collab", m.media_pk, brand.name, weights.collab))
        caption = m.caption or ""
        mentioned = set(extract_mentions(caption)) & brand.account_usernames
        if brand.account_pks & set(m.usertags or []) or mentioned:
            out.append(Evidence("usertag", m.media_pk, brand.name, weights.usertag))
        for article in sorted(set(extract_wb_articles(caption)) & brand.wb_articles):
            out.append(Evidence("wb_article", m.media_pk, article, weights.wb_article))
        for tag in sorted(set(extract_hashtags(caption)) & tags):
            out.append(Evidence("hashtag", m.media_pk, tag, weights.hashtag))
    return out


def score(evidence: Sequence[Evidence], weights: DiscoveryWeights) -> Decimal:
    total = 0
    article_media: set[int | None] = set()
    seen: set[tuple[str, int | None, str]] = set()
    for e in evidence:
        key = (e.kind, e.media_pk, e.value)
        if key in seen:
            continue
        seen.add(key)
        if e.kind == "wb_article":
            # Артикул: вес за ролик, не больше заданного числа роликов
            if e.media_pk in article_media or len(article_media) >= weights.wb_article_max_media:
                continue
            article_media.add(e.media_pk)
        total += e.weight
    return min(Decimal(1), Decimal(total) / 100).quantize(Decimal("0.001"))


def level(confidence: Decimal) -> Level:
    if confidence >= Decimal("0.9"):
        return Level.CONFIRMED
    if confidence >= Decimal("0.6"):
        return Level.LIKELY
    return Level.POSSIBLE


def link_type(evidence: Sequence[Evidence]) -> str:
    kinds = [e.kind for e in evidence]
    if "paid_partnership" in kinds:
        return "paid"
    if kinds.count("collab") >= 2:
        return "ambassador"
    if "brand_name" in kinds:
        return "satellite"
    return "ugc"


def should_resurface(old: Sequence[Evidence], new: Sequence[Evidence]) -> bool:
    """Скрытый кандидат возвращается, только если появился новый сигнал весом ≥ 50."""
    known = {(e.kind, e.media_pk, e.value) for e in old}
    return any(
        e.weight >= RESURFACE_MIN_WEIGHT and (e.kind, e.media_pk, e.value) not in known for e in new
    )
