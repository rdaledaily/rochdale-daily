#!/usr/bin/env python3
"""Apply the human-reviewed legacy archive integrity decisions.

This deliberately does NOT accept generic classifier output. The first report-only
scan surfaced ambiguous keyword traps, so every proposed historical category move
was reviewed and is recorded below. Images are then repaired conservatively, and
related-story cards are forced to use the canonical image of the story they link to.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from legacy_archive_integrity import (
    ROOT, PAGES, REPORT, SITE, clean, meta, title_of, category_of, og_image_of,
    image_reason, replace_category, generated_card, replace_primary_image,
    repair_related_images,
)

# Exact archive headlines reviewed after the report-only scan. Values are the
# editorially appropriate section in the site's existing taxonomy. Entries that
# the generic scanner suggested moving but which were already correct are also
# listed, so future reruns cannot regress them through keyword matching.
REVIEWED = {
    "Appeal for Information Following Serious Collision in Heywood": "traffic",
    "Bus driver shot dead outside London pub named by police": "crime",
    "Bus Services Diverted Due to Roadworks on Shawfield Lane": "transport",
    "Business Clinic Drop-In Event Scheduled in Rochdale": "business",
    "Car Crashes into Restaurant in Rochdale, Causing Significant Damage": "traffic",
    "Car crashes into restaurant in Bamford, causing extensive damage": "traffic",
    "College Road to Close for Roadworks from 29 August 2026": "traffic",
    "Community Event Celebrates Remembrance of Allah in Rochdale": "events",
    "Community Fun Day in Heywood Attracts Over 450 Residents": "events",
    "Police Concerned for Missing Woman from Littleborough": "news",
    "Croft Shifa Pharmacy in Rochdale Sold to First-Time Buyer": "business",
    "Death of 80-Year-Old Rochdale Resident Jimmy Cricket Announced": "news",
    "Death of 80-Year-Old Rochdale Resident Jimmy Cricket": "news",
    "Delays on Tram Replacement Bus Services Due to M62 Car Fire": "transport",
    "Education Minister Visits Derby Street Best Start Family Hub in Heywood": "politics",
    "Falinge Park Junior Parkrun Set for Sunday at 9am": "sport",
    "Investigation Launched After Fire at Illegal Waste Site in Rochdale": "environment",
    "Firefighters Tackle Waste Fire in Smallbridge, Rochdale": "environment",
    "Fireground Museum in Rochdale to Host Summer Family Fun Day": "events",
    "Gabrielle to Perform at Rochdale Feel Good Festival": "events",
    "Green Party Candidate Geraldine Coggins Unveils Vision for Greater Manchester Mayoral Election": "politics",
    "Heywood Students Visit First Choice Homes Oldham as Part of Summer School": "education",
    "Hopwood Hall College to Name New Buildings After Former Governors": "education",
    "Investigation into Neglect of Baby Who Nearly Died in Hospital": "news",
    "Live Bus Departure Information Now Available at Rochdale Road / Oldham College Stop": "transport",
    "Live Bus Departures Available at Rochdale Road / Oldham College Stop": "transport",
    "Sian Astley sets out nine-point plan in Greater Manchester mayoral manifesto": "politics",
    "Man in hospital after glassing incident outside Rochdale pub": "crime",
    "Community protest planned in Middleton town centre next month": "news",
    "Missing Cat Gene Last Seen in Falinge Area of Rochdale": "community",
    "Missing Maltese Dog in Trub, Rochdale": "community",
    "NESO issues urgent call for increased power supply amid heatwave": "environment",
    "New Starbucks with Drive-Through Opens Near Rochdale Infirmary": "business",
    "Paul Waugh Calls for Action on Climate Change in Parliament": "politics",
    "Pupils quiz Paul Waugh about Parliament during Littleborough school visit": "education",
    "Phil Eckersley Promises Support for Greater Manchester Boroughs Ahead of Mayoral Election": "politics",
    "Plans Submitted for 350 New Homes in Bamford, Rochdale": "business",
    "Police appeal for footage after woman dies in M62 collision near Rochdale": "traffic",
    "Police Concerned for Missing 75-Year-Old Woman Last Seen Near Milnrow Golf Club": "news",
    "Police Officer Rushed to Hospital After Middleton Crash": "traffic",
    "Premier Kia Renews Support for Rochdale Feel Good Festival": "business",
    "Road Closures Announced for Rochdale Feel Good Festival": "traffic",
    "Roadworks on School Lane in Heywood to Begin on 29 July 2026": "traffic",
    "Rochdale AFC Signs Will Jenkins on Two-Year Deal": "sport",
    "Rochdale Appoints New Chief Executive": "politics",
    "Rochdale Charity Raises Awareness of Honour-Based Abuse at Women’s Event": "community",
    "Rochdale Community Fair Scheduled for Next Month": "events",
    "Rochdale Faces Disorder Charges Following York City Match": "sport",
    "Rochdale Feel Good Festival 2026 Celebrates Community Spirit": "events",
    "Rochdale Feel Good Festival Features Performances from Major Artists": "events",
    "Rochdale Feel Good Festival Returns This Summer": "events",
    "Rochdale AFC Announces New Signings Ahead of Upcoming Season": "sport",
    "Rochdale Local Plan Advances, Aiming for 11,000 New Homes by 2039": "politics",
    "Rochdale Local Plan Moves Forward, Shaping Future Development Until 2039": "politics",
    "Rochdale Mental Health Worker Recognised for Saving Person from Canal": "community",
    "Rochdale MP Paul Waugh Calls for Urgent Climate Action in Parliament": "politics",
    "Rochdale MP Paul Waugh Calls for Urgent Climate Action": "politics",
    "Rochdale Pride Returns with Parade and Stalls This Saturday": "events",
    "Rochdale Local Plan to Approve Thousands of New Homes and Transport Changes": "politics",
    "Rochdale’s Side-by-Side Festival Celebrates Community with Theme ‘It Belongs to You’": "events",
    "Rochdale Team to Host First Charity Game Against Hornets": "sport",
    "Saturday Sessions bring live music to Rochdale town centre": "events",
    "Police Appeal for Information on Missing Man James Last Seen in Rochdale": "news",
    "Search Underway for Missing Dog in Castleton": "community",
    "The weather is due to cool down this Sunday in time for the Falinge Park junior parkrun fun day. Free to all families with children 4 to 14. We": "sport",
    "There was one person of interest living in Lancashire. That is the ex leader of the Rochdale Rape Gang. I know that he is not an illegal immigrant but when": "crime",
    "Thousands Attend Rochdale Feel Good Festival Featuring Gabrielle": "events",
    "Children enjoy Tin Man and the Scarecrow show at Smallbridge Library": "events",
    "Severely Neglected Toddler Rushed to Hospital After Social Services Case Closed": "news",
    "Traffic Updates and Local News from Rochdale": "traffic",
    "Two teenagers die in open water during heatwave": "environment",
    "Two prison officers began secret relationships with two gangster brothers after the drug dealers were moved to a jail in Rochdale. Jai Gascoyne, 25, and El": "crime",
    "Vintage Coffee Pot Available for £3 at RSPCA Shop in Rochdale": "community",
    "Work Begins to Repair Collapsing Culvert in Rochdale Canal": "environment",
    "Young bowlers invited to take part in Syke Bowling Club fun day": "sport",
}


def main() -> int:
    current_slugs: set[str] = set()
    current_path = ROOT / "articles.json"
    if current_path.exists():
        data = json.loads(current_path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("articles", [])
        current_slugs = {clean(a.get("slug")) for a in rows if isinstance(a, dict)}

    records = {}
    sources = {}
    for path in sorted(PAGES.glob("*.html")):
        source = path.read_text(encoding="utf-8", errors="ignore")
        title = title_of(source)
        if not title:
            continue
        slug = path.stem
        records[slug] = {
            "slug": slug,
            "title": title,
            "description": meta(source, "description") or meta(source, "og:description"),
            "category": category_of(source),
            "image": og_image_of(source),
            "current_feed": slug in current_slugs,
        }
        sources[slug] = source

    category_changes = []
    image_changes = []
    changed_pages: set[str] = set()

    # Current feed pages remain owned by story_integrity_audit.py. Legacy pages
    # use only the reviewed decisions above; no generic classifier writes here.
    for slug, record in records.items():
        if record["current_feed"]:
            continue
        source = sources[slug]
        old = record["category"] or "news"
        proposed = REVIEWED.get(record["title"], old)
        if proposed != old:
            category_changes.append({"slug": slug, "title": record["title"], "from": old, "to": proposed})
            source = replace_category(source, old, proposed)
            record["category"] = proposed
            changed_pages.add(slug)

        reason = image_reason(record, proposed)
        if reason:
            new_path = generated_card(record, proposed)
            source = replace_primary_image(source, record["image"], new_path)
            absolute = new_path if re.match(r"https?://", new_path, re.I) else SITE + new_path.lstrip("/")
            image_changes.append({
                "slug": slug, "title": record["title"], "category": proposed,
                "old_image": record["image"], "new_image": absolute, "reason": reason,
            })
            record["image"] = absolute
            changed_pages.add(slug)
        sources[slug] = source

    # Now every related-story card is deterministic: linked headline -> linked
    # story's own canonical image. This fixes the 1,288 mismatches found in the
    # report-only scan without guessing what a thumbnail depicts.
    canonical = {slug: clean(r.get("image")) for slug, r in records.items() if clean(r.get("image"))}
    related_changes = []
    for slug, source in list(sources.items()):
        updated = repair_related_images(source, slug, canonical, related_changes, True)
        if updated != source:
            sources[slug] = updated
            changed_pages.add(slug)

    for slug in changed_pages:
        (PAGES / f"{slug}.html").write_text(sources[slug], encoding="utf-8")

    report = {
        "policy": "human-reviewed historical classifications; conservative canonical-image repair; related cards always use the linked story's own canonical image",
        "mode": "reviewed-apply",
        "total_static_pages": len(records),
        "current_feed_pages": sum(1 for r in records.values() if r["current_feed"]),
        "legacy_pages_audited": sum(1 for r in records.values() if not r["current_feed"]),
        "category_change_count": len(category_changes),
        "image_change_count": len(image_changes),
        "related_image_change_count": len(related_changes),
        "changed_page_count": len(changed_pages),
        "category_changes": category_changes,
        "image_changes": image_changes,
        "related_image_changes": related_changes,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "total_static_pages", "current_feed_pages", "legacy_pages_audited",
        "category_change_count", "image_change_count", "related_image_change_count", "changed_page_count"
    )}, indent=2))
    for item in category_changes:
        print(f"CATEGORY {item['from']} -> {item['to']}: {item['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
