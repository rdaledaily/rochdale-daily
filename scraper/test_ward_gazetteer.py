"""Ward lookup and shared library-photo rule regressions (no network)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ward_gazetteer as wg  # noqa: E402
from editorial_contract import ward_decision  # noqa: E402

FIXTURE = {
    "streets": {
        "Albert Royds Street": ["Healey"],
        "Manchester Road": ["Castleton", "Kingsway", "Central Rochdale"],
        "Church Street": ["Littleborough Lakeside"],
        "Hollin Lane": ["North Middleton"],
        "Will Place": ["Central Rochdale"],
        "Sparth Lane": ["Smallbridge and Firgrove"],
        "Ashfield Road": ["Norden"],
        "Darnhill Road": ["West Heywood"],
    },
    "places": {
        "Belfield": ["Milkstone and Deeplish"],
        "Syke": ["Healey"],
        "Smithy Bridge": ["Littleborough Lakeside"],
        "Slattocks": ["North Middleton", "Hopwood Hall"],
    },
}


def story(title, body="", excerpt=""):
    return {"title": title, "excerpt": excerpt, "content_html": "<p>" + body + "</p>", "area": "rochdale"}


def run_wards(path: Path) -> None:
    wg.GAZETTEER_PATH = path
    wg._load.cache_clear(); wg._street_regex.cache_clear()

    d = ward_decision(story("Dog loose on Albert Royds Street worries parents"))
    assert d["wards"] == ["Healey"] and d["status"] == "gazetteer" and d["scope"] == "ward" and d["township"] == "Rochdale", d

    # A road crossing wards never decides one; the named town gives the township.
    d = ward_decision(story("Lane closure on Manchester Road in Heywood"))
    assert d["wards"] == [] and d["scope"] == "township" and d["township"] == "Heywood", d

    # Surname, not place.
    d = ward_decision(story("Councillor praises volunteers", "Mr Belfield said the event went well."))
    assert d["wards"] == [], d
    d = ward_decision(story("Bins missed for a fortnight in Belfield"))
    assert d["wards"] == ["Milkstone and Deeplish"], d
    d = ward_decision(story("Syke residents object to flats"))
    assert d["wards"] == ["Healey"], d

    # Generic street names need the story to place itself in that township.
    d = ward_decision(story("Shop opens on Church Street"))
    assert d["wards"] == [], d
    d = ward_decision(story("Shop opens on Church Street in Littleborough"))
    assert d["wards"] == ["Littleborough Lakeside"], d

    # A sentence is not an address.
    d = ward_decision(story("Council says it will place new bins in the town centre soon"))
    assert "Central Rochdale" not in d["wards"] or d["status"] == "explicit-ward", d

    # Multi-ward places are ignored.
    d = ward_decision(story("Traffic builds in Slattocks"))
    assert d["wards"] == [], d

    # A list of many sites is borough-wide, not four wards.
    d = ward_decision(story("Hygiene ratings published",
                            "Premises on Albert Royds Street, Hollin Lane, Sparth Lane and Ashfield Road were inspected."))
    assert d["wards"] == [] and d["status"] == "multi-site-borough" and d["scope"] == "borough", d

    # Two sites stay two wards.
    d = ward_decision(story("Resurfacing on Sparth Lane and Darnhill Road"))
    assert d["wards"] == ["Smallbridge and Firgrove", "West Heywood"] and d["township"] == "", d

    # "Rochdale" alone is the borough.
    d = ward_decision(story("Rochdale food bank receives donation"))
    assert d["scope"] == "borough" and d["township"] == "", d

    # Only the story's opening counts, not a later paragraph.
    d = {"title": "Charity appeal launched", "excerpt": "", "area": "rochdale",
         "content_html": "<p>A charity has launched an appeal.</p><p>It runs online.</p><p>Its office is on Albert Royds Street.</p>"}
    assert ward_decision(d)["wards"] == [], ward_decision(d)

    assert wg.place_in_text("Fun day in Smithy Bridge") == "Smithy Bridge"
    assert wg.place_in_text("Heywood market reopens") == "Heywood"
    assert wg.place_in_text("Heywood Road roadworks") == ""


def run_photos(root: Path) -> None:
    from PIL import Image
    import ensure_article_images as E
    import image_hierarchy as H
    cards = root / "assets/img/cards"
    cards.mkdir(parents=True)
    import random
    rnd = random.Random(1)
    for name in ("rochdale_in_bloom.jpg", "rochdale_fans.jpg"):
        img = Image.new("RGB", (400, 300))
        img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(400 * 300)])
        img.save(cards / name, quality=90)
    (cards / "commons_image_candidates.json").write_text("{}")

    bloom = {"slug": "bloom", "title": "Rochdale Crowned Champion at Britain in Bloom Awards 2026",
             "category": "community", "area": "rochdale", "image_url": "assets/img/cards/rochdale_in_bloom.jpg",
             "image_status": "cards-library-photo"}
    assert H.choose_image(bloom, root, allow_network=False) == "internal", bloom
    assert bloom["image_url"].endswith("rochdale_in_bloom.jpg"), bloom

    # A body-only word match is not a relevant photo.
    takeaway = {"slug": "spud", "title": "Spudbros Opens New Location on Manchester Road", "category": "business",
                "area": "rochdale", "content": "Rochdale fans welcomed the opening.", "body": "Rochdale fans welcomed the opening."}
    assert E.choose_library_photo(takeaway, root) is None
    assert H.choose_image(takeaway, root, allow_network=False) == "place-card", takeaway

    # The vision review's rejection still overrides a library match.
    bloom2 = dict(bloom)
    assert H.choose_image(bloom2, root, relevance=False, allow_network=False,
                          rejected=["assets/img/cards/rochdale_in_bloom.jpg"]) == "place-card", bloom2


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ward_gazetteer.json"
        path.write_text(json.dumps(FIXTURE))
        run_wards(path)
    with tempfile.TemporaryDirectory() as tmp:
        run_photos(Path(tmp))
    print("Ward gazetteer and library photo checks passed.")


if __name__ == "__main__":
    main()
