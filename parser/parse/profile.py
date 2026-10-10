"""Разбор профиля из веб-эндпоинта web_profile_info (`{"data": {"user": {...}}}`)."""

from datetime import datetime
from typing import Any

from parser.parse import fields as f
from parser.parse.errors import InvalidResponse
from parser.parse.graphql import parse_graphql_node
from parser.parse.models import IgProfile, ParsedItem


def parse_web_profile_info(raw: Any) -> IgProfile:
    user = f.req_dict(raw, "data.user")
    username = f.req_str(user, "username").lower()
    return IgProfile(
        user_pk=f.req_int(user, "id"),
        username=username,
        full_name=f.opt_str(user, "full_name"),
        biography=f.opt_str(user, "biography"),
        external_url=f.opt_str(user, "external_url"),
        followers_count=f.req_int(user, "edge_followed_by.count"),
        following_count=f.req_int(user, "edge_follow.count"),
        media_count=f.req_int(user, "edge_owner_to_timeline_media.count"),
        is_private=f.req_bool(user, "is_private"),
        is_verified=f.req_bool(user, "is_verified"),
        is_business=f.req_bool(user, "is_business_account"),
        category=f.opt_str(user, "category_name"),
        avatar_url=f.opt_str(user, "profile_pic_url_hd") or f.opt_str(user, "profile_pic_url"),
        pronouns=_strings(f.opt_list(user, "pronouns")),
        bio_links=_bio_links(user),
        is_professional=f.opt_bool(user, "is_professional_account"),
        business_category=f.opt_str(user, "business_category_name"),
        highlight_reel_count=f.opt_int(user, "highlight_reel_count"),
        has_clips=f.opt_bool(user, "has_clips"),
        hide_like_and_view_counts=f.opt_bool(user, "hide_like_and_view_counts"),
        fbid=f.opt_id_str(user, "fbid"),
        transparency_label=f.opt_str(user, "transparency_label"),
    )


def _strings(items: list[Any] | None) -> list[str] | None:
    out = [x.strip() for x in items or [] if isinstance(x, str) and x.strip()]
    return out or None


def _bio_links(user: Any) -> list[str] | None:
    links = f.opt_list(user, "bio_links") or []
    urls = [f.opt_str(link, "url") or f.opt_str(link, "lynx_url") for link in links]
    return [u for u in urls if u] or None


def parse_profile_timeline(raw: Any, *, captured_at: datetime) -> list[ParsedItem]:
    """12 последних постов, которые web_profile_info отдаёт вместе с профилем (формат GraphQL).

    Просмотров Reels (play_count) здесь обычно нет — ролики из этого блока дают
    метаданные и лайки / комментарии, а снимок просмотров пишется только из ленты.
    """
    user = f.req_dict(raw, "data.user")
    edges = f.opt_list(user, "edge_owner_to_timeline_media.edges") or []
    owner_pk = f.req_int(user, "id")
    out = []
    for i, edge in enumerate(edges):
        try:
            out.append(
                parse_graphql_node(
                    f.req_dict(edge, "node"), owner_pk=owner_pk, captured_at=captured_at
                )
            )
        except InvalidResponse as e:
            raise InvalidResponse(f"timeline[{i}].{e.path}", e.reason) from e
    return out


def is_profile_not_found(raw: Any) -> bool:
    """Пустой профиль (`data.user = null`) — аккаунт не найден, а не ошибка формата."""
    try:
        data = f.req_dict(raw, "data")
    except InvalidResponse:
        return False
    return "user" in data and data["user"] is None
