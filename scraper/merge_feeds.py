"""Merge two concurrently produced articles.json files without losing stories.

Used by the "Commit updated feed" workflow step when a scheduled run's push
is rejected because origin/main moved while the run was in progress (another
run finished first, an editorial publish landed, or a manual push happened).
articles.json is machine-generated whole-file state, so git's line merge can
never resolve it; this merger resolves it with the pipeline's own
story-identity logic instead.

Guarantees:
  * lossless union: every story present on either side survives;
  * editorially locked records survive whole (title, body and category are
    never overwritten by an automated rewrite of the same story);
  * URL stability: when both sides carry the same story, the slug and id of
    the REMOTE (already-pushed, already-served) record win, so a published
    URL never changes during conflict resolution;
  * output sorted newest-first, matching the pipeline's own ordering.

Usage: python scraper/merge_feeds.py REMOTE_JSON LOCAL_JSON OUTPUT_JSON
       (remote first: the side already on origin/main is authoritative for
        story identity; the local run refreshes content where it is newer.)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from story_identity import dedupe_article_records  # noqa: E402
from story_blocklist import is_blocked_article, load_blocklist  # noqa: E402

# Same persistent event-dates ledger frontpage_pipeline.py maintains (see its
# EVENT_DATES_PATH docstring). This merge path is the OTHER way articles.json
# gets rewritten during a lost git push race, and it never calls
# frontpage_pipeline.py's clean_and_integrate_events — so an event's true
# first-seen date needs the same independent correction applied here too, or
# a race resolved through this path alone could still leave a fresh "now"
# timestamp unchallenged.
EVENT_DATES_PATH = Path(os.getenv("EVENT_DATES_JSON", "event_dates.json"))


def normalise_event_url(value: object) -> str:
    parsed = urlparse(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return parsed._replace(fragment="", query="").geturl().rstrip("/")


def load_event_dates() -> dict[str, str]:
    try:
        payload = json.loads(EVENT_DATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(key): str(value)
        for key, value in (payload.items() if isinstance(payload, dict) else [])
        if key and value
    }


def apply_event_date_ledger(articles: list[dict]) -> list[dict]:
    """Correct any event record's date to the ledger's earliest known value.

    Applied AFTER the story-identity merge, as a final, independent pass:
    whatever the whole-file merge decided, an event whose ticket URL is in
    the ledger can never be shown as newer than its true first-seen date.
    """
    ledger = load_event_dates()
    if not ledger:
        return articles
    for article in articles:
        if str(article.get("source_kind") or "").lower() != "event":
            continue
        key = normalise_event_url(article.get("source_url"))
        ledger_value = ledger.get(key)
        if not ledger_value:
            continue
        try:
            ledger_dt = datetime.fromisoformat(ledger_value.replace("Z", "+00:00"))
        except ValueError:
            continue
        current_dt = parse_iso(article.get("published_at"))
        if ledger_dt < current_dt:
            article["published_at"] = ledger_value
            article["first_published_at"] = ledger_value
    return articles


def parse_iso(value: object) -> datetime:
    """Parse the pipeline's ISO-8601 UTC timestamps; datetime.min on failure."""
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def load_feed(path: str) -> list[dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARNING: could not read {path} ({exc}); treating as empty feed.")
        return []
    if not isinstance(payload, list):
        print(f"WARNING: {path} is not a JSON list; treating as empty feed.")
        return []
    return [item for item in payload if isinstance(item, dict)]


def main(remote_path: str, local_path: str, output_path: str) -> int:
    remote = load_feed(remote_path)
    local = load_feed(local_path)

    # Remote records come first: dedupe_article_records merges left-to-right
    # within each cluster and merge_article_records preserves the LEFT
    # record's slug and id, so the already-published identity always wins.
    merged = dedupe_article_records(remote + local)

    # Editorial takedowns override the lossless union. Without this, a
    # story removed on origin/main was resurrected by any in-flight run
    # whose local feed still contained it — the union guarantee made
    # deletion structurally impossible while runs overlapped.
    blocklist = load_blocklist()
    blocked = [
        article for article in merged if is_blocked_article(article, blocklist)
    ]
    if blocked:
        for article in blocked:
            print(
                f"Takedown enforced during merge: {article.get('slug')} — "
                f"{article.get('title')}"
            )
        merged = [article for article in merged if article not in blocked]
    merged = apply_event_date_ledger(merged)
    merged.sort(
        key=lambda article: parse_iso(article.get("published_at")),
        reverse=True,
    )

    Path(output_path).write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    locked = sum(1 for article in merged if article.get("editorial_lock"))
    print(
        f"Merged feeds: {len(remote)} remote + {len(local)} local -> "
        f"{len(merged)} stories ({locked} editorially locked preserved)."
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
