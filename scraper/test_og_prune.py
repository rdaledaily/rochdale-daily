"""Share-image crops: never crop a crop, and remove crops nothing points at.
Run: python -m pytest -q scraper/test_og_prune.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_data_files
import og_images as og
from PIL import Image


def site(tmp_path):
    (tmp_path / "assets/img/cards").mkdir(parents=True)
    (tmp_path / "articles").mkdir()
    Image.new("RGB", (1600, 900), (20, 60, 90)).save(tmp_path / "assets/img/cards/town-hall.jpg")
    og._cache.clear()
    return tmp_path


def crops(root):
    return sorted(p.name for p in (root / og.OUT_DIR).iterdir())


def test_a_crop_is_never_cropped_again(tmp_path):
    root = site(tmp_path)
    first = og.variants("assets/img/cards/town-hall.jpg", root)
    assert [c["ratio"] for c in first] == ["1200x675", "1200x900", "1200x1200"] and len(crops(root)) == 3
    # A post-processor reads og:image back from the page and asks again, run after run.
    url = first[0]["url"]
    for _ in range(4):
        og._cache.clear()
        again = og.variants(url, root)
        assert again == first
        url = again[0]["url"]
    og._cache.clear()
    assert og.variants("https://rochdaledaily.co.uk/" + first[2]["url"], root) == first
    assert len(crops(root)) == 3
    assert [u for u, _, _ in og.image_set(first[1]["url"], root)] == [og.absolute(c["url"]) for c in first]


def test_a_lone_crop_is_used_as_it_is(tmp_path):
    root = site(tmp_path)
    first = og.variants("assets/img/cards/town-hall.jpg", root)
    (root / first[1]["url"]).unlink()
    og._cache.clear()
    assert og.variants(first[0]["url"], root) == []
    assert og.image_set(first[0]["url"], root) == [(og.absolute(first[0]["url"]), 1200, 675)]
    assert len(crops(root)) == 2


def test_unused_crops_are_removed_and_used_ones_kept(tmp_path):
    root = site(tmp_path)
    used = og.variants("assets/img/cards/town-hall.jpg", root)
    for name in ("old-story-aaaaaaaaaa-1200x675.jpg", "town-hall-bbbbbbbbbb-1200x675-cccccccccc-1200x675.jpg", "it&s a name-dddddddddd-1200x900.jpg"):
        Image.new("RGB", (8, 8)).save(root / og.OUT_DIR / name)
    page = "".join(f'<meta property="og:image" content="https://rochdaledaily.co.uk/{c["url"]}">' for c in used[:2])
    (root / "articles/story.html").write_text(page + '<img src="/assets/img/og/it&amp;s%20a%20name-dddddddddd-1200x900.jpg">', encoding="utf-8")
    (root / "articles.json").write_text('[{"image_url": "%s"}]' % used[2]["url"], encoding="utf-8")
    assert og.prune_unreferenced(root) == {"kept": 4, "removed": 2}
    assert crops(root) == sorted([c["url"].rsplit("/", 1)[1] for c in used] + ["it&s a name-dddddddddd-1200x900.jpg"])
    assert og.prune_unreferenced(root) == {"kept": 4, "removed": 0}


def test_nothing_is_removed_when_no_page_could_be_read(tmp_path):
    root = site(tmp_path)
    og.variants("assets/img/cards/town-hall.jpg", root)
    assert og.prune_unreferenced(root) == {"kept": 3, "removed": 0}
    assert og.prune_unreferenced(tmp_path / "missing") == {"kept": 0, "removed": 0}


def test_file_count_alarm(tmp_path, monkeypatch):
    for i in range(12):
        (tmp_path / "assets/img/og").mkdir(parents=True, exist_ok=True)
        (tmp_path / f"assets/img/og/{i}.jpg").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/ignored").write_text("x")
    total, largest = check_data_files.site_file_count(tmp_path)
    assert total == 12 and largest[0] == (12, "assets/img/og")
    monkeypatch.setattr(check_data_files, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_data_files, "FILE_COUNT_ERROR", 10)
    check_data_files.problems.clear()
    check_data_files.check_file_count()
    assert len(check_data_files.problems) == 1 and "Cloudflare Pages stops deploying" in check_data_files.problems[0]
    check_data_files.problems.clear()
