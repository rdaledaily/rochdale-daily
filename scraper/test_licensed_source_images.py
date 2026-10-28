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

        # Remove the exact-slug source file before testing an independent
        # library subject match, which should otherwise rightly win.
        (base / article["image_url"]).unlink()
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

    run_source_grants(jpeg)
    print("Licensed source image discovery, attribution and library fallback passed.")


def run_source_grants(jpeg: bytes) -> None:
    """Organisation-level written permission (council, club, college...)."""
    council_page = "https://www.rochdale.gov.uk/news/article/1/park-reopens"
    council_photo = "https://www.rochdale.gov.uk/images/park-reopens.jpg"
    council_logo = "https://www.rochdale.gov.uk/images/council-logo.png"
    grant = {"permission_type": "source-publication-permission", "organisation": "Rochdale Borough Council",
             "credit": "Rochdale Borough Council", "source_hosts": ["rochdale.gov.uk"],
             "granted_by": "Press office, Rochdale Borough Council", "granted_on": "2026-10-20",
             "permission_verified": True}
    with TemporaryDirectory() as root:
        file = Path(root) / "permissions.json"
        # Incomplete evidence grants nothing, and is reported.
        file.write_text(json.dumps([dict(grant, granted_on="")]), encoding="utf-8")
        assert rights.source_grants(file) == []
        assert rights.inactive_grants(file) == ["Rochdale Borough Council"]
        file.write_text(json.dumps([grant]), encoding="utf-8")
        grants = rights.source_grants(file)
        assert len(grants) == 1 and rights.inactive_grants(file) == []

    got = rights.grant_for(council_photo, council_page, grants)
    assert got and got["creator"] == "Rochdale Borough Council" and got["license_name"] == "Used with permission"
    assert "2026-10-20" in got["evidence_ref"]
    # Image on another domain, page on another domain, logo: never covered.
    assert rights.grant_for("https://cdn.getty.example/x.jpg", council_page, grants) is None
    assert rights.grant_for(council_photo, "https://www.manchestereveningnews.co.uk/a", grants) is None
    assert rights.grant_for(council_logo, council_page, grants) is None
    assert rights.grant_for(council_photo, "https://democracy.rochdale.gov.uk/x", grants)  # subdomain ok
    # Per-grant category exclusion.
    excl = [dict(grants[0], exclude_categories={"crime"})]
    assert rights.grant_for(council_photo, council_page, excl, "crime") is None

    page = f'''<html><head><meta property="og:image" content="{council_photo}"></head>
      <body><article><figure><img src="{council_photo}"><figcaption>The reopened park</figcaption></figure></article></body></html>'''.encode()
    agency = page.replace(b"The reopened park", b"Photo: Getty Images")
    def fake(pages):
        return lambda url, **kw: (pages, "text/html", council_page) if url == council_page else (jpeg, "image/jpeg", council_photo)
    with patch.object(rights, "request_bytes", side_effect=fake(page)):
        got = rights.fetch_licensed_source_image(council_page, permissions={}, grants=grants)
        assert got and got[3]["creator"] == "Rochdale Borough Council"
        # The same picture already used on a different story = default share image.
        assert rights.fetch_licensed_source_image(council_page, permissions={}, grants=grants,
                                                  skip_urls={rights.canonical(council_photo)}) is None
        # No grant, no photo.
        assert rights.fetch_licensed_source_image(council_page, permissions={}, grants=[]) is None
    with patch.object(rights, "request_bytes", side_effect=fake(agency)):
        assert rights.fetch_licensed_source_image(council_page, permissions={}, grants=grants) is None

    # A recent council story carrying a Commons/library image is upgraded;
    # editor photos, locked stories, old stories and other sources are not.
    now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    recent = {"source_url": council_page, "category": "community", "published_at": "2026-10-27T09:00:00Z",
              "image_status": "commons-photo-cached", "image_url": "assets/img/cards/x-commons-photo.jpg"}
    assert repair.granted_source_upgrade(recent, now, grants)
    assert not repair.granted_source_upgrade(dict(recent, image_status="editorial-photo"), now, grants)
    assert not repair.granted_source_upgrade(dict(recent, manual_article=True), now, grants)
    assert not repair.granted_source_upgrade(dict(recent, published_at="2026-10-01T09:00:00Z"), now, grants)
    assert not repair.granted_source_upgrade(dict(recent, source_url="https://www.rochdaletimes.co.uk/a"), now, grants)
    assert not repair.granted_source_upgrade(recent, now, [])

    # Credit names the organisation and links to its original story.
    with TemporaryDirectory() as root:
        base = Path(root)
        article = dict(story(), source_url=council_page)
        result = (rights.Candidate(council_photo, "og:image"), jpeg, ".jpg",
                  rights.grant_for(council_photo, council_page, grants))
        with patch.object(repair, "CARDS_DIR", base / "assets/img/cards"), \
             patch.object(repair, "fetch_licensed_source_image", return_value=result):
            ok, _ = repair.try_licensed_source_photo(article, [council_page], timeout=1,
                                                      permissions={}, grants=grants)
        assert ok
        assert article["image_credit"] == "Rochdale Borough Council / Used with permission"
        assert article["image_credit_url"] == council_page
        assert "2026-10-20" in article["image_permission_ref"]


