from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.config import DiscoveryWeights
from core.discovery.confidence import (
    BrandRef,
    Evidence,
    Level,
    collect_evidence,
    level,
    link_type,
    score,
    should_resurface,
)
from parser.parse.models import IgMedia, IgProfile

W = DiscoveryWeights()
BRAND_PK = 900
BRAND = BrandRef(
    name="WAISTLINE",
    account_pks=frozenset({BRAND_PK}),
    account_usernames=frozenset({"waistline_shop"}),
    hashtags=frozenset({"waistline"}),
    wb_articles=frozenset({"847963328"}),
)


def media(pk: int, **kw: Any) -> IgMedia:
    base: dict[str, Any] = dict(
        media_pk=pk,
        shortcode=f"s{pk}",
        owner_user_pk=1,
        product_type="clips",
        media_type="video",
        taken_at=datetime(2026, 9, 1, tzinfo=UTC),
        caption=None,
        duration_s=None,
        is_pinned=False,
        coauthors=None,
        usertags=None,
        is_paid_partnership=None,
        sponsor_user_pks=None,
        audio_id=None,
        audio_title=None,
        is_original_audio=None,
        video_url=None,
        cover_url=None,
    )
    base.update(kw)
    return IgMedia(**base)


def profile(username: str = "anna", bio: str | None = None) -> IgProfile:
    return IgProfile(
        user_pk=1,
        username=username,
        full_name=None,
        biography=bio,
        external_url=None,
        followers_count=1,
        following_count=1,
        media_count=1,
        is_private=False,
        is_verified=False,
        is_business=False,
        category=None,
        avatar_url=None,
    )


def test_paid_partnership_plus_collab_is_confirmed() -> None:
    ev = collect_evidence(
        BRAND,
        profile(),
        [
            media(1, is_paid_partnership=True, sponsor_user_pks=[BRAND_PK]),
            media(2, coauthors=[BRAND_PK]),
        ],
        W,
    )
    assert {e.kind for e in ev} == {"paid_partnership", "collab"}
    c = score(ev, W)
    assert c == Decimal("1.000") and level(c) == Level.CONFIRMED
    assert link_type(ev) == "paid"


def test_tag_and_hashtag_is_possible() -> None:
    ev = collect_evidence(
        BRAND, profile(), [media(1, usertags=[BRAND_PK], caption="#WaistLine")], W
    )
    assert score(ev, W) == Decimal("0.400")
    assert level(score(ev, W)) == Level.POSSIBLE


def test_mention_counts_as_tag() -> None:
    ev = collect_evidence(BRAND, profile(), [media(1, caption="платье от @waistline_shop")], W)
    assert [e.kind for e in ev] == ["usertag"]


def test_brand_name_in_username_or_bio() -> None:
    assert (
        collect_evidence(BRAND, profile(username="anna_waist_line"), [], W)[0].kind == "brand_name"
    )
    assert (
        collect_evidence(BRAND, profile(bio="Амбассадор WAISTLINE"), [], W)[0].value == "biography"
    )
    assert (
        link_type(collect_evidence(BRAND, profile(username="waistline_msk"), [], W)) == "satellite"
    )


def test_wb_article_capped_at_two_media() -> None:
    medias = [media(i, caption="арт. 847963328") for i in range(5)]
    ev = collect_evidence(BRAND, None, medias, W)
    assert len(ev) == 5
    assert score(ev, W) == Decimal("0.600")  # 30 × 2


def test_brand_own_media_is_not_evidence() -> None:
    ev = collect_evidence(BRAND, None, [media(1, owner_user_pk=BRAND_PK, caption="#waistline")], W)
    assert ev == []


def test_duplicate_evidence_counted_once() -> None:
    e = Evidence("collab", 1, "WAISTLINE", 50)
    assert score([e, e], W) == Decimal("0.500")


def test_levels_boundaries() -> None:
    assert level(Decimal("0.9")) == Level.CONFIRMED
    assert level(Decimal("0.89")) == Level.LIKELY
    assert level(Decimal("0.6")) == Level.LIKELY
    assert level(Decimal("0.59")) == Level.POSSIBLE


def test_hidden_returns_only_on_new_strong_signal() -> None:
    old = [Evidence("collab", 1, "B", 50)]
    assert not should_resurface(old, [Evidence("collab", 1, "B", 50)])
    assert not should_resurface(old, [Evidence("usertag", 2, "B", 25)])
    assert should_resurface(old, [Evidence("collab", 2, "B", 50)])


def test_frequent_collab_is_ambassador() -> None:
    ev = [Evidence("collab", 1, "B", 50), Evidence("collab", 2, "B", 50)]
    assert link_type(ev) == "ambassador"


FIFTEEN = BrandRef(
    name="15.wear",
    account_pks=frozenset({1500}),
    account_usernames=frozenset({"15.wear"}),
    hashtags=frozenset(),
    ww_codes=frozenset({"WW336590"}),
    username_masks=("*onefive*", "*one_five*", "*1five*"),
    domains=frozenset({"15wear.ru"}),
)


def test_username_mask() -> None:
    ev = collect_evidence(FIFTEEN, profile(username="lera_onefive"), [], W)
    assert [(e.kind, e.value, e.weight) for e in ev] == [("username_mask", "*onefive*", 20)]
    assert collect_evidence(FIFTEEN, profile(username="pamela"), [], W) == []


def test_bio_link_and_ambassador_words() -> None:
    p = profile(username="anna", bio="Амбассадор бренда @15.wear 💛")
    kinds = {e.kind: e.weight for e in collect_evidence(FIFTEEN, p, [], W)}
    assert kinds == {"bio_link": 40, "ambassador_bio": 20}
    assert link_type(collect_evidence(FIFTEEN, p, [], W)) == "ambassador"


def test_brand_site_in_bio_links() -> None:
    p = profile(username="anna").model_copy(
        update={"bio_links": ["https://15wear.ru/?utm_source=ig"]}
    )
    assert [e.kind for e in collect_evidence(FIFTEEN, p, [], W)] == ["bio_link"]


def test_ambassador_word_alone_is_not_evidence() -> None:
    assert collect_evidence(FIFTEEN, profile(bio="амбассадор спорта"), [], W) == []


def test_ww_code_of_brand_counts_like_article() -> None:
    medias = [media(i, caption="#WW336590 размер S") for i in range(4)] + [
        media(9, caption="арт. 847963328")
    ]
    ev = collect_evidence(FIFTEEN, None, medias, W)
    assert {e.kind for e in ev} == {"ww_code"}
    assert score(ev, W) == Decimal("0.600")  # не больше 2 роликов с артикулами


def test_brand_mention_without_at_sign() -> None:
    """Graph API вырезает «@» из подписи: «спасибо waistline_shop» — всё равно отметка бренда."""
    ev = collect_evidence(BRAND, None, [media(1, caption="спасибо waistline_shop за платье")], W)
    assert [e.kind for e in ev] == ["usertag"]
