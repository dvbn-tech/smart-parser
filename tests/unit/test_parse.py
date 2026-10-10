from datetime import UTC, datetime
from decimal import Decimal

import pytest

from parser.parse.classify import Outcome, classify
from parser.parse.errors import InvalidResponse
from parser.parse.profile import is_profile_not_found, parse_web_profile_info
from parser.parse.reels import parse_reels_page
from tests.factories import DELETE, OWNER_PK, profile_response, reel_node, reels_page

NOW = datetime(2026, 10, 10, 1, 0, tzinfo=UTC)


def parse_one(**overrides: object):  # type: ignore[no-untyped-def]
    page = parse_reels_page(reels_page(reel_node(**overrides)), captured_at=NOW)
    return page.items[0]


class TestProfile:
    def test_full_profile(self) -> None:
        p = parse_web_profile_info(profile_response())
        assert p.user_pk == OWNER_PK
        assert p.username == "yaroslava_line"  # нижний регистр
        assert p.followers_count == 120500
        assert p.external_url is None
        assert p.is_business is True

    def test_missing_required_field_is_invalid(self) -> None:
        raw = profile_response()
        del raw["data"]["user"]["edge_followed_by"]
        with pytest.raises(InvalidResponse, match=r"edge_followed_by\.count"):
            parse_web_profile_info(raw)

    def test_wrong_type_is_invalid(self) -> None:
        with pytest.raises(InvalidResponse):
            parse_web_profile_info(profile_response(is_private="false"))

    def test_empty_optional_is_null_not_empty_string(self) -> None:
        assert parse_web_profile_info(profile_response(biography="  ")).biography is None

    def test_not_found(self) -> None:
        assert is_profile_not_found({"data": {"user": None}, "status": "ok"})
        assert not is_profile_not_found(profile_response())

    def test_text_normalized_nfc(self) -> None:
        decomposed = "й"  # и + кратка
        p = parse_web_profile_info(profile_response(full_name=decomposed))
        assert p.full_name == "й"


class TestReels:
    def test_reel_fields(self) -> None:
        item = parse_one()
        m, x = item.media, item.metrics
        assert m.media_pk == 3471298811234567
        assert m.owner_user_pk == OWNER_PK
        assert m.taken_at == datetime(2026, 6, 2, 9, 14, tzinfo=UTC)
        assert m.is_reel and m.media_type == "video"
        assert m.duration_s == Decimal("23.46")
        assert m.audio_id == "987654321" and m.is_original_audio is True
        assert m.is_pinned is False
        assert x.play_count == 2400000 and x.like_count == 91400

    def test_hidden_likes_are_null_not_zero(self) -> None:
        x = parse_one(like_and_view_counts_disabled=True, like_count=0).metrics
        assert x.like_count is None and x.likes_hidden is True

    def test_comments_disabled(self) -> None:
        x = parse_one(comments_disabled=True, comment_count=0).metrics
        assert x.comment_count is None and x.comments_disabled is True

    def test_reel_without_play_count_is_invalid(self) -> None:
        with pytest.raises(InvalidResponse, match=r"items\[0\]\.play_count"):
            parse_one(play_count=DELETE)

    def test_ig_play_count_fallback(self) -> None:
        assert parse_one(play_count=DELETE, ig_play_count=5).metrics.play_count == 5

    def test_photo_without_play_count_is_ok(self) -> None:
        item = parse_one(product_type="feed", media_type=1, play_count=DELETE)
        assert not item.media.is_reel and item.metrics.play_count is None

    def test_pinned(self) -> None:
        assert parse_one(clips_tab_pinned_user_ids=[OWNER_PK]).media.is_pinned

    def test_collab_usertags_partnership(self) -> None:
        m = parse_one(
            coauthor_producers=[{"pk": 111}],
            usertags={"in": [{"user": {"pk": 222}}, {"user": {"pk": "333"}}]},
            is_paid_partnership=True,
            sponsor_tags=[{"sponsor": {"pk": 444}}],
        ).media
        assert m.coauthors == [111]
        assert m.usertags == [222, 333]
        assert m.is_paid_partnership is True and m.sponsor_user_pks == [444]

    def test_licensed_music(self) -> None:
        m = parse_one(
            clips_metadata={
                "music_info": {"music_asset_info": {"audio_cluster_id": "55", "title": "Hit"}}
            }
        ).media
        assert (m.audio_id, m.audio_title, m.is_original_audio) == ("55", "Hit", False)

    def test_unknown_media_type_is_invalid(self) -> None:
        with pytest.raises(InvalidResponse):
            parse_one(media_type=99)

    def test_pagination(self) -> None:
        page = parse_reels_page(reels_page(reel_node(), cursor="QVFE"), captured_at=NOW)
        assert page.more_available and page.next_cursor == "QVFE"
        last = parse_reels_page(reels_page(reel_node()), captured_at=NOW)
        assert not last.more_available and last.next_cursor is None

    def test_more_available_without_cursor_is_invalid(self) -> None:
        raw = reels_page(reel_node())
        raw["paging_info"]["more_available"] = True
        with pytest.raises(InvalidResponse):
            parse_reels_page(raw, captured_at=NOW)

    def test_feed_format_without_media_wrapper(self) -> None:
        raw = {"items": [reel_node()], "more_available": False}
        assert len(parse_reels_page(raw, captured_at=NOW).items) == 1


class TestClassify:
    @pytest.mark.parametrize(
        ("status", "location", "body", "expected"),
        [
            (200, None, {"status": "ok"}, Outcome.OK),
            (429, None, None, Outcome.RATE_LIMITED),
            (302, "https://www.instagram.com/accounts/login/?next=", None, Outcome.LOGIN_WALL),
            (401, None, None, Outcome.LOGIN_WALL),
            (200, None, {"message": "checkpoint_required"}, Outcome.LOGIN_WALL),
            (
                400,
                None,
                {"message": "Please wait a few minutes before you try again."},
                Outcome.LOGIN_WALL,
            ),
            (200, None, {"require_login": True}, Outcome.LOGIN_WALL),
            (404, None, None, Outcome.NOT_FOUND),
            (503, None, None, Outcome.SERVER_ERROR),
        ],
    )
    def test_classify(
        self, status: int, location: str | None, body: object, expected: Outcome
    ) -> None:
        assert classify(status, location, body) == expected
