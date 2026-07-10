"""One-off repair for contaminated event records in articles.json.

The union-find duplicate merge (fixed in frontpage_pipeline the same day)
fused several distinct What's Occurrin' ticket events into a single record
carrying multiple event URLs and a borrowed slug. Ticket events are
re-collected in full from the box-office feed on every scheduled run, so
the safe repair is to drop any event record that carries more than one
source URL and let the next run re-create each event cleanly under its own
canonical URL, slug and id. Event records mislabelled with a non-event
category are corrected in place.

Run from the repository root:  python scraper/repair_event_records.py
Preview only:                  python scraper/repair_event_records.py --dry-run
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ARTICLES = Path(__file__).resolve().parents[1] / "articles.json"


def is_event_record(article: dict) -> bool:
    return (
        str(article.get("source_kind") or "") == "event"
        or str(article.get("category") or "") == "events"
    )


def main(dry_run: bool = False) -> int:
    feed = json.loads(ARTICLES.read_text(encoding="utf-8"))
    kept: list[dict] = []
    dropped = 0
    recategorised = 0
    for article in feed:
        if is_event_record(article):
            urls = [u for u in article.get("source_urls") or [] if u]
            if len(urls) > 1:
                print(
                    f"drop contaminated event ({len(urls)} URLs fused): "
                    f"{article.get('slug')} — {str(article.get('title'))[:60]}"
                )
                dropped += 1
                continue
            if str(article.get("category")) != "events":
                print(
                    f"recategorise {article.get('category')!r} -> 'events': "
                    f"{article.get('slug')}"
                )
                article["category"] = "events"
                article["types"] = ["events"]
                recategorised += 1
        kept.append(article)

    if not dry_run and (dropped or recategorised):
        ARTICLES.write_text(
            json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    mode = "DRY RUN — nothing written" if dry_run else "written"
    print(
        f"{dropped} contaminated event record(s) dropped, {recategorised} "
        f"recategorised; {len(kept)} records remain ({mode}). Dropped events "
        f"are re-collected from the ticket feed on the next scheduled run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(dry_run="--dry-run" in sys.argv[1:]))
