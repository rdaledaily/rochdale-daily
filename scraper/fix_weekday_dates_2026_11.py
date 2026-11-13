#!/usr/bin/env python3
"""One-off correction (13 Nov 2026): weekday/date pairs that cannot both be true.

Found by scraper/date_check.py (now a publishing gate). Each correction below
records the evidence used. Where the true date is established, it is
corrected; where it is not, the unverifiable part is removed rather than
guessed. Every corrected page and record gets a dated correction note
(corrections block on the page, corrections[] on the record), as the
editorial standards require for material changes.

Idempotent: a replacement whose old text is absent is skipped.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TODAY = "2026-11-13"

# slug -> (replacements [(old, new)], correction note)
FIXES: dict[str, tuple[list[tuple[str, str]], str]] = {
    "rochdale-afc-to-host-york-city-in-league-two-clash-this-saturday": (
        [("this Saturday, 12 November", "this Saturday, 14 November"),
         ("Saturday, 12 November", "Saturday 14 November")],
        "The match date was given as Saturday 12 November. The match is on Saturday 14 November."),
    # The 13 Nov Morning Briefing quoted the York City story before it was corrected.
    "morning-briefing-13-november-2026": (
        [("this Saturday, 12 November", "this Saturday, 14 November"),
         ("Saturday, 12 November", "Saturday 14 November")],
        "The York City match was dated Saturday 12 November. The match is on Saturday 14 November."),
    "union-street-roadworks-in-rochdale-to-begin-on-17-november-2026": (
        [("Tuesday, 17 November 2027", "Tuesday 17 November 2026")],
        "The start date was misprinted as 2027. The works start on Tuesday 17 November 2026."),
    "roadworks-planned-for-toad-lane-and-surrounding-streets-on-6-november-2026": (
        [("on Sunday, 6 November 2026", "on 6 November 2026")],
        "An incorrect weekday was given for 6 November 2026 and has been removed."),
    "roadworks-scheduled-on-toad-lane-and-surrounding-streets-in-rochdale-on-6-novemb": (
        [("on Sunday, 6 November 2026", "on 6 November 2026")],
        "An incorrect weekday was given for 6 November 2026 and has been removed."),
    # Club page: "FA Youth Cup at COA next Thursday", published Thu 22 Oct.
    "rochdale-afc-to-host-fa-youth-cup-match-at-crown-oil-arena": (
        [("Thursday, October 27", "Thursday 29 October")],
        "The match date was given as Thursday 27 October. The match was on Thursday 29 October."),
    # Source (Rochdale Times, 12 Oct) says only "this weekend".
    "rochdale-pioneers-museum-to-host-archive-sessions-on-local-folklore": (
        [("Scheduled for Saturday 15 October,", "Scheduled for the weekend of 17 October,")],
        "The sessions were wrongly dated Saturday 15 October. The source says they were held that weekend (17 October)."),
    # Report published Monday 5 Oct of the previous Saturday's match.
    "anselmians-rugby-club-secures-40-24-victory-against-rochdale": (
        [("on Saturday, October 5", "on Saturday 3 October")],
        "The match date was given as Saturday 5 October. It was played on Saturday 3 October."),
    # Pages whose body is a York City preview: date unverified -> removed.
    "al-rayyan-to-face-rochdale-in-upcoming-match": (
        [(" on Saturday, July 15, 2026", "")],
        "An unverified match date (Saturday 15 July, which is not a Saturday) has been removed."),
    "boreham-wood-to-play-rochdale-in-upcoming-match": (
        [(" on Saturday, July 15, 2026", "")],
        "An unverified match date (Saturday 15 July, which is not a Saturday) has been removed."),
    "york-city-to-face-rochdale-in-upcoming-match": (
        [(" on Saturday, July 15, 2026", "")],
        "An unverified match date (Saturday 15 July, which is not a Saturday) has been removed."),
    # Walsall 0-0 at the Bescot: Saturday 12 Sep (report published Sun 13 Sep morning).
    "rochdale-afc-manager-discusses-player-returns-and-new-signing-flint": (
        [("on Saturday, September 16, 2026", "on Saturday 12 September 2026")],
        "The Walsall match was dated Saturday 16 September. It was played on Saturday 12 September."),
    "walsall-and-rochdale-play-out-goalless-draw-in-league-two": (
        [("on Saturday, September 13, 2026", "on Saturday 12 September 2026")],
        "The match was dated Saturday 13 September. It was played on Saturday 12 September."),
    # Accrington at home: Saturday 24 October.
    "rochdale-afc-prepares-for-home-match-against-accrington-stanley": (
        [("on Saturday, October 28, 2026", "on Saturday 24 October 2026")],
        "The match was dated Saturday 28 October. It was on Saturday 24 October."),
    # Liverpool U21, EFL Trophy: Tuesday 22 September.
    "rochdale-afc-releases-efl-trophy-matchday-programme-preview": (
        [("on Tuesday, September 21, 2026", "on Tuesday 22 September 2026")],
        "The match was dated Tuesday 21 September. It was on Tuesday 22 September."),
    "rochdale-to-face-liverpool-u21-in-efl-trophy-match": (
        [("on Tuesday, September 21, 2026", "on Tuesday 22 September 2026")],
        "The match was dated Tuesday 21 September. It was on Tuesday 22 September."),
    "rochdale-afc-to-host-liverpool-under-21s-match": (
        [("on Tuesday, September 21, 2026", "on Tuesday 22 September 2026")],
        "The match was dated Tuesday 21 September. It was on Tuesday 22 September."),
    # Crawley at home: Saturday 22 August (previews published Fri 21 Aug).
    "rochdale-afc-to-host-crawley-town-in-league-two-match": (
        [("on Saturday, August 21, 2026", "on Saturday 22 August 2026")],
        "The match was dated Saturday 21 August. It was on Saturday 22 August."),
    "rochdale-afc-to-host-crawley-town-in-key-league-match": (
        [("for Saturday, August 21, 2026", "for Saturday 22 August 2026")],
        "The match was dated Saturday 21 August. It was on Saturday 22 August."),
    "zac-kennard-kettle-to-referee-rochdale-s-match-against-crawley-town": (
        [("for Saturday, August 26, 2026", "for Saturday 22 August 2026")],
        "The match was dated Saturday 26 August. It was on Saturday 22 August."),
    # Gillingham at home: Saturday 5 September.
    "rochdale-afc-publishes-matchday-guide-for-saturday-s-fixture": (
        [("on Saturday, September 3, 2026", "on Saturday 5 September 2026")],
        "The fixture was dated Saturday 3 September. It was on Saturday 5 September."),
    "rochdale-afc-to-host-gillingham-on-september-10-2026": (
        [("on Saturday, September 10, 2026", "on Saturday 5 September 2026")],
        "The match was dated Saturday 10 September. It was on Saturday 5 September."),
    # A Certain Ratio: the Friday 7 August warm-up show.
    "a-certain-ratio-to-perform-at-rochdale-town-hall-square-this-weekend": (
        [("on Saturday, August 7, 2026", "on Friday 7 August 2026")],
        "The concert was dated Saturday 7 August. It was on Friday 7 August."),
    # Date of the meeting not confirmed by the sources: removed.
    "pakistan-refuses-to-take-back-rochdale-grooming-gang-leader-shabir-ahmed": (
        [(" on Thursday, August 28, 2026", "")],
        "An incorrect date for the meeting with UK officials has been removed."),
    "rochdale-afc-women-secure-1-0-victory-over-accrington-stanley-in-fa-cup": (
        [("on Sunday, 31 August 2026", "on Sunday 30 August 2026")],
        "The match was dated Sunday 31 August. It was on Sunday 30 August."),
    "rochdale-afc-women-to-play-at-crown-oil-arena-on-sunday": (
        [("this Sunday, August 21, 2026", "this Sunday, 23 August 2026")],
        "The match was dated Sunday 21 August. It was on Sunday 23 August."),
    # Oldham 2-0 at home: Saturday 19 September.
    "rochdale-afc-secures-2-0-victory-against-oldham-athletic": (
        [("on Saturday, 20 September 2026", "on Saturday 19 September 2026")],
        "The match was dated Saturday 20 September. It was on Saturday 19 September."),
    "rochdale-afc-secures-2-0-victory-against-oldham-athletic-in-league-two": (
        [("on Saturday, 20 September 2026", "on Saturday 19 September 2026")],
        "The match was dated Saturday 20 September. It was on Saturday 19 September."),
    # Grimsby at home: Tuesday 20 October, 2-2 (club highlights "Dale 2-2 Grimsby Town").
    "rochdale-afc-to-host-grimsby-town-on-21-october-2026": (
        [("in a goalless draw on Saturday, 20 October", "in a 2-2 draw on Tuesday 20 October")],
        "The match was described as a goalless draw on Saturday 20 October. It was a 2-2 draw on Tuesday 20 October."),
    # Shrewsbury at home: Tuesday 1 September, Crown Oil Arena.
    "rochdale-to-host-shrewsbury-town-match-on-tuesday-night": (
        [("on Saturday, September 3, 2026, at the New Meadow stadium in Shrewsbury",
          "on Tuesday 1 September 2026 at the Crown Oil Arena")],
        "The match was dated Saturday 3 September at New Meadow. It was at the Crown Oil Arena on Tuesday 1 September."),
    "rochdale-to-host-shrewsbury-town-in-league-two-match-on-september-2": (
        [("on Saturday, September 2, 2026", "on Tuesday 1 September 2026")],
        "The match was dated Saturday 2 September. It was on Tuesday 1 September."),
}

TEXT_FIELDS = ("title", "excerpt", "summary", "content_html", "body", "social_headline", "seo_title")


def correction_html(note: str) -> str:
    return (f'<p><strong>This article was amended on 13 November 2026.</strong> {note}</p>')


def fix_page(path: Path, reps, note) -> bool:
    if not path.exists():
        return False
    s = path.read_text(encoding="utf-8")
    new = s
    for old, rep in reps:
        new = new.replace(old, rep)
    if new == s:
        return False
    block = correction_html(note)
    if '<section class="article-corrections">' in new:
        new = new.replace('<h3>Corrections and clarifications</h3>',
                          '<h3>Corrections and clarifications</h3>' + block, 1)
    else:
        section = ('<section class="article-corrections"><h3>Corrections and clarifications</h3>' + block +
                   '<p class="corrections-footnote">All significant corrections are recorded in our '
                   '<a href="/corrections-log.html">public corrections log</a>. Spotted an error? See '
                   '<a href="/corrections-and-complaints.html">how to request a correction</a>.</p></section>')
        for anchor in ('<section class="comments', '<section class="read-next', '<section class="editorial-legal-note">'):
            if anchor in new:
                new = new.replace(anchor, section + anchor, 1)
                break
    path.write_text(new, encoding="utf-8")
    return True


def fix_record(rec: dict, reps, note) -> bool:
    changed = False
    for field in TEXT_FIELDS:
        val = rec.get(field)
        if isinstance(val, str):
            new = val
            for old, rep in reps:
                new = new.replace(old, rep)
            if new != val:
                rec[field] = new
                changed = True
    if changed:
        corr = rec.setdefault("corrections", [])
        if not any(c.get("note") == note for c in corr if isinstance(c, dict)):
            corr.append({"date": TODAY, "note": note})
        rec["last_updated_at"] = max(str(rec.get("last_updated_at") or ""), TODAY + "T07:45:00Z")
    return changed


def fix_json(path: Path) -> int:
    if not path.exists():
        return 0
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    n = 0

    def walk(node):
        nonlocal n
        if isinstance(node, dict):
            slug = node.get("slug")
            if slug in FIXES and isinstance(node.get("title"), str):
                if fix_record(node, *FIXES[slug]):
                    n += 1
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(data)
    if n:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""),
                        encoding="utf-8")
    return n


def main() -> int:
    pages = sum(fix_page(ROOT / "articles" / f"{slug}.html", *spec) for slug, spec in FIXES.items())
    records = 0
    for path in [ROOT / "articles.json", ROOT / "manual_articles.json",
                 *sorted((ROOT / "manual_articles.d").rglob("*.json")),
                 *sorted((ROOT / "articles").rglob("*.json"))]:
        records += fix_json(path)
    print(f"weekday/date corrections: {pages} page(s), {records} record(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
