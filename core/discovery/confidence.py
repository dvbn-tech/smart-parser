"""Уверенность в связи аккаунта с брендом (техспека §13, Ф-18, Ф-19).

confidence = min(1, Σ весов / 100). Уровни: Confirmed ≥ 0,9; Likely 0,6–0,89;
Possible < 0,6. Доказательства хранятся в brand_account.evidence списком
{kind, media_pk, value, weight}.
"""

import fnmatch
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from core.config import DiscoveryWeights
from parser.parse.models import IgMedia, IgProfile
from parser.signals.extract import (
    extract_hashtags,
    extract_mentions,
    extract_wb_articles,
    extract_ww_codes,
)

RESURFACE_MIN_WEIGHT = 50


class Level(StrEnum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    POSSIBLE = "possible"


@dataclass(frozen=True)
class Evidence:
    # paid_partnership | collab | usertag | wb_article | ww_code | brand_name | username_mask
    # | bio_link | ambassador_bio | hashtag
    kind: str
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
    ww_codes: frozenset[str] = frozenset()
    username_masks: tuple[str, ...] = ()
    domains: frozenset[str] = frozenset()


AMBASSADOR_WORDS = ("амбассадор", "ambassador", "креатор", "creator", "модель", "лицо бренда")
ARTICLE_KINDS = ("wb_article", "ww_code")


def mask_matches(username: str, mask: str) -> bool:
    return fnmatch.fnmatchcase(username.lower(), mask.lower())


def _bio_brand_refs(brand: "BrandRef", profile: IgProfile) -> list[str]:
    """Ссылки на бренд в шапке: домен сайта в ссылках или @аккаунт бренда в био."""
    found: list[str] = []
    links = [u.lower() for u in [profile.external_url, *(profile.bio_links or [])] if u]
    for domain in sorted(brand.domains):
        if any(domain.lower() in link for link in links):
            found.append(domain)
    bio_mentions = set(extract_mentions(profile.biography or ""))
    found += [f"@{u}" for u in sorted(brand.account_usernames & bio_mentions)]
    return found


def _words(text: str) -> list[str]:
    return re.findall(r"(?<![\w.])[a-z0-9._]{3,30}(?![\w])", text.lower())


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

    if profile is not None:
        named = False
        refs = _bio_brand_refs(brand, profile)
        if len(token) >= 3 and token in name_token(profile.username):
            out.append(
                Evidence(
                    "brand_name",
                    None,
                    f"username:{profile.username}",
                    weights.brand_name_in_profile,
                )
            )
            named = True
        elif len(token) >= 3 and profile.biography and token in name_token(profile.biography):
            # @аккаунт бренда в био — это bio_link ниже, второй раз не считаем
            if not refs:
                out.append(Evidence("brand_name", None, "biography", weights.brand_name_in_profile))
            named = True
        masks = [m for m in brand.username_masks if mask_matches(profile.username, m)]
        if masks and not named:
            out.append(Evidence("username_mask", None, masks[0], weights.username_mask))
        if refs:
            out.append(Evidence("bio_link", None, refs[0], weights.bio_link))
        bio = (profile.biography or "").lower()
        if (named or refs) and any(w in bio for w in AMBASSADOR_WORDS):
            out.append(Evidence("ambassador_bio", None, "biography", weights.ambassador_bio))

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
        # Graph API вырезает «@» из подписи — ник бренда ищем и отдельным словом
        mentioned = (
            set(extract_mentions(caption)) | set(_words(caption))
        ) & brand.account_usernames
        if brand.account_pks & set(m.usertags or []) or mentioned:
            out.append(Evidence("usertag", m.media_pk, brand.name, weights.usertag))
        for article in sorted(set(extract_wb_articles(caption)) & brand.wb_articles):
            out.append(Evidence("wb_article", m.media_pk, article, weights.wb_article))
        for code in sorted(set(extract_ww_codes(caption)) & brand.ww_codes):
            out.append(Evidence("ww_code", m.media_pk, code, weights.wb_article))
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
        if e.kind in ARTICLE_KINDS:
            # Артикул WB или WW-код: вес за ролик, не больше заданного числа роликов
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
    if "ambassador_bio" in kinds or "bio_link" in kinds:
        return "ambassador"
    return "ugc"


def should_resurface(old: Sequence[Evidence], new: Sequence[Evidence]) -> bool:
    """Скрытый кандидат возвращается, только если появился новый сигнал весом ≥ 50."""
    known = {(e.kind, e.media_pk, e.value) for e in old}
    return any(
        e.weight >= RESURFACE_MIN_WEIGHT and (e.kind, e.media_pk, e.value) not in known for e in new
    )
