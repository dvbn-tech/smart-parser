from datetime import UTC, datetime
from decimal import Decimal

import pytest

from parser.parse.models import IgMedia
from parser.signals.extract import (
    BARE_NUMBER_CONFIDENCE,
    BRAND_HASHTAG_CONFIDENCE,
    KEYWORD_CONFIDENCE,
    Signal,
    extract_hashtags,
    extract_mentions,
    extract_signals,
    extract_wb_articles,
)


def test_hashtags_cyrillic_and_lowercase() -> None:
    assert extract_hashtags("#WW318221 #Платье_лето #outfit2026 и#нет") == [
        "ww318221",
        "платье_лето",
        "outfit2026",
    ]


def test_hashtag_html_entity_is_not_tag() -> None:
    assert extract_hashtags("&#128512; привет") == []


def test_mentions() -> None:
    assert extract_mentions("спасибо @Waistline_Shop и @brand.ru. Почта a@b.com") == [
        "waistline_shop",
        "brand.ru",
    ]


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("арт. 847963328", {"847963328": KEYWORD_CONFIDENCE}),
        ("Артикул: 12345678", {"12345678": KEYWORD_CONFIDENCE}),
        (
            "артикулы 123456789, 987654321",
            {"123456789": KEYWORD_CONFIDENCE, "987654321": KEYWORD_CONFIDENCE},
        ),
        ("art 55512345", {"55512345": KEYWORD_CONFIDENCE}),
        ("№ 7654321 на WB", {"7654321": KEYWORD_CONFIDENCE}),
        ("#WW318221", {"318221": BRAND_HASHTAG_CONFIDENCE}),
        ("смотри 412683058 на вб", {"412683058": BARE_NUMBER_CONFIDENCE}),
        ("арт 12345", {}),  # меньше 6 цифр
        ("арт 1234567890123", {}),  # больше 12 цифр
        ("звоните +79161234567", {}),  # телефон
        ("цена 1 299 000.50", {}),
        ("", {}),
    ],
)
def test_wb_articles(caption: str, expected: dict[str, Decimal]) -> None:
    assert extract_wb_articles(caption) == expected


def test_keyword_beats_bare_number() -> None:
    assert extract_wb_articles("арт. 847963328 ещё раз 847963328") == {
        "847963328": KEYWORD_CONFIDENCE
    }


def test_structural_signals() -> None:
    media = IgMedia(
        media_pk=1,
        shortcode="x",
        owner_user_pk=10,
        product_type="clips",
        media_type="video",
        taken_at=datetime(2026, 1, 1, tzinfo=UTC),
        caption="#brand @shop",
        duration_s=None,
        is_pinned=False,
        coauthors=[20],
        usertags=[30],
        is_paid_partnership=True,
        sponsor_user_pks=[40],
        audio_id=None,
        audio_title=None,
        is_original_audio=None,
        video_url=None,
        cover_url=None,
    )
    kinds = {(s.kind, s.value) for s in extract_signals(media)}
    assert kinds == {
        ("hashtag", "brand"),
        ("mention", "shop"),
        ("coauthor", "20"),
        ("usertag", "30"),
        ("sponsor", "40"),
    }
    assert all(isinstance(s, Signal) for s in extract_signals(media))
