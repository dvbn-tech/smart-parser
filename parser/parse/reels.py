"""Разбор страницы ленты в формате API v1 (`items[]` + `paging_info`).

Лента Reels (`clips/user`) отдаёт `items[].media`, лента профиля (`feed/user`) —
`items[]` с роликом напрямую; разбор понимает оба вида.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from parser.parse import fields as f
from parser.parse.errors import InvalidResponse
from parser.parse.models import IgMedia, IgMetrics, ParsedItem, ReelsPage

_MEDIA_TYPES = {1: "image", 2: "video", 8: "carousel"}


def parse_reels_page(raw: Any, *, captured_at: datetime) -> ReelsPage:
    items = f.req_list(raw, "items")
    parsed = []
    for i, item in enumerate(items):
        node = item.get("media", item) if isinstance(item, dict) else item
        try:
            parsed.append(parse_media_item(node, captured_at=captured_at))
        except InvalidResponse as e:
            raise InvalidResponse(f"items[{i}].{e.path}", e.reason) from e

    paging = f.opt_dict(raw, "paging_info")
    if paging is not None:
        more = f.req_bool(paging, "more_available")
        cursor = f.opt_str(paging, "max_id")
    else:
        more = f.req_bool(raw, "more_available")
        cursor = f.opt_str(raw, "next_max_id")
    if more and cursor is None:
        raise InvalidResponse("paging_info.max_id", "more_available without cursor")
    return ReelsPage(items=parsed, next_cursor=cursor if more else None, more_available=more)


def parse_media_item(node: Any, *, captured_at: datetime) -> ParsedItem:
    media_pk = f.req_int(node, "pk")
    owner_pk = f.req_int(node, "user.pk")
    product_type = f.req_str(node, "product_type")
    media_type_code = f.req_int(node, "media_type")
    if media_type_code not in _MEDIA_TYPES:
        raise InvalidResponse("media_type", f"unknown code {media_type_code}")

    taken_ts = f.req_int(node, "taken_at")
    taken_at = datetime.fromtimestamp(taken_ts, tz=UTC)

    pinned_ids = (f.opt_list(node, "clips_tab_pinned_user_ids") or []) + (
        f.opt_list(node, "timeline_pinned_user_ids") or []
    )

    duration = node.get("video_duration")
    duration_s = Decimal(str(round(duration, 2))) if isinstance(duration, int | float) else None

    media = IgMedia(
        media_pk=media_pk,
        shortcode=f.req_str(node, "code"),
        owner_user_pk=owner_pk,
        owner_username=(f.opt_str(node, "user.username") or "").lower() or None,
        product_type=product_type,
        media_type=_MEDIA_TYPES[media_type_code],
        taken_at=taken_at,
        caption=f.opt_str(node, "caption.text"),
        duration_s=duration_s,
        # Instagram не присылает поле у незакреплённых: отсутствие = не закреплён
        is_pinned=owner_pk in {int(x) for x in pinned_ids},
        coauthors=_pks(node, "coauthor_producers", "pk"),
        usertags=_pks(node, "usertags.in", "user.pk"),
        is_paid_partnership=f.opt_bool(node, "is_paid_partnership"),
        sponsor_user_pks=_pks(node, "sponsor_tags", "sponsor.pk"),
        **_audio(node),
        video_url=_first_url(node, "video_versions"),
        cover_url=_first_url(node, "image_versions2.candidates"),
        **_details(node),
    )

    likes_hidden = f.opt_bool(node, "like_and_view_counts_disabled") is True
    comments_disabled = f.opt_bool(node, "comments_disabled") is True
    play_count = f.opt_int(node, "play_count")
    if play_count is None:
        play_count = f.opt_int(node, "ig_play_count")
    if media.is_reel and play_count is None:
        raise InvalidResponse("play_count", "required for Reels")

    metrics = IgMetrics(
        media_pk=media_pk,
        play_count=play_count,
        video_view_count=f.opt_int(node, "view_count"),
        fb_play_count=f.opt_int(node, "fb_play_count"),
        fb_like_count=f.opt_int(node, "fb_like_count"),
        like_count=None if likes_hidden else f.opt_int(node, "like_count"),
        comment_count=None if comments_disabled else f.opt_int(node, "comment_count"),
        reshare_count=f.opt_int(node, "reshare_count"),
        likes_hidden=likes_hidden,
        comments_disabled=comments_disabled,
        captured_at=captured_at,
    )
    return ParsedItem(media=media, metrics=metrics)


def _pks(node: Any, list_path: str, pk_path: str) -> list[int] | None:
    items = f.opt_list(node, list_path)
    if items is None:
        return None
    pks = [f.req_int(it, pk_path) for it in items]
    return pks or None


def _first_url(node: Any, list_path: str) -> str | None:
    items = f.opt_list(node, list_path)
    if not items:
        return None
    return f.opt_str(items[0], "url")


def _audio(node: Any) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "audio_id": None,
        "audio_title": None,
        "audio_artist": None,
        "audio_type": None,
        "is_original_audio": None,
    }
    clips = f.opt_dict(node, "clips_metadata")
    if clips is None:
        return empty
    audio_type = f.opt_str(clips, "audio_type")
    original = f.opt_dict(clips, "original_sound_info")
    if original is not None:
        return {
            "audio_id": f.opt_id_str(original, "audio_asset_id"),
            "audio_title": f.opt_str(original, "original_audio_title"),
            "audio_artist": f.opt_str(original, "ig_artist.username"),
            "audio_type": audio_type or "original_sounds",
            "is_original_audio": True,
        }
    music = f.opt_dict(clips, "music_info.music_asset_info")
    if music is not None:
        return {
            "audio_id": f.opt_id_str(music, "audio_cluster_id"),
            "audio_title": f.opt_str(music, "title"),
            "audio_artist": f.opt_str(music, "display_artist"),
            "audio_type": audio_type or "licensed_music",
            "is_original_audio": False,
        }
    return {**empty, "audio_type": audio_type}


def _details(node: Any) -> dict[str, Any]:
    """Необязательные подробности ролика. Нет поля — None, а не 0 и не пустая строка."""
    location = f.opt_dict(node, "location")
    mashup = f.opt_dict(node, "clips_metadata.mashup_info")
    remix_of = f.opt_int(mashup, "original_media.pk") if mashup else None
    lat = location.get("lat") if location else None
    lng = location.get("lng") if location else None
    caption = f.opt_dict(node, "caption")
    return {
        "has_audio": f.opt_bool(node, "has_audio"),
        "caption_is_edited": f.opt_bool(node, "caption_is_edited")
        if f.has(node, "caption_is_edited")
        else (f.opt_bool(caption, "is_edited") if caption else None),
        "accessibility_caption": f.opt_str(node, "accessibility_caption"),
        "location_pk": f.opt_int(location, "pk") if location else None,
        "location_name": f.opt_str(location, "name") if location else None,
        "location_lat": Decimal(str(round(lat, 6))) if isinstance(lat, int | float) else None,
        "location_lng": Decimal(str(round(lng, 6))) if isinstance(lng, int | float) else None,
        "width": f.opt_int(node, "original_width"),
        "height": f.opt_int(node, "original_height"),
        "remix_of_media_pk": remix_of,
        "is_shared_to_fb": f.opt_bool(node, "clips_metadata.is_shared_to_fb"),
        "carousel_media_count": f.opt_int(node, "carousel_media_count"),
        "commerciality_status": f.opt_str(node, "commerciality_status"),
        "is_in_profile_grid": f.opt_bool(node, "is_in_profile_grid"),
    }
