"""Ответы Business Discovery по документации Meta (v25.0) для тестов."""

from typing import Any

BIZ_ID = 17841400000000001  # id бизнес-аккаунта, от имени которого запрашиваем
TARGET_ID = 17841400000000777


def gmedia(
    shortcode: str, ts: str, *, views: int | None = 50_000, product: str = "REELS", **kw: Any
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": f"1790{abs(hash(shortcode)) % 10**12}",
        "shortcode": shortcode,
        "permalink": f"https://www.instagram.com/reel/{shortcode}/",
        "caption": "Образ дня WW336590 спасибо waistline_shop",
        "timestamp": ts,
        "media_type": "VIDEO",
        "media_product_type": product,
        "media_audio_type": "ORIGINAL_SOUND",
        "like_count": 1200,
        "comments_count": 34,
    }
    if views is not None:
        node["view_count"] = views
    node.update(kw)
    return node


def discovery(
    *media: dict[str, Any], after: str | None = None, username: str = "yaroslava_line"
) -> dict[str, Any]:
    page: dict[str, Any] = {"data": list(media)}
    if after:
        page["paging"] = {"cursors": {"before": "B", "after": after}}
    return {
        "business_discovery": {
            "id": str(TARGET_ID),
            "username": username,
            "name": "Ярослава",
            "biography": "амбассадор waistline",
            "website": "https://waistline.shop/?utm=ig",
            "followers_count": 120500,
            "follows_count": 310,
            "media_count": 412,
            "profile_picture_url": "https://cdn.example/a.jpg",
            "media": page,
        },
        "id": str(BIZ_ID),
    }


def graph_error(code: int, message: str, subcode: int | None = None) -> dict[str, Any]:
    return {
        "error": {
            "message": message,
            "type": "OAuthException",
            "code": code,
            "error_subcode": subcode,
        }
    }
