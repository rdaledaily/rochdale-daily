"""Reader-first newsroom contract and useful local sitemap coverage."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from house_style import HOUSE_STYLE_SYSTEM
from reader_usefulness import READER_FIRST_POLICY, reader_questions_for
from generate_pages import locally_indexable_hub_urls
from generate_category_pages import render_category, CATEGORY_LABELS


def run() -> None:
    assert READER_FIRST_POLICY in HOUSE_STYLE_SYSTEM
    assert "Never guess" in READER_FIRST_POLICY
    assert "no more" not in READER_FIRST_POLICY  # not a rigid article structure

    traffic = " ".join(reader_questions_for("traffic", "live")).lower()
    assert "road" in traffic and "direction" in traffic
    assert "timestamped" in traffic
    council = " ".join(reader_questions_for("politics")).lower()
    assert "public money" in council and "response" in council
    crime = " ".join(reader_questions_for("crime")).lower()
    assert "convicted" in crime and "victims" in crime
    events = " ".join(reader_questions_for("events")).lower()
    assert "tickets" in events and "accessibility" in events
    assert reader_questions_for("mystery", "article")

    # Indexable hubs are discovered only when their actual canonical matches.
    with TemporaryDirectory() as directory:
        root = Path(directory)
        wards = root / "wards"
        wards.mkdir()
        (wards / "index.html").write_text(
            '<link rel="canonical" href="https://rochdaledaily.co.uk/wards/">',
            encoding="utf-8",
        )
        (wards / "west-heywood.html").write_text(
            '<meta name="robots" content="index,follow">'
            '<link rel="canonical" href="https://rochdaledaily.co.uk/wards/west-heywood.html">',
            encoding="utf-8",
        )
        (wards / "bad-preview.html").write_text(
            '<link rel="canonical" href="https://rochdaledaily.co.uk/">',
            encoding="utf-8",
        )
        (wards / "private.html").write_text(
            '<meta name="robots" content="noindex,follow">'
            '<link rel="canonical" href="https://rochdaledaily.co.uk/wards/private.html">',
            encoding="utf-8",
        )
        (root / "heywood.html").write_text(
            '<link rel="canonical" href="https://rochdaledaily.co.uk/heywood.html">',
            encoding="utf-8",
        )
        urls = locally_indexable_hub_urls(root)
        assert "https://rochdaledaily.co.uk/wards/" in urls
        assert "https://rochdaledaily.co.uk/wards/west-heywood.html" in urls
        assert "https://rochdaledaily.co.uk/heywood.html" in urls
        assert len(urls) == 3, urls

    assert CATEGORY_LABELS["news"] == "News"
    # Category pages must not say "News news".
    sample = render_category("news", [], ["news"], "")
    assert "Latest Rochdale borough news | Rochdale Daily" in sample, sample[:500]
    assert "News news" not in sample

    print("Reader-first template and locality SEO tests passed.")


if __name__ == "__main__":
    run()
