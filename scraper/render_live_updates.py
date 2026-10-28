"""Apply LIVE labels and render timestamped updates for fresh crime stories."""
from __future__ import annotations
from feature_policy import is_reserve_feature, normalise_feature
import live_format

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ARTICLES = Path(__file__).resolve().parents[1] / "articles.json"
UK = ZoneInfo("Europe/London")
TIMELINE_RE = re.compile(r'<section class="live-update-timeline".*?</section>', re.S)
FINISHED_RE = re.compile(r"\b(?:sentenced|jailed|convicted|acquitted|no further action|case closed)\b", re.I)


def parse_time(value):
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def visible_time(value):
    dt = parse_time(value)
    from uk_update_times import label
    return label(value)


def main() -> int:
    if not ARTICLES.exists():
        return 0
    items = json.loads(ARTICLES.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    changed = 0

    for index, article in enumerate(items):
        if isinstance(article, dict) and is_reserve_feature(article):
            items[index] = normalise_feature(article)
            continue
        if not isinstance(article, dict) or str(article.get("category") or "").lower() != "crime":
            continue

        # LIVE means live coverage: at least two real updates, the newest under
        # six hours old (live_format.live_state). Until 28 Oct 2026 every crime
        # story under 72 hours old was badged BREAKING NEWS - LIVE, with its own
        # standfirst seeded as a fake first "update". The page now renders its
        # timeline itself, so nothing is baked into the body here.
        text = " ".join(str(article.get(k) or "") for k in ("title", "excerpt", "summary"))
        state = live_format.live_state(article, now)
        live = bool(state["is_live"] and not FINISHED_RE.search(text))
        article["live_story"] = live
        article["live_label"] = "LIVE" if live else ""
        article["breaking_news"] = live
        article["breaking_label"] = "BREAKING NEWS" if live else ""
        article["is_ongoing"] = live
        article["ongoing_label"] = "LIVE" if live else ""
        article["content_html"] = live_format.strip_baked_timeline(str(article.get("content_html") or ""))
        changed += 1

    ARTICLES.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"render_live_updates: processed {changed} crime article(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
