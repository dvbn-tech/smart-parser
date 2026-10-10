from parser.raw.fingerprint import fingerprint, key_paths, missing_paths
from tests.factories import reel_node, reels_page


def test_paths_collapse_arrays() -> None:
    assert key_paths({"a": [{"b": 1}, {"c": 2}], "d": None}) == {"a", "a[].b", "a[].c", "d"}


def test_same_shape_same_fingerprint() -> None:
    assert fingerprint(reels_page(reel_node(play_count=1))) == fingerprint(
        reels_page(reel_node(play_count=999), reel_node(like_count=5))
    )


def test_new_field_changes_fingerprint() -> None:
    assert fingerprint(reels_page(reel_node())) != fingerprint(reels_page(reel_node(new_field=1)))


def test_missing_required_path() -> None:
    raw = reels_page(reel_node())
    del raw["paging_info"]
    assert missing_paths(raw, {"items", "paging_info.more_available"}) == {
        "paging_info.more_available"
    }
