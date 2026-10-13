#!/usr/bin/env python3
"""Generate a compact same-origin JavaScript fallback for My Rochdale.

Why: WAF/bot checks can reject browser fetch() requests for JSON data even
while normal <script> loads work. This snapshot is used ONLY when an ordinary
request fails, and always labelled as a saved copy, not live data.

Runs in the normal Pages deployment after article/ward generation.
Does not include personal postcodes, subscriber data, payment data or KV.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "assets/data/my-rochdale-snapshot.js"

FILES = {
    "archive": ROOT / "archive-index.json",
    "wards": ROOT / "ward_areas.json",
    "weather": ROOT / "weather.json",
    "councillors": ROOT / "council_votes.json",
    "policing": ROOT / "assets/data/gmp-ward-policing-priorities.json",
}

def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Snapshot warning: {path.name} unavailable ({type(exc).__name__})")
        return None

def main() -> None:
    values = {name: load(path) for name, path in FILES.items()}
    records = values.get("archive")
    if not isinstance(records, list):
        raise SystemExit("Cannot build local archive fallback without archive-index.json")
    # Only published public archive records; discard arbitrary extra fields.
    values["archive"] = [
        {k: item.get(k) for k in ("title", "slug", "url", "description", "category", "published_at")
         if item.get(k) is not None}
        for item in records if isinstance(item, dict) and item.get("title") and item.get("url")
    ]
    # No personal postcode or reader data is put in this static snapshot.
    values["generatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    values["snapshotOnly"] = True
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    source = "/* Saved public newsroom data. Never claim current traffic or incident status. */\n"
    source += "window.RD_LOCAL_SNAPSHOT = " + json.dumps(values, ensure_ascii=True, separators=(",", ":"), allow_nan=False).replace("</", "<\\/") + ";\n"
    TARGET.write_text(source, encoding="utf-8")
    print(f"Built {TARGET.relative_to(ROOT)} ({len(source):,} bytes; {len(values['archive'])} articles)")

if __name__ == "__main__":
    main()
