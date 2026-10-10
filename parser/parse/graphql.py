"""Разбор поста в формате GraphQL (блок edge_owner_to_timeline_media в ответе профиля)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from parser.parse import fields as f
from parser.parse.models import IgMedia, IgMetrics, ParsedItem

_TYPENAMES = {"GraphVideo": "video", "GraphImage": "image", "GraphSidecar": "carousel"}


def parse_graphql_node(node: Any, *, owner_pk: int, captured_at: datetime) -> ParsedItem:
    media_pk = f.req_int(node, "id")
    typename = f.req_str(node, "__typename")
    is_video = f.opt_bool(node, "is_video")
    product_type = f.opt_str(node, "product_type") or ("clips" if is_video else "feed")
    taken_at = datetime.fromtimestamp(f.req_int(node, "taken_at_timestamp"), tz=UTC)

    captions = f.opt_list(node, "edge_media_to_caption.edges") or []
    caption = f.opt_str(captions[0], "node.text") if captions else None
    pinned = f.opt_list(node, "pinned_for_users") or []
    music = f.opt_dict(node, "clips_music_attribution_info")
    location = f.opt_dict(node, "location")
    tagged = f.opt_list(node, "edge_media_to_tagged_user.edges") or []
    coauthors = [f.req_int(c, "id") for c in f.opt_list(node, "coauthor_producers") or []]
    sidecar = f.opt_list(node, "edge_sidecar_to_children.edges")
    duration = node.get("video_duration")

    media = IgMedia(
        media_pk=media_pk,
        shortcode=f.req_str(node, "shortcode"),
        owner_user_pk=f.opt_int(node, "owner.id") or owner_pk,
        owner_username=(f.opt_str(node, "owner.username") or "").lower() or None,
        product_type=product_type,
        media_type=_TYPENAMES.get(typename, "video" if is_video else "image"),
        taken_at=taken_at,
        caption=caption,
        duration_s=Decimal(str(round(duration, 2))) if isinstance(duration, int | float) else None,
        is_pinned=any(f.opt_id_str(p, "id") == str(owner_pk) for p in pinned),
        coauthors=coauthors or None,
        usertags=[f.req_int(t, "node.user.id") for t in tagged] or None,
        is_paid_partnership=f.opt_bool(node, "is_paid_partnership"),
        sponsor_user_pks=None,
        audio_id=f.opt_id_str(music, "audio_id") if music else None,
        audio_title=f.opt_str(music, "song_name") if music else None,
        audio_artist=f.opt_str(music, "artist_name") if music else None,
        is_original_audio=f.opt_bool(music, "uses_original_audio") if music else None,
        has_audio=f.opt_bool(node, "has_audio"),
        accessibility_caption=f.opt_str(node, "accessibility_caption"),
        location_pk=f.opt_int(location, "id") if location else None,
        location_name=f.opt_str(location, "name") if location else None,
        width=f.opt_int(node, "dimensions.width"),
        height=f.opt_int(node, "dimensions.height"),
        carousel_media_count=len(sidecar) if sidecar else None,
        video_url=f.opt_str(node, "video_url"),
        cover_url=f.opt_str(node, "display_url") or f.opt_str(node, "thumbnail_src"),
    )

    likes_hidden = f.opt_bool(node, "like_and_view_counts_disabled") is True
    comments_disabled = f.opt_bool(node, "comments_disabled") is True
    likes = f.opt_int(node, "edge_liked_by.count")
    if likes is None:
        likes = f.opt_int(node, "edge_media_preview_like.count")
    metrics = IgMetrics(
        media_pk=media_pk,
        play_count=f.opt_int(node, "video_play_count"),
        video_view_count=f.opt_int(node, "video_view_count"),
        like_count=None if likes_hidden else likes,
        comment_count=None if comments_disabled else f.opt_int(node, "edge_media_to_comment.count"),
        reshare_count=None,
        likes_hidden=likes_hidden,
        comments_disabled=comments_disabled,
        captured_at=captured_at,
    )
    return ParsedItem(media=media, metrics=metrics)
