#!/usr/bin/env python3
"""
Rochdale Daily - repair stored article bodies carrying stale merge scaffolding.

WHY THIS EXISTS
---------------
merge_group() used to build merged stories by pooling paragraphs from every
source record and slicing them into "Latest update" (paragraphs 0-3) and
"Earlier developments" (paragraphs 4-11). With two sources each covering the
whole story, that printed the story twice under headings implying the two
halves were different developments, and printed the standfirst three times.

That is fixed at the point of merging. It does not fix articles already
merged, because the merged HTML was written into content_html in
articles.json, and generate_pages.py renders that field directly. Once a
story settles into a single record, merge_group returns early without
touching it, so the old structure is frozen into the stored body and no
amount of re-running the pipeline will clear it.

This pass repairs the stored field. It is idempotent: a body with no
scaffolding is left byte-identical, so it can run on every pipeline run and
becomes a no-op once the archive is clean.

WHAT IT KEEPS
-------------
Where the old structure is present, the "Latest update" section is the most
recent source's own account and survives. The "Earlier developments" pile is
the duplication and is dropped. Nothing is rewritten or reworded - this only
removes scaffolding and duplication that the pipeline itself added.

Usage:
    python scraper/repair_merged_bodies.py
    python scraper/repair_merged_bodies.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from frontpage_pipeline import _canonical_body, plain_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FEED_PATHS = [
    REPO_ROOT / "articles.json",
    REPO_ROOT / "articles" / "frontpage.json",
]
FEED_PATHS += sorted((REPO_ROOT / "articles" / "categories").glob("*.json"))
FEED_PATHS += sorted((REPO_ROOT / "articles" / "areas").glob("*.json"))

SCAFFOLD_RE = re.compile(
    r"<h2>\s*(?:Latest update|Earlier developments|Update timeline)\s*</h2>"
    r'|<p class="ongoing-label">',
    re.S,
)

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def needs_repair(record: dict) -> bool:
    return bool(SCAFFOLD_RE.search(str(record.get("content_html") or "")))


def repair(record: dict) -> tuple[bool, str]:
    """Return (changed, note). Never rewords; only removes scaffolding."""
    before = str(record.get("content_html") or "")
    overview = plain_text(record.get("excerpt") or record.get("summary") or "")
    after = _canonical_body(record, overview)

    if not after.strip():
        # Refuse to empty an article. Better a repetitive page than a blank
        # one, and a blank body would be a silent data loss.
        return False, "SKIPPED - repair would empty the body"

    if after == before:
        return False, ""

    record["content_html"] = after
    b = len(SPACE_RE.sub(" ", TAG_RE.sub(" ", before)).split())
    a = len(SPACE_RE.sub(" ", TAG_RE.sub(" ", after)).split())
    return True, f"{b} -> {a} words"


def load(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, data, None
    for key in ("articles", "items"):
        if isinstance(data.get(key), list):
            return data, data[key], key
    return data, [], None


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair stale merged bodies.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    total_seen = total_fixed = total_skipped = 0

    for path in FEED_PATHS:
        if not path.exists():
            continue
        try:
            data, records, _ = load(path)
        except json.JSONDecodeError as exc:
            print(f"{path.name}: unreadable ({exc})", file=sys.stderr)
            continue

        affected = [r for r in records if isinstance(r, dict) and needs_repair(r)]
        if not affected:
            continue

        fixed = 0
        for record in affected:
            total_seen += 1
            changed, note = repair(record)
            slug = record.get("slug") or record.get("id") or "?"
            if changed:
                fixed += 1
                total_fixed += 1
                print(f"  {path.name}: {slug}  {note}")
            elif note:
                total_skipped += 1
                print(f"  {path.name}: {slug}  {note}", file=sys.stderr)

        if fixed and not args.dry_run:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    print(
        f"\nrecords carrying scaffolding: {total_seen} | "
        f"repaired: {total_fixed} | skipped: {total_skipped}"
        + (" | DRY RUN, nothing written" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
