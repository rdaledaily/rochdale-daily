#!/usr/bin/env python3
"""SEO quality gate for the canonical Rochdale Daily article feed."""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTICLES = ROOT / "articles.json"
DENIED = {"rochdaletimes.co.uk", "rochdaleonline.co.uk", "pressreader.com", "rochdaleobserver.co.uk"}
DENIED_NAMES = {"rochdale times", "rochdale online", "rochdale observer", "pressreader"}

def words(html: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", re.sub(r"<[^>]+>", " ", html or "")))

def denied(source: str, url: str) -> bool:
    name = str(source or "").lower()
    domain = re.sub(r"^www\.", "", (re.findall(r"://([^/]+)", str(url or "")) or [""])[0]).lower()
    return domain in DENIED or any(x in name for x in DENIED_NAMES)

def main() -> int:
    rows = json.loads(ARTICLES.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("articles.json must be a list")
    errors, warnings, seen = [], [], set()
    for a in rows:
        if not isinstance(a, dict) or str(a.get("status") or "published").lower() != "published":
            continue
        slug = str(a.get("slug") or "").strip()
        if not slug:
            errors.append("published article missing slug"); continue
        if slug in seen: errors.append(f"duplicate slug: {slug}")
        seen.add(slug)
        for field in ("title", "excerpt", "byline", "category", "area"):
            if not str(a.get(field) or "").strip():
                errors.append(f"{slug}: missing {field}")
        if denied(a.get("source_name"), a.get("source_url")):
            warnings.append(f"{slug}: denied/third-party source is excluded from generated live pages")
        title, excerpt = str(a.get("title") or ""), str(a.get("excerpt") or a.get("summary") or "")
        if len(title) > 90: warnings.append(f"{slug}: title is {len(title)} characters")
        if len(excerpt) > 170: warnings.append(f"{slug}: excerpt is {len(excerpt)} characters")
        w = words(str(a.get("content_html") or ""))
        if w < 120 and str(a.get("source_kind") or "").lower() not in {"event", "listing"}:
            warnings.append(f"{slug}: only {w} words of body copy")
        if not str(a.get("image_url") or a.get("img") or "").strip():
            warnings.append(f"{slug}: no canonical image URL yet")
    print(f"SEO feed audit: {len(rows)} records checked; {len(errors)} error(s); {len(warnings)} warning(s).")
    for item in errors: print("ERROR:", item)
    for item in warnings[:80]: print("WARN:", item)
    if len(warnings) > 80: print(f"WARN: ... {len(warnings)-80} more warning(s)")
    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
