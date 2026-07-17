from __future__ import annotations

import json
import tempfile
from pathlib import Path

import backfill_article_images as mod


def test_placeholder_detection() -> None:
    assert mod.is_placeholder_image({"image_url": "assets/img/stock_crime.jpg"})
    assert mod.is_placeholder_image({
        "image_url": "x.jpg",
        "image_credit": "Rochdale Daily category image",
    })
    assert not mod.is_placeholder_image({
        "image_url": "assets/article-images/real.jpg",
        "image_credit": "Greater Manchester Police",
    })


def test_extracts_open_graph_first() -> None:
    page = b"""
    <html><head>
      <meta property="og:image" content="/lead.jpg">
      <meta name="twitter:image" content="/twitter.jpg">
    </head><body><article><img src="/body.jpg"></article></body></html>
    """
    candidates = mod.extract_candidates(page, "https://example.org/story")
    assert candidates[0].url == "https://example.org/lead.jpg"
    assert candidates[0].method == "og:image"


def test_source_credit_mapping() -> None:
    article = {
        "source_url": "https://first.example/a",
        "source_name": "First",
        "source_urls": ["https://first.example/a", "https://second.example/b"],
        "source_names": ["First", "Second"],
    }
    assert mod.source_name_for(article, "https://second.example/b") == "Second"


def test_dry_run_preserves_json_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "articles.json"
        article = [{
            "slug": "sample",
            "title": "Sample",
            "status": "published",
            "image_url": "assets/img/stock_news.jpg",
            "source_url": "",
        }]
        original = json.dumps(article)
        path.write_text(original, encoding="utf-8")
        report = root / "report.json"
        rc = mod.main([
            "--articles", str(path),
            "--report", str(report),
            "--limit", "1",
        ])
        assert rc == 0
        assert path.read_text(encoding="utf-8") == original
        assert report.exists()


if __name__ == "__main__":
    tests = [
        test_placeholder_detection,
        test_extracts_open_graph_first,
        test_source_credit_mapping,
        test_dry_run_preserves_json_file,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    raise SystemExit(1 if failures else 0)
