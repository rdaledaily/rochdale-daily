"""Apply LIVE labels for fresh crime stories and updating incidents.

Editor, 15 Nov 2026: "For incidents that are updating they should use the live
template ... with a red light, and times (5.15pm) in a timeline". So besides
crime, any story carrying a real timeline (two or more live_updates, e.g. the
follow-up desk adding a road reopening to a crash) is LIVE while its newest
update is under six hours old, then "As it happened" (live_format.live_state).
"""
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
FINISHED_RE = re.compile(r"\b(?:sentenced|jailed|convicted|acquitted|no further action|case closed|"
                         r"reopen(?:s|ed)?|re-opened|all clear|found safe|stood down)\b", re.I)


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
        if not isinstance(article, dict):
            continue
        is_crime = str(article.get("category") or "").lower() == "crime"
        if not is_crime and len(article.get("live_updates") or []) < 2:
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
        article["breaking_news"] = live and is_crime
        article["breaking_label"] = "BREAKING NEWS" if live and is_crime else ""
        article["is_ongoing"] = live
        article["ongoing_label"] = "LIVE" if live else ""
        article["content_html"] = live_format.strip_baked_timeline(str(article.get("content_html") or ""))
        changed += 1

    ARTICLES.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"render_live_updates: processed {changed} crime or live incident article(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
