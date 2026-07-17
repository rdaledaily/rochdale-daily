from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ensure_article_images as mod


def test_existing_image_is_preserved() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = root / "assets/article-images/existing.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"x" * mod.MIN_IMAGE_BYTES)
        article = {"image_url": "assets/article-images/existing.jpg"}
        assert mod.has_real_image(article, root)


def test_placeholder_is_created_without_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        output = root / "assets/article-images"
        article = {
            "title": "Sample Rochdale story",
            "slug": "sample-rochdale-story",
            "category": "community",
            "area": "rochdale",
            "status": "published",
        }
        result = mod.ensure_article_image(
            article,
            repo_root=root,
            output_dir=output,
            timeout=1,
            sleep_seconds=0,
            retry_placeholders=False,
        )
        assert result == "placeholder"
        assert (root / article["image_url"]).is_file()
        assert article["image_credit"] == "Rochdale Daily"


def test_candidate_order_prefers_stored_source_image() -> None:
    article = {
        "source_url": "https://publisher.example/story",
        "source_image_candidate_url": "https://publisher.example/image.jpg",
        "rss_image_url": "https://publisher.example/rss.jpg",
    }
    candidates = mod.article_candidates(article)
    assert candidates[0].method == "source_image_candidate_url"


def test_run_gives_every_published_story_an_image() -> None:
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
            },
            {
                "title": "Two",
                "slug": "two",
                "status": "published",
                "category": "sport",
                "area": "heywood",
            },
        ]), encoding="utf-8")

        old_cwd = Path.cwd()
        try:
            import os
            os.chdir(root)
            rc = mod.main([
                "--articles", str(articles_path),
                "--output-dir", "assets/article-images",
                "--report", str(report_path),
            ])
        finally:
            os.chdir(old_cwd)

        assert rc == 0
        saved = json.loads(articles_path.read_text(encoding="utf-8"))
        assert all(item.get("image_url") for item in saved)
        assert all((root / item["image_url"]).is_file() for item in saved)


if __name__ == "__main__":
    failures = 0
    for test in (
        test_existing_image_is_preserved,
        test_placeholder_is_created_without_source,
        test_candidate_order_prefers_stored_source_image,
        test_run_gives_every_published_story_an_image,
    ):
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    raise SystemExit(1 if failures else 0)
