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

    # 6 Nov 2026: the hourly limit-8 pass spent every slot on roadworks
    # directory records and other publishers' pages, so council press releases
    # (foster carers, 26 Oct) aged out unchecked. Pages that can never hold a
    # story photo are skipped, and a granted story still on a generated card
    # within GRANT_BACKLOG_DAYS is in the backlog.
    roadworks = "https://www.rochdale.gov.uk/directory-record/12345/roadworks-on-x"
    assert repair.grant_pages({"source_url": roadworks}, grants) == []
    assert repair.grant_pages({"source_url": council_page}, grants) == [council_page]
    assert repair.grant_pages({"source_url": "https://www.rochdale.gov.uk/"}, grants) == []
    carded = dict(recent, image_status="place-generated-card",
                  image_url="assets/img/cards/x-place-generated-card.jpg", published_at="2026-10-26T09:00:00Z")
    assert repair.grant_backlog(carded, now, grants)
    assert not repair.grant_backlog(dict(carded, source_url=roadworks), now, grants)
    assert not repair.grant_backlog(dict(carded, image_status="source-photo-cached"), now, grants)
    assert not repair.grant_backlog(dict(carded, published_at="2026-10-01T09:00:00Z"), now, grants)

    # Standing rule: a manual council story whose own file names no photo gets
    # the council's photo in place of the pipeline's library pick, at any age.
    # An editor-supplied photo, or one already fetched, is never replaced.
    with TemporaryDirectory() as root:
        cards = Path(root) / "assets/img/cards"
        cards.mkdir(parents=True)
        manual = dict(recent, slug="council-park-story", manual_article=True, editorial_lock=True,
                      image_status="editorial-photo", image_url="assets/img/cards/parking_restrictions.jpg",
                      published_at="2026-09-01T09:00:00Z")
        with patch.object(repair, "CARDS_DIR", cards):
            assert repair.granted_source_upgrade(manual, now, grants, set())
            assert not repair.granted_source_upgrade(manual, now, grants, {"council-park-story"})
            assert not repair.granted_source_upgrade(manual, now, grants, None)
            assert not repair.granted_source_upgrade(dict(manual, source_url="https://www.rochdaletimes.co.uk/a"),
                                                     now, grants, set())
            (cards / "council-park-story.jpg").write_bytes(jpeg)
            (cards / "credits.json").write_text(json.dumps(
                {"council-park-story": "Rochdale Borough Council / Used with permission"}), encoding="utf-8")
            assert not repair.granted_source_upgrade(manual, now, grants, set())

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



def run_gmp_release_match() -> None:
    """7 Nov 2026: crime stories reach the paper through other outlets even when
    GMP issued its own release; the release's photo is usable under the GMP
    permission. Report-only by default."""
    import gmp_release_match as gm
    now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    def story(slug, title, when="2026-10-29T10:00:00Z", **extra):
        return dict({"slug": slug, "title": title, "category": "crime", "first_published_at": when,
                     "image_status": "place-generated-card", "image_url": "assets/img/cards/x-place-generated-card.jpg",
                     "source_url": "https://www.manchestereveningnews.co.uk/news/x"}, **extra)
    wanted = story("kibriya", "Police appeal for help finding Kibriya Ahmed linked to missing children")
    jailed = story("grainger", "Drunk driver Cameron Grainger jailed after Rochdale police pursuit", "2026-11-06T09:00:00Z")
    releases = [
        {"url": "https://www.gmp.police.uk/news/greater-manchester/news/appeals/2026/october/wanted-kibriya-ahmed/",
         "title": "Appeal to find wanted man Kibriya Ahmed in Rochdale", "published": "28 October 2026"},
        {"url": "https://www.gmp.police.uk/news/greater-manchester/news/news/2026/november/grainger-jailed/",
         "title": "Cameron Grainger jailed after pursuit through Rochdale", "published": "5 November 2026"},
        {"url": "https://www.gmp.police.uk/news/greater-manchester/news/news/2026/november/ahmed-bolton/",
         "title": "Appeal after burglary in Bolton: Ahmed", "published": "29 October 2026"},
    ]
    found = {m["slug"]: m["release_url"] for m in gm.best_matches([wanted, jailed], releases, now)}
    assert found == {"kibriya": releases[0]["url"], "grainger": releases[1]["url"]}, found
    # Outside the date window: no match.
    late = dict(jailed, first_published_at="2026-09-01T09:00:00Z")
    assert gm.best_matches([late], releases[1:2], now) == []
    # One shared word, or no shared name: no match.
    assert gm.score(story("s", "Rochdale burglary appeal"), releases[2])[0] == 0
    # Photos never taken from active proceedings, sexual offences, missing
    # people, children or safeguarding releases.
    for unsafe in ("Man charged after assault in Rochdale", "Man on trial over Heywood robbery",
                   "Rochdale man jailed for rape", "Missing woman from Middleton", "Boy, 13, stabbed in Rochdale",
                   "Appeal after child neglect in Heywood", "Inquest opens into Rochdale death"):
        assert not gm.photo_safe(unsafe), unsafe
    for safe in ("Cameron Grainger jailed after pursuit through Rochdale", "Appeal to find wanted man Kibriya Ahmed",
                 "CCTV appeal after Rochdale shop robbery", "Wanted: man missing from bail in Rochdale"):
        assert gm.photo_safe(safe), safe
    # Not a candidate once it has a real photo or a GMP page already.
    assert not gm.candidate_story(dict(wanted, image_status="editorial-photo", image_url="assets/img/cards/a.jpg"), now)
    assert not gm.candidate_story(dict(wanted, source_urls=[releases[0]["url"]]), now)
    # Apply mode attaches the release as a source; report mode changes nothing.
    rows = [dict(wanted)]
    report = gm.run(rows, "report", releases)
    assert report["matches"] and "gmp_release_url" not in rows[0]
    report = gm.run(rows, "apply", releases)
    assert rows[0]["gmp_release_url"] == releases[0]["url"] and releases[0]["url"] in rows[0]["source_urls"]
    # Dates (7 Nov 2026 review): an undated release never matches, and a
    # long month name is read in full.
    undated = dict(releases[1], published="")
    assert gm.score(jailed, undated)[0] == 0
    assert gm._when("29 September 2026") == datetime(2026, 9, 29, tzinfo=timezone.utc)
    assert gm._when("Published 5 November 2026 at 10:31") == datetime(2026, 11, 5, tzinfo=timezone.utc)
    september = dict(releases[1], published="29 September 2026")
    assert gm.score(jailed, september)[0] == 0          # same person, different incident
    assert gm._when("November 2026") is None
    # Ages: adults stay eligible, children never.
    assert gm.photo_safe("Appeal to find wanted man John Smith, 35-year-old, in Rochdale")
    assert gm.photo_safe("Rochdale man, 42, jailed after pursuit")
    for child in ("Appeal for 15-year-old from Heywood", "Rochdale boy, 13, hurt", "Girl aged 9 assaulted",
                  "Teenager sought after Middleton incident"):
        assert not gm.photo_safe(child), child
    print("GMP release matching passed.")


if __name__ == "__main__":
    run()
    run_gmp_release_match()


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
