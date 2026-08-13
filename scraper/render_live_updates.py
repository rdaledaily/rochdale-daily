"""Apply LIVE labels and render timestamped updates for fresh crime stories."""
from __future__ import annotations

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
    return dt.astimezone(UK).strftime("%H:%M, %d %B %Y") if dt else "Update"


def main() -> int:
    if not ARTICLES.exists():
        return 0
    items = json.loads(ARTICLES.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    changed = 0

    for article in items:
        if not isinstance(article, dict) or str(article.get("category") or "").lower() != "crime":
            continue

        latest = parse_time(article.get("last_updated_at") or article.get("published_at"))
        text = " ".join(str(article.get(k) or "") for k in ("title", "excerpt", "summary"))
        live = bool(latest and latest >= now - timedelta(hours=72) and not FINISHED_RE.search(text))
        article["live_story"] = live
        article["live_label"] = "LIVE" if live else ""
        article["breaking_news"] = live
        article["breaking_label"] = "BREAKING NEWS" if live else ""
        article["is_ongoing"] = live
        article["ongoing_label"] = "LIVE" if live else ""

        updates = article.get("live_updates") if isinstance(article.get("live_updates"), list) else []
        if live and not updates:
            seed = re.sub(r"<[^>]+>", " ", str(article.get("excerpt") or article.get("summary") or article.get("title") or ""))
            seed = re.sub(r"\s+", " ", seed).strip()
            if seed:
                updates = [{"timestamp": str(article.get("last_updated_at") or article.get("published_at") or ""), "text": seed}]
                article["live_updates"] = updates
                article["update_count"] = 1

        body = TIMELINE_RE.sub("", str(article.get("content_html") or "")).strip()
        if live and len(updates) >= 1:
            rows = []
            for row in updates[:30]:
                if not isinstance(row, dict) or not row.get("text"):
                    continue
                rows.append(
                    '<div class="live-update">'
                    f'<h3>{html.escape(visible_time(row.get("timestamp")))}</h3>'
                    f'<p>{html.escape(str(row.get("text")))}</p>'
                    '</div>'
                )
            timeline = '<section class="live-update-timeline"><h2>BREAKING NEWS — LIVE</h2><p><strong>Live updates, newest first.</strong></p>' + "".join(rows) + '</section>'
            article["content_html"] = timeline + body
        else:
            article["content_html"] = body
        changed += 1

    ARTICLES.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"render_live_updates: processed {changed} crime article(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
