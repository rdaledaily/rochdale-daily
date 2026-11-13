#!/usr/bin/env python3
"""Weekday/date consistency: a core fact the paper must never get wrong.

"Saturday, September 10, 2026" when 10 September 2026 is a Thursday is a
factual error, and one a model makes easily when it fills in a fixture day.
An audit on 12 Nov 2026 found 31 article pages and 6 live stories with a
weekday that no date within a year either side of publication can carry.

weekday_errors() returns each such pair. It ignores corrections blocks and
corrections notes, which quote the old wrong date on purpose.

Used by:
  - editorial_upgrade.quality_issues  -> an integrity issue: the model must
    repair the draft, or the story is not published (no guessing here);
  - check_data_files.py               -> a validator error on manual copy;
  - `python scraper/date_check.py`    -> scans live stories and every page.
"""
from __future__ import annotations

import datetime as dt
import html as _html
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ("January February March April May June July August September "
          "October November December").split()
MONTH_INDEX = {m: i + 1 for i, m in enumerate(MONTHS)}
WEEKDAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()
_M = "|".join(MONTHS)
_W = "|".join(WEEKDAYS)
UK_RE = re.compile(rf"\b({_W}),?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_M})(?:,?\s+(\d{{4}}))?\b")
US_RE = re.compile(rf"\b({_W}),?\s+({_M})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b")
CORRECTIONS_RE = re.compile(r'<section class="article-corrections">.*?</section>', re.S | re.I)
ISSUE_MARKER = "Weekday does not match date"


def plain(value: Any) -> str:
    text = CORRECTIONS_RE.sub(" ", str(value or ""))
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", text)))


def _reference(published: Any) -> dt.date:
    if isinstance(published, dt.datetime):
        return published.date()
    if isinstance(published, dt.date):
        return published
    try:
        return dt.datetime.fromisoformat(str(published).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return dt.datetime.now(dt.timezone.utc).date()


def weekday_errors(text: Any, published: Any = None) -> list[tuple[str, str]]:
    """[(phrase, why)] for every weekday + date that cannot be true.

    With no year in the phrase, any year within one either side of
    publication that makes the pair true is accepted."""
    ref = _reference(published)
    body = plain(text)
    errors: list[tuple[str, str]] = []
    for rx, order in ((UK_RE, "dm"), (US_RE, "md")):
        for m in rx.finditer(body):
            weekday = m.group(1)
            if order == "dm":
                day, month = int(m.group(2)), m.group(3)
            else:
                day, month = int(m.group(3)), m.group(2)
            years = [int(m.group(4))] if m.group(4) else [ref.year - 1, ref.year, ref.year + 1]
            candidates = []
            for year in years:
                try:
                    candidates.append(dt.date(year, MONTH_INDEX[month], day))
                except ValueError:
                    pass
            if not candidates:
                errors.append((m.group(0), "no such date"))
                continue
            if any(WEEKDAYS[c.weekday()] == weekday for c in candidates):
                continue
            nearest = min(candidates, key=lambda c: abs((c - ref).days))
            errors.append((m.group(0), f"{nearest.day} {MONTHS[nearest.month - 1]} {nearest.year} "
                                       f"is a {WEEKDAYS[nearest.weekday()]}"))
    return errors


def record_text(record: dict) -> str:
    return " . ".join(str(record.get(k) or "") for k in
                      ("title", "excerpt", "summary", "content_html", "body", "social_headline"))


def record_errors(record: dict) -> list[tuple[str, str]]:
    published = record.get("first_published_at") or record.get("published_at")
    return weekday_errors(record_text(record), published)


def issue_text(errors: Iterable[tuple[str, str]]) -> str:
    detail = "; ".join(f'"{p}" ({why})' for p, why in errors)
    return (f"{ISSUE_MARKER}: {detail}. Use the date and weekday exactly as the source gives "
            "them, or leave the weekday out. Never infer a weekday.")


def scan(root: Path = ROOT) -> dict[str, list[tuple[str, str]]]:
    found: dict[str, list[tuple[str, str]]] = {}
    try:
        for rec in json.loads((root / "articles.json").read_text(encoding="utf-8")):
            if isinstance(rec, dict):
                errs = record_errors(rec)
                if errs:
                    found["articles.json:" + str(rec.get("slug"))] = errs
    except (OSError, ValueError):
        pass
    for page in sorted((root / "articles").glob("*.html")):
        s = page.read_text(encoding="utf-8", errors="ignore")
        pub = re.search(r'"datePublished":\s*"([^"]+)"', s)
        body = re.search(r'class="article-copy".*?(?=<footer|</body>)', s, re.S)
        if not body:
            continue
        errs = weekday_errors(body.group(0), pub.group(1) if pub else None)
        if errs:
            found["articles/" + page.name] = errs
    return found


def main() -> int:
    found = scan()
    for name, errs in found.items():
        for phrase, why in errs:
            print(f"  {name}: \"{phrase}\" -- {why}")
    print(f"date_check: {len(found)} file(s)/record(s) with a weekday that does not match its date")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
