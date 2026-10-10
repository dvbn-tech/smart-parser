"""Разбор профиля из веб-эндпоинта web_profile_info (`{"data": {"user": {...}}}`)."""

from typing import Any

from parser.parse import fields as f
from parser.parse.errors import InvalidResponse
from parser.parse.models import IgProfile


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
    )


def is_profile_not_found(raw: Any) -> bool:
    """Пустой профиль (`data.user = null`) — аккаунт не найден, а не ошибка формата."""
    try:
        data = f.req_dict(raw, "data")
    except InvalidResponse:
        return False
    return "user" in data and data["user"] is None
