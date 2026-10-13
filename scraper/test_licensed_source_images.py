"""No source image without confirmed reuse rights, with automatic photo credit."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

import licensed_source_images as rights
import repair_generated_article_images as repair
import ensure_article_images as images
import preselect_library_images as preselect


SOURCE = "https://example.org/news/local-story"
PHOTO = "https://cdn.example.org/images/local-story.jpg"
LICENCE = "https://creativecommons.org/licenses/by/4.0/"


def photo_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (900, 540), (40, 50, 60)).save(stream, "JPEG", quality=90)
    return stream.getvalue()


def story() -> dict:
    return {
        "title": "Littleborough bakery opens on Church Street",
        "slug": "littleborough-bakery-church-street",
        "status": "published",
        "category": "business",
        "source_url": SOURCE,
        "published_at": "2026-10-13T10:00:00Z",
        "image_url": "assets/img/cards/littleborough-bakery-church-street-generated-card.jpg",
        "image_status": "cards-generated",
    }


def run() -> None:
    page = f"""<html><head>
    <meta property="og:image" content="{PHOTO}">
    <script type="application/ld+json">{json.dumps({
        "@type": "NewsArticle", "image": {
            "@type": "ImageObject",
            "contentUrl": PHOTO,
            "license": LICENCE,
            "creator": {"@type": "Person", "name": "A Local Photographer"},
        }
    })}</script></head></html>""".encode()

    parsed = rights.image_object_rights(page, SOURCE)
    assert parsed[rights.canonical(PHOTO)]["creator"] == "A Local Photographer"
    assert parsed[rights.canonical(PHOTO)]["license_name"] == "CC BY"
    assert rights.license_name("https://creativecommons.org/licenses/by-nc/4.0/") == ""
    assert rights.license_name("https://creativecommons.org/licenses/by-nd/4.0/") == ""
    assert rights.license_name("https://publisher.example.org/licence") == ""

    metadata_only = f'<meta property="og:image" content="{PHOTO}">'.encode()
    assert not rights.image_object_rights(metadata_only, SOURCE)
    assert rights.permitted_candidate(PHOTO, SOURCE, {}, {}) is None

    with TemporaryDirectory() as root:
        file = Path(root) / "permissions.json"
        file.write_text(json.dumps([
            {"image_url": PHOTO, "credit": "Photographer", "evidence_url": SOURCE,
             "permission_type": "explicit-publication-permission",
             "permission_verified": False},
        ]), encoding="utf-8")
        assert rights.permission_entries(file) == {}
        file.write_text(json.dumps([
            {"image_url": PHOTO, "credit": "Photographer", "evidence_url": SOURCE,
             "permission_type": "explicit-publication-permission",
             "permission_verified": True},
        ]), encoding="utf-8")
        assert rights.permission_entries(file)[rights.canonical(PHOTO)]["creator"] == "Photographer"

    jpeg = photo_bytes()
    def mock_request(url: str, **kwargs):
        if url == SOURCE:
            return page, "text/html", SOURCE
        if url == PHOTO:
            return jpeg, "image/jpeg", PHOTO
        raise AssertionError(url)

    with patch.object(rights, "request_bytes", side_effect=mock_request):
        photo = rights.fetch_licensed_source_image(SOURCE, permissions={})
        assert photo and photo[0].url == PHOTO and photo[3]["creator"] == "A Local Photographer"

    with patch.object(rights, "request_bytes", side_effect=lambda url, **kwargs: (
        (metadata_only, "text/html", SOURCE) if url == SOURCE else (jpeg, "image/jpeg", PHOTO)
    )):
        assert rights.fetch_licensed_source_image(SOURCE, permissions={}) is None

    with TemporaryDirectory() as root:
        base = Path(root)
        article = story()
        with patch.object(repair, "CARDS_DIR", base / "assets/img/cards"), \
             patch.object(repair, "fetch_licensed_source_image", return_value=photo):
            ok, reason = repair.try_licensed_source_photo(
                article, [SOURCE], timeout=1, permissions={}
            )
            assert ok and reason == "licensed-source-photo"
            assert (base / article["image_url"]).is_file()
            assert article["image_credit"] == "A Local Photographer / CC BY"
            assert article["image_license_url"] == LICENCE
            assert article["source_image_reuse_status"] == "verified-source-image-license"

        assert images.high_risk_photo_story({
            "title": "Missing woman appeal in Rochdale", "category": "news"
        })
        assert images.high_risk_photo_story({"title": "Suspect charged", "category": "crime"})
        assert not images.high_risk_photo_story(story())

        selected = story()
        library = base / "assets/img/cards/littleborough_bakery.jpg"
        library.parent.mkdir(parents=True, exist_ok=True)
        library.write_bytes(jpeg)
        assert preselect.preselect(selected, base) == "library-photo"
        assert selected["image_url"].endswith("littleborough_bakery.jpg")

        library_only = dict(story(), image_url=selected["image_url"],
                            image_status="cards-library-photo",
                            image_backfill_method="cards-filename-match")
        assert repair.needs_source_photo_check(
            library_only, datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        )
        assert not repair.needs_source_photo_check(
            dict(library_only, editorial_lock=True), datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        )

    print("Licensed source image discovery, attribution and library fallback passed.")


if __name__ == "__main__":
    run()
