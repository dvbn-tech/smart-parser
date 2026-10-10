from datetime import UTC, datetime
from decimal import Decimal

from parser.parse.profile import parse_profile_timeline, parse_web_profile_info
from parser.parse.reels import parse_reels_page
from tests.factories import OWNER_PK, graphql_node, profile_response, reel_node, reels_page

NOW = datetime(2026, 10, 10, 1, 0, tzinfo=UTC)


def test_profile_extras() -> None:
    p = parse_web_profile_info(
        profile_response(
            pronouns=["she/her"],
            bio_links=[
                {"url": "https://t.me/line"},
                {"lynx_url": "https://wb.ru/x"},
                {"title": "без ссылки"},
            ],
            is_professional_account=True,
            business_category_name="Creators & Celebrities",
            highlight_reel_count=12,
            has_clips=True,
            fbid=17841400000000000,
        )
    )
    assert p.pronouns == ["she/her"]
    assert p.bio_links == ["https://t.me/line", "https://wb.ru/x"]
    assert p.is_professional is True and p.highlight_reel_count == 12
    assert p.business_category == "Creators & Celebrities"
    assert p.fbid == "17841400000000000"


def test_profile_extras_absent_are_null() -> None:
    p = parse_web_profile_info(profile_response())
    assert p.pronouns is None and p.bio_links is None and p.highlight_reel_count is None


def test_reel_details() -> None:
    node = reel_node(
        original_width=1080,
        original_height=1920,
        has_audio=True,
        caption_is_edited=True,
        location={"pk": 213385402, "name": "Москва", "lat": 55.7558, "lng": 37.6173},
        clips_metadata={
            "audio_type": "licensed_music",
            "music_info": {
                "music_asset_info": {
                    "audio_cluster_id": 77,
                    "title": "Hit",
                    "display_artist": "Artist",
                }
            },
            "mashup_info": {"original_media": {"pk": 123}},
            "is_shared_to_fb": True,
        },
        commerciality_status="commercial",
        fb_play_count=1500,
        view_count=99,
    )
    item = parse_reels_page(reels_page(node), captured_at=NOW).items[0]
    m, x = item.media, item.metrics
    assert (m.width, m.height, m.has_audio, m.caption_is_edited) == (1080, 1920, True, True)
    assert m.location_name == "Москва" and m.location_lat == Decimal("55.7558")
    assert (m.audio_type, m.audio_artist, m.audio_id) == ("licensed_music", "Artist", "77")
    assert m.remix_of_media_pk == 123 and m.is_shared_to_fb is True
    assert m.commerciality_status == "commercial"
    assert x.fb_play_count == 1500 and x.video_view_count == 99


def test_reel_details_absent_are_null() -> None:
    item = parse_reels_page(reels_page(reel_node()), captured_at=NOW).items[0]
    m = item.media
    assert m.location_name is None and m.width is None and m.remix_of_media_pk is None
    assert m.audio_type == "original_sounds"  # original_sound_info есть, audio_type нет
    assert item.metrics.fb_play_count is None


def test_profile_timeline_graphql() -> None:
    raw = profile_response(
        edge_owner_to_timeline_media={
            "count": 412,
            "edges": [
                {"node": graphql_node()},
                {
                    "node": graphql_node(
                        id="1",
                        shortcode="p1",
                        __typename="GraphImage",
                        is_video=False,
                        product_type=None,
                    )
                },
            ],
        }
    )
    items = parse_profile_timeline(raw, captured_at=NOW)
    reel, photo = items
    assert reel.media.is_reel and reel.media.owner_user_pk == OWNER_PK
    assert reel.media.caption == "Образ дня #waistline"
    assert reel.media.location_name == "Москва" and reel.media.usertags == [900]
    assert reel.media.is_original_audio is True and reel.media.audio_artist == "yaroslava_line"
    assert reel.metrics.like_count == 5100 and reel.metrics.comment_count == 77
    assert reel.metrics.play_count is None and reel.metrics.video_view_count == 88000
    assert photo.media.media_type == "image" and not photo.media.is_reel


def test_profile_timeline_hidden_likes() -> None:
    raw = profile_response(
        edge_owner_to_timeline_media={
            "count": 1,
            "edges": [{"node": graphql_node(like_and_view_counts_disabled=True)}],
        }
    )
    x = parse_profile_timeline(raw, captured_at=NOW)[0].metrics
    assert x.like_count is None and x.likes_hidden