if __name__ == "__main__":
    run()


def run_manual_credit_survives_rebuild() -> None:
    """A manual story is rebuilt from the editor's file every run; the
    permitted source photo and its organisation credit must survive that."""
    import os
    import image_hierarchy
    page = "https://www.rochdale.gov.uk/news/article/9/half-term"
    photo = "https://www.rochdale.gov.uk/images/half-term.jpg"
    grants = [{"organisation": "Rochdale Borough Council", "source_hosts": ["rochdale.gov.uk"],
               "image_hosts": ["rochdale.gov.uk"], "credit": "Rochdale Borough Council",
               "granted_by": "Press office", "granted_on": "2026-10-20", "exclude_categories": set()}]
    stream = io.BytesIO()
    Image.effect_noise((1200, 675), 64).convert("RGB").save(stream, "JPEG", quality=95)
    result = (rights.Candidate(photo, "og:image"), stream.getvalue(), ".jpg", rights.grant_for(photo, page, grants))
    here = os.getcwd()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "assets/img/cards").mkdir(parents=True)
        os.chdir(root)
        try:
            for run in (1, 2):
                article = {"manual_article": True, "editorial_lock": True, "source_kind": "editorial",
                           "status": "published", "category": "education",
                           "title": "Rochdale October half-term 2026: school dates",
                           "slug": "rochdale-october-half-term-2026", "source_url": page,
                           "image_url": "assets/img/cards/community.jpg"}
                with patch.object(repair, "CARDS_DIR", Path("assets/img/cards")), \
                     patch.object(repair, "fetch_licensed_source_image", return_value=result) as fetch:
                    _, reason = repair.try_licensed_source_photo(article, [page], timeout=1,
                                                                 permissions={}, grants=grants)
                with patch.object(image_hierarchy, "commons_search",
                                  return_value={"status": "service-unavailable", "pages": []}):
                    images.enforce_article(article, root)
                assert article["image_url"] == "assets/img/cards/rochdale-october-half-term-2026.jpg", article
                assert article["image_credit"] == "Rochdale Borough Council / Used with permission", article
                assert fetch.called == (run == 1), reason
        finally:
            os.chdir(here)


run_manual_credit_survives_rebuild()


def run_uncredited_cached_photo_is_healed() -> None:
    """A permitted photo cached before credits were recorded gets its credit back."""
    import os
    import image_hierarchy
    page = "https://www.rbh.org.uk/news/rbh-news/representative-body-update/"
    photo = "https://www.rbh.org.uk/media/rep-body.jpg"
    grants = [{"organisation": "RBH", "source_hosts": ["rbh.org.uk"], "image_hosts": ["rbh.org.uk"],
               "credit": "Rochdale Boroughwide Housing", "granted_by": "Press office",
               "granted_on": "2026-10-20", "exclude_categories": set()}]
    stream = io.BytesIO()
    Image.effect_noise((1200, 675), 64).convert("RGB").save(stream, "JPEG", quality=95)
    payload = stream.getvalue()
    here = os.getcwd()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        cards = root / "assets/img/cards"
        cards.mkdir(parents=True)
        (cards / "rbh-rep-body.jpg").write_bytes(payload)  # cached earlier, no credit recorded
        os.chdir(root)
        try:
            article = {"status": "published", "category": "community", "title": "RBH updates on Representative Body",
                       "slug": "rbh-rep-body", "source_url": page, "image_url": "assets/img/cards/rbh-rep-body.jpg",
                       "image_credit": "Rochdale Daily", "image_status": "cards-library-photo"}
            result = (rights.Candidate(photo, "og:image"), payload, ".jpg", rights.grant_for(photo, page, grants))
            with patch.object(repair, "CARDS_DIR", Path("assets/img/cards")), \
                 patch.object(repair, "fetch_licensed_source_image", return_value=result):
                ok, _ = repair.try_licensed_source_photo(article, [page], timeout=1, permissions={}, grants=grants)
            assert ok and article["image_credit"] == "Rochdale Boroughwide Housing / Used with permission"
            with patch.object(image_hierarchy, "commons_search", return_value={"status": "service-unavailable", "pages": []}):
                images.enforce_article(article, root)
            assert article["image_credit"] == "Rochdale Boroughwide Housing / Used with permission", article
            # A DIFFERENT existing file (an editor's) is never overwritten or re-credited.
            editor_bytes = payload + b"editor"
            (cards / "rbh-rep-body.jpg").write_bytes(editor_bytes)
            other = dict(article, slug="rbh-rep-body", image_credit="Rochdale Daily")
            with patch.object(repair, "CARDS_DIR", Path("assets/img/cards")), \
                 patch.object(repair, "fetch_licensed_source_image", return_value=result):
                ok, _ = repair.try_licensed_source_photo(other, [page], timeout=1, permissions={}, grants=grants)
            assert (cards / "rbh-rep-body.jpg").read_bytes() == editor_bytes
        finally:
            os.chdir(here)


run_uncredited_cached_photo_is_healed()
