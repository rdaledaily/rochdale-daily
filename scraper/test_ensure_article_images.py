from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PIL import Image

import ensure_article_images as mod


def write_jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 450), (30, 40, 50)).save(path, format="JPEG")


def test_existing_matching_cards_image_is_preserved() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = root / "assets/img/cards/sample_rochdale_story.jpg"
        write_jpeg(image)
        article = {
            "title": "Sample Rochdale Story",
            "slug": "sample-rochdale-story",
            "image_url": "assets/img/cards/sample_rochdale_story.jpg",
            "status": "published",
        }
        assert mod.valid_cards_image(root, article["image_url"])
        assert mod.enforce_article(article, root) == "kept-cards"
        assert article["image_url"] == "assets/img/cards/sample_rochdale_story.jpg"


def test_unrelated_existing_cards_image_is_not_preserved() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = root / "assets/img/cards/gift_shop.jpg"
        write_jpeg(image)
        article = {
            "title": "Rochdale supporters travel to cup match",
            "slug": "rochdale-supporters-travel-to-cup-match",
            "category": "sport",
            "area": "rochdale",
            "status": "published",
            "image_url": "assets/img/cards/gift_shop.jpg",
        }
        result = mod.enforce_article(article, root)
        assert result == "cards-generated"
        assert article["image_url"].startswith("assets/img/cards/")
        assert "gift_shop" not in article["image_url"]


def test_non_cards_image_is_never_preserved() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = root / "assets/article-images/existing.jpg"
        write_jpeg(image)
        article = {
            "title": "Sample Rochdale story",
            "slug": "sample-rochdale-story",
            "category": "community",
            "area": "rochdale",
            "status": "published",
            "image_url": "assets/article-images/existing.jpg",
            "source_image_candidate_url": "https://example.invalid/photo.jpg",
        }
        result = mod.enforce_article(article, root)
        assert result == "cards-generated"
        assert article["image_url"].startswith("assets/img/cards/")
        assert (root / article["image_url"]).is_file()
        assert "source_image_candidate_url" not in article


def test_curated_cards_photo_matches_full_story_phrase() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        chosen = root / "assets/img/cards/rochdale_town_hall.jpg"
        write_jpeg(chosen)
        article = {
            "title": "Rochdale Town Hall restoration reaches milestone",
            "slug": "rochdale-town-hall-restoration-milestone",
            "category": "news",
            "area": "rochdale",
            "status": "published",
        }
        result = mod.enforce_article(article, root)
        assert result == "cards-library"
        assert article["image_url"] == "assets/img/cards/rochdale_town_hall.jpg"


def test_leading_the_filename_partially_matches_resilient_roach_project() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        chosen = root / "assets/img/cards/the_resilient_roach.jpg"
        write_jpeg(chosen)
        article = {
            "title": "Resilient Roach Project expands work across Rochdale",
            "slug": "resilient-roach-project-expands-work-across-rochdale",
            "category": "environment",
            "area": "rochdale",
            "status": "published",
        }
        result = mod.enforce_article(article, root)
        assert result == "cards-library"
        assert article["image_url"] == "assets/img/cards/the_resilient_roach.jpg"
        assert article["image_match_title"] == "the_resilient_roach.jpg"


def test_longest_filename_subject_wins() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        short = root / "assets/img/cards/roach.jpg"
        long = root / "assets/img/cards/resilient_roach.jpg"
        write_jpeg(short)
        write_jpeg(long)
        article = {
            "title": "Resilient Roach Project expands work across Rochdale",
            "slug": "resilient-roach-project-expands-work-across-rochdale",
            "category": "environment",
            "area": "rochdale",
            "status": "published",
        }
        result = mod.enforce_article(article, root)
        assert result == "cards-library"
        assert article["image_url"] == "assets/img/cards/resilient_roach.jpg"


def test_run_gives_every_published_story_a_cards_image() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        articles_path = root / "articles.json"
        report_path = root / "report.json"
        articles_path.write_text(json.dumps([
            {
                "title": "One",
                "slug": "one",
                "status": "published",
                "category": "news",
                "area": "rochdale",
                "image_url": "https://upload.wikimedia.org/example.jpg",
            },
            {
                "title": "Two",
                "slug": "two",
                "status": "published",
                "category": "sport",
                "area": "heywood",
                "image_url": "assets/article-images/two.jpg",
            },
        ]), encoding="utf-8")

        old_cwd = Path.cwd()
        try:
            os.chdir(root)
            rc = mod.main([
                "--articles", str(articles_path),
                "--report", str(report_path),
            ])
        finally:
            os.chdir(old_cwd)

        assert rc == 0
        saved = json.loads(articles_path.read_text(encoding="utf-8"))
        assert all(item["image_url"].startswith("assets/img/cards/") for item in saved)
        assert all((root / item["image_url"]).is_file() for item in saved)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["policy"] == "assets/img/cards only; filename matched against title, slug, excerpt and body"


if __name__ == "__main__":
    failures = 0
    for test in (
        test_existing_matching_cards_image_is_preserved,
        test_unrelated_existing_cards_image_is_not_preserved,
        test_non_cards_image_is_never_preserved,
        test_curated_cards_photo_matches_full_story_phrase,
        test_leading_the_filename_partially_matches_resilient_roach_project,
        test_longest_filename_subject_wins,
        test_run_gives_every_published_story_a_cards_image,
    ):
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    raise SystemExit(1 if failures else 0)
