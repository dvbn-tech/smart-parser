"""Синтетические ответы в формате Instagram для юнит-тестов.

Это не замена библиотеке записанных ответов (≥ 30 реальных образцов в
tests/fixtures/responses): формат сверяется с ними после PoC.
"""

import copy
from typing import Any

OWNER_PK = 4601217
TAKEN_AT = 1780391640  # 2026-06-02T09:14:00Z


def reel_node(**overrides: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "pk": "3471298811234567",
        "id": f"3471298811234567_{OWNER_PK}",
        "code": "C9xAbCdEfGh",
        "user": {"pk": OWNER_PK, "username": "yaroslava_line"},
        "taken_at": TAKEN_AT,
        "product_type": "clips",
        "media_type": 2,
        "caption": {"text": "Больше интересного у меня в тг #WW318221 @waistline_shop"},
        "video_duration": 23.456,
        "play_count": 2400000,
        "like_count": 91400,
        "comment_count": 1830,
        "like_and_view_counts_disabled": False,
        "comments_disabled": False,
        "clips_metadata": {
            "original_sound_info": {
                "audio_asset_id": 987654321,
                "original_audio_title": "Original audio",
            }
        },
        "video_versions": [{"url": "https://cdn.example/v.mp4"}],
        "image_versions2": {"candidates": [{"url": "https://cdn.example/c.jpg"}]},
    }
    for key, value in overrides.items():
        if value is _DELETE:
            node.pop(key, None)
        else:
            node[key] = value
    return node


def reels_page(*nodes: dict[str, Any], cursor: str | None = None) -> dict[str, Any]:
    return {
        "items": [{"media": copy.deepcopy(n)} for n in nodes],
        "paging_info": {"max_id": cursor, "more_available": cursor is not None},
        "status": "ok",
    }


def profile_response(**user_overrides: Any) -> dict[str, Any]:
    user: dict[str, Any] = {
        "id": str(OWNER_PK),
        "username": "Yaroslava_Line",
        "full_name": "Ярослава",
        "biography": "амбассадор WAISTLINE",
        "external_url": None,
        "edge_followed_by": {"count": 120500},
        "edge_follow": {"count": 310},
        "edge_owner_to_timeline_media": {"count": 412},
        "is_private": False,
        "is_verified": False,
        "is_business_account": True,
        "category_name": "Blogger",
        "profile_pic_url_hd": "https://cdn.example/a.jpg",
    }
    user.update(user_overrides)
    return {"data": {"user": user}, "status": "ok"}


class _Delete:
    pass


_DELETE = _Delete()
DELETE: Any = _DELETE
