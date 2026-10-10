import json
from pathlib import Path

import httpx

from core.config import Settings
from parser.cli import normalize_username
from parser.poc import run_poc
from tests.factories import OWNER_PK, profile_response, reel_node, reels_page

SETTINGS = Settings(min_pause_between_requests_s=0, proxy_url=None)


def fake_instagram(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/v1/users/web_profile_info/":
        username = request.url.params["username"]
        if username == "ghost":
            return httpx.Response(404)
        if username == "closed":
            return httpx.Response(200, json=profile_response(is_private=True, username="closed"))
        return httpx.Response(200, json=profile_response(username=username))
    if path == "/api/v1/clips/user/":
        cursor = dict(httpx.QueryParams(request.content.decode())).get("max_id")
        if cursor is None:
            return httpx.Response(200, json=reels_page(reel_node(), cursor="p2"))
        return httpx.Response(200, json=reels_page(reel_node(pk="2", code="x2")))
    if path.startswith("/api/v1/usertags/"):
        return httpx.Response(
            302, headers={"location": "https://www.instagram.com/accounts/login/"}
        )
    if path == "/web/search/topsearch/":
        return httpx.Response(200, json={"users": [{"user": {"pk": 1}}]})
    return httpx.Response(500)


async def test_poc_end_to_end(tmp_path: Path) -> None:
    report = await run_poc(
        SETTINGS,
        ["yaroslava_line", "ghost", "closed"],
        tmp_path,
        max_pages=10,
        brand_query="waistline",
        transport=httpx.MockTransport(fake_instagram),
    )
    text = report.read_text()
    assert "| yaroslava_line | 4601217 | ok |" in text
    assert "| clips/user | 2 | 2 | 2 | да |" in text
    assert "| ghost |  | not_found |" in text
    assert "| closed |" in text and "private" in text
    assert "play_count у роликов | ≥ 95% | 100.0% (2/2)" in text
    assert "tagged: blocked: login_wall" in text
    assert "search: 200 ok, users=1" in text
    # ответы сохранены как есть — для библиотеки образцов
    saved = json.loads((tmp_path / "raw/yaroslava_line/0000-profile.json").read_text())
    assert saved["data"]["user"]["id"] == str(OWNER_PK)


async def test_poc_stops_on_repeated_blocks(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(429))
    report = await run_poc(
        SETTINGS,
        ["a", "b", "c", "d", "e"],
        tmp_path,
        max_pages=5,
        brand_query=None,
        transport=transport,
    )
    text = report.read_text()
    assert "Прогон остановлен" in text
    assert "| d |" not in text  # после трёх блокировок подряд дальше не идём


def test_normalize_username() -> None:
    assert normalize_username("https://www.instagram.com/Waistline_Shop/?hl=ru") == "waistline_shop"
    assert normalize_username("@Anna.K") == "anna.k"
    assert normalize_username("  # комментарий") is None
    assert normalize_username("") is None
