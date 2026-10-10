from datetime import UTC, datetime

import pytest

from parser.parse.classify import Outcome
from parser.parse.errors import InvalidResponse
from parser.sources.graph import (
    graph_outcome,
    parse_discovery_media,
    parse_discovery_profile,
    shortcode_to_pk,
)
from tests.graph_factories import TARGET_ID, discovery, gmedia, graph_error

NOW = datetime(2026, 10, 11, 1, 0, tzinfo=UTC)


def test_shortcode_to_pk() -> None:
    assert shortcode_to_pk("A") == 0
    assert shortcode_to_pk("B") == 1
    assert shortcode_to_pk("BA") == 64
    assert shortcode_to_pk("C9xAbCdEfGh") == shortcode_to_pk("C9xAbCdEfGh")
    assert shortcode_to_pk("C9xAbCdEfGh") > 10**18


def test_profile() -> None:
    p = parse_discovery_profile(discovery())
    assert p.user_pk == TARGET_ID and p.username == "yaroslava_line"
    assert p.followers_count == 120500 and p.following_count == 310 and p.media_count == 412
    assert p.external_url == "https://waistline.shop/?utm=ig" and p.bio_links == [
        "https://waistline.shop/?utm=ig"
    ]
    assert p.is_private is False


def test_media_page() -> None:
    raw = discovery(
        gmedia("C9xAbCdEfGh", "2026-10-09T18:30:00+0000", views=2_400_000),
        gmedia(
            "C8photo0001",
            "2026-10-01T10:00:00+0000",
            product="FEED",
            media_type="IMAGE",
            views=None,
        ),
        gmedia("C7hidden001", "2026-09-30T10:00:00+0000", views=None, like_count=None),
        after="CURSOR2",
    )
    page = parse_discovery_media(raw, captured_at=NOW, page_size=3)
    reel, photo, hidden = page.items
    assert reel.media.is_reel and reel.media.media_pk == shortcode_to_pk("C9xAbCdEfGh")
    assert reel.media.taken_at == datetime(2026, 10, 9, 18, 30, tzinfo=UTC)
    assert reel.media.is_original_audio is True and reel.media.audio_type == "original_sounds"
    assert reel.metrics.play_count == 2_400_000 and reel.metrics.like_count == 1200
    assert not photo.media.is_reel and photo.metrics.play_count is None
    assert hidden.metrics.play_count is None and hidden.metrics.likes_hidden
    assert page.next_cursor == "CURSOR2" and page.more_available


def test_last_page_has_no_cursor() -> None:
    page = parse_discovery_media(
        discovery(gmedia("C1", "2026-10-09T18:30:00+0000"), after="X"),
        captured_at=NOW,
        page_size=50,
    )
    assert page.next_cursor is None and not page.more_available


def test_unknown_media_type_is_invalid() -> None:
    with pytest.raises(InvalidResponse):
        parse_discovery_media(
            discovery(gmedia("C1", "2026-10-09T18:30:00+0000", media_type="HOLOGRAM")),
            captured_at=NOW,
            page_size=50,
        )


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, discovery(), Outcome.OK),
        (400, graph_error(4, "Application request limit reached"), Outcome.RATE_LIMITED),
        (400, graph_error(17, "User request limit reached"), Outcome.RATE_LIMITED),
        (
            400,
            graph_error(190, "Error validating access token: Session has expired"),
            Outcome.AUTH_ERROR,
        ),
        (400, graph_error(100, "Invalid user id", 2207013), Outcome.NOT_FOUND),
        (429, None, Outcome.RATE_LIMITED),
        (500, None, Outcome.SERVER_ERROR),
    ],
)
def test_outcome(status: int, body: object, expected: Outcome) -> None:
    assert graph_outcome(status, body) == expected
