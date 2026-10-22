#!/usr/bin/env python3
"""Post one fresh Rochdale Daily story to its Facebook Page each hour.

This publisher shares individual fresh articles with at least an hour between posts. It does not automate likes, comments, follows,
messages, audience manipulation, or behaviour intended to mimic a person.

Required environment variables:
  FACEBOOK_PAGE_ACCESS_TOKEN

Optional:
  FACEBOOK_GRAPH_VERSION (default: v26.0)
  FACEBOOK_STATE_PATH (default: facebook/facebook_posted.json)
  FACEBOOK_RESULT_PATH (default: facebook/facebook_last_result.json)
  FACEBOOK_MAX_ARTICLE_AGE_HOURS (default: 48; 0 disables age filtering)
  FACEBOOK_MIN_POST_INTERVAL_MINUTES (default: 60)
  FACEBOOK_MAX_POSTS_24H (default: 0; 0 disables the cap)
  FACEBOOK_MIN_ARTICLES_PER_ROUNDUP (default: 2)
  FACEBOOK_MAX_ARTICLES_PER_ROUNDUP (default: 5)
  FACEBOOK_DRY_RUN (1/true/yes to avoid the Graph API call)
"""
from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
SITE_BASE = "https://rochdaledaily.co.uk/articles/"
HOMEPAGE_URL = "https://rochdaledaily.co.uk/"
LONDON = ZoneInfo("Europe/London")

# Four local-time roundup windows, with several fresh stories in one post.
# An available job can publish once during each window, never overnight.
ROUNDUP_WINDOWS = (
    (8, 12, "morning", "Morning news from Rochdale Daily"),
    (12, 16, "lunchtime", "Lunchtime news from Rochdale Daily"),
    (16, 20, "afternoon", "Afternoon news from Rochdale Daily"),
    (20, 24, "evening", "Evening news from Rochdale Daily"),
)


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def truthy(name: str) -> bool:
    return env(name).lower() in {"1", "true", "yes", "on"}


def int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(env(name, str(default)) or str(default)))
    except ValueError:
        return default


def parse_dt(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.max.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return datetime.max.replace(tzinfo=timezone.utc)


def article_key(article: dict[str, Any]) -> str:
    return str(article.get("id") or article.get("story_key") or article.get("slug") or "").strip()


def canonical_url(article: dict[str, Any]) -> str:
    slug = str(article.get("slug") or "").strip().strip("/")
    return f"{SITE_BASE}{slug}.html"


def clean_excerpt(article: dict[str, Any]) -> str:
    text = str(article.get("excerpt") or article.get("summary") or "").strip()
    text = " ".join(text.split())
    if len(text) > 700:
        text = text[:697].rstrip() + "..."
    return text


def is_urgent(article: dict[str, Any]) -> bool:
    title = str(article.get("title") or "").lower()
    content = " ".join([
        title,
        str(article.get("excerpt") or "").lower(),
        str(article.get("category") or "").lower(),
    ])
    return bool(
        article.get("featured") is True
        or article.get("breaking") is True
        or article.get("live") is True
        or "breaking" in content
        or title.startswith("live:")
        or title.startswith("live ")
    )


def eligible(article: Any, max_age_hours: int) -> bool:
    if not isinstance(article, dict):
        return False
    if str(article.get("status") or "published").lower() != "published":
        return False
    if article.get("requires_approval") is True:
        return False
    if not str(article.get("title") or "").strip():
        return False
    if not str(article.get("slug") or "").strip():
        return False
    if not article_key(article):
        return False
    published = parse_dt(article.get("first_published_at") or article.get("published_at"))
    now = datetime.now(timezone.utc)
    # Missing publication timestamps must not cause archive stories to be reposted.
    if published == datetime.max.replace(tzinfo=timezone.utc):
        return False
    if published > now:
        return False
    if max_age_hours > 0 and published != datetime.max.replace(tzinfo=timezone.utc):
        if published < now - timedelta(hours=max_age_hours):
            return False
    return True


def roundup_slot(now: datetime) -> tuple[str, str] | None:
    """Return the unique local-day slot and a human-readable label."""
    local = now.astimezone(LONDON)
    for start, end, name, caption in ROUNDUP_WINDOWS:
        if start <= local.hour < end:
            return f"{local.date().isoformat()}:{name}", caption
    return None


def roundup_posts_today(posted: dict[str, Any], now: datetime) -> int:
    """Count distinct Facebook posts, not the articles contained in a roundup."""
    local_day = now.astimezone(LONDON).date()
    ids: set[str] = set()
    for key, entry in posted.items():
        if not isinstance(entry, dict):
            continue
        when = parse_dt(entry.get("posted_at"))
        if when == datetime.max.replace(tzinfo=timezone.utc):
            continue
        if when.astimezone(LONDON).date() != local_day:
            continue
        ids.add(str(entry.get("facebook_post_id") or key))
    return len(ids)


def format_roundup(articles: list[dict[str, Any]], caption: str) -> str:
    """One readable Facebook post and one clear route back to the newspaper."""
    lines = [caption, "", "A few stories from across the borough:"]
    for article in articles:
        title = html.unescape(" ".join(str(article.get("title") or "").split()))
        # Keep original headlines in the paper, but avoid dash punctuation here.
        title = title.replace(" — ", ": ").replace(" – ", ": ").replace(" - ", ": ")
        lines.append("")
        lines.append("• " + title)
    lines.extend(["", "Read the full reports at rochdaledaily.co.uk."])
    return "\n".join(lines)


def roundup_eligible(article: Any, max_age_hours: int) -> bool:
    if not eligible(article, max_age_hours):
        return False
    if article.get("sponsored") or article.get("paid_submission"):
        return False
    if article.get("briefing_slot"):
        return False
    if str(article.get("publication_route") or "").lower() == "daily-briefing":
        return False
    if str(article.get("source_kind") or "").lower() in {
        "paid_reader_submission", "advertisement", "utility", "weather",
    }:
        return False
    return True


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def recent_post_times(posted: dict[str, Any]) -> list[datetime]:
    """One timestamp per Facebook post, even when five articles share it."""
    unique: dict[str, datetime] = {}
    for key, value in posted.items():
        if not isinstance(value, dict):
            continue
        parsed = parse_dt(value.get("posted_at"))
        if parsed == datetime.max.replace(tzinfo=timezone.utc):
            continue
        identifier = str(value.get("facebook_post_id") or key)
        unique[identifier] = parsed
    return list(unique.values())


def rate_limit_reason(
    posted: dict[str, Any], min_interval_minutes: int, max_posts_24h: int
) -> str:
    now = datetime.now(timezone.utc)
    times = recent_post_times(posted)
    if min_interval_minutes > 0 and times:
        latest = max(times)
        next_allowed = latest + timedelta(minutes=min_interval_minutes)
        if now < next_allowed:
            remaining = max(1, int((next_allowed - now).total_seconds() // 60) + 1)
            return f"Facebook safety cooldown active; next post allowed in about {remaining} minutes"
    if max_posts_24h > 0:
        cutoff = now - timedelta(hours=24)
        count = sum(1 for t in times if t >= cutoff)
        if count >= max_posts_24h:
            return f"Facebook 24-hour safety cap reached ({count}/{max_posts_24h})"
    return ""


def resolve_page_id(token: str, version: str) -> str:
    """Resolve the real Graph API Page ID from the token, not a Facebook URL ID."""
    query = urllib.parse.urlencode({"fields": "id,name", "access_token": token})
    endpoint = f"https://graph.facebook.com/{version}/me?{query}"
    try:
        with urllib.request.urlopen(endpoint, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, KeyError):
            msg = ""
        raise RuntimeError(f"Cannot verify Facebook Page token: {msg or 'HTTP ' + str(exc.code)}") from exc
    except (urllib.error.URLError, ValueError) as exc:
        raise RuntimeError("Cannot verify Facebook Page identity") from exc
    page_name = str(payload.get("name") or "").strip()
    page_id = str(payload.get("id") or "").strip()
    if page_name.casefold() != "rochdale daily" or not page_id.isdigit():
        raise RuntimeError(
            "Token does not identify the Rochdale Daily Page. In Meta Graph API Explorer "
            "select the Rochdale Daily Page token, not a personal User token."
        )
    return page_id


def graph_post(page_id: str, token: str, message: str, link: str, version: str) -> str:
    endpoint = f"https://graph.facebook.com/{version}/{urllib.parse.quote(page_id)}/feed"
    body = urllib.parse.urlencode({
        "message": message,
        "link": link,
        "access_token": token,
    }).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
            error_detail = detail.get("error", {})
            message_text = error_detail.get("message") or f"HTTP {exc.code}"
            diagnostics = [f"HTTP {exc.code}", f"code={error_detail.get('code', 'unknown')}"]
            if error_detail.get("error_subcode") is not None:
                diagnostics.append(f"subcode={error_detail['error_subcode']}")
            if error_detail.get("type"):
                diagnostics.append(f"type={error_detail['type']}")
            message_text += " (" + ", ".join(diagnostics) + ")"
        except json.JSONDecodeError:
            message_text = f"HTTP {exc.code}"
        raise RuntimeError(f"Facebook Graph API rejected the post: {message_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Facebook Graph API request failed: {exc.reason}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Facebook Graph API returned invalid JSON") from exc
    post_id = str(payload.get("id") or "").strip()
    if not post_id:
        raise RuntimeError("Facebook Graph API returned no post id")
    return post_id


def main() -> int:
    token = env("FACEBOOK_PAGE_ACCESS_TOKEN")
    graph_version = env("FACEBOOK_GRAPH_VERSION", "v26.0")
    state_path = Path(env("FACEBOOK_STATE_PATH", str(ROOT / "facebook/facebook_posted.json")))
    result_path = Path(env("FACEBOOK_RESULT_PATH", str(ROOT / "facebook/facebook_last_result.json")))
    dry_run = truthy("FACEBOOK_DRY_RUN")
    max_age_hours = int_env("FACEBOOK_MAX_ARTICLE_AGE_HOURS", 48)
    min_interval_minutes = int_env("FACEBOOK_MIN_POST_INTERVAL_MINUTES", 60)
    max_posts_24h = int_env("FACEBOOK_MAX_POSTS_24H", 0)
    max_stories = 1
    now = datetime.now(timezone.utc)

    def report(status: str, reason: str = "", **details: Any) -> int:
        result = {
            "status": status,
            "checked_at": now.isoformat().replace("+00:00", "Z"),
            **details,
        }
        if reason:
            result["reason"] = reason
        write_json(result_path, result)
        print(f"Facebook article: {status}" + (f" ({reason})" if reason else ""))
        return 0

    if not ARTICLES_PATH.exists():
        print("articles.json not found", file=sys.stderr)
        return 2
    if not dry_run and not token:
        print("FACEBOOK_PAGE_ACCESS_TOKEN is required", file=sys.stderr)
        return 2

    articles = load_json(ARTICLES_PATH, [])
    if not isinstance(articles, list):
        print("articles.json must contain a JSON array", file=sys.stderr)
        return 2

    state = load_json(state_path, {"posted": {}, "roundups": {}})
    if not isinstance(state, dict):
        state = {"posted": {}, "roundups": {}}
    posted = state.setdefault("posted", {})
    if not isinstance(posted, dict):
        posted = {}
        state["posted"] = posted
    roundups = state.setdefault("roundups", {})
    if not isinstance(roundups, dict):
        roundups = {}
        state["roundups"] = roundups

    # UTC hour keys remain unique across the autumn clock change.
    slot_key = now.strftime("%Y-%m-%dT%H")
    limit_reason = rate_limit_reason(posted, min_interval_minutes, max_posts_24h)
    if limit_reason:
        return report("idle", limit_reason, slot=slot_key)

    candidates = [
        row for row in articles
        if roundup_eligible(row, max_age_hours) and article_key(row) not in posted
    ]
    candidates.sort(
        key=lambda row: (
            1 if is_urgent(row) else 0,
            parse_dt(row.get("first_published_at") or row.get("published_at")),
            str(row.get("slug") or ""),
        ),
        reverse=True,
    )
    # Only one rendition of each story or URL per roundup.
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        url = canonical_url(row)
        if url in seen:
            continue
        seen.add(url)
        selected.append(row)
        if len(selected) == max_stories:
            break

    if not selected:
        return report("idle", "No fresh unposted stories", remaining_unposted=0)

    article = selected[0]
    title = html.unescape(" ".join(str(article.get("title") or "").split()))
    message = "\n\n".join(part for part in [title, clean_excerpt(article)] if part)
    destination = canonical_url(article)
    keys = [article_key(row) for row in selected]
    titles = [str(row.get("title") or "") for row in selected]

    try:
        if dry_run:
            post_id = "dry-run"
        else:
            page_id = resolve_page_id(token, graph_version)
            post_id = graph_post(page_id, token, message, destination, graph_version)
    except RuntimeError as exc:
        result = {
            "status": "error",
            "reason": str(exc),
            "slot": slot_key,
            "article_keys": keys,
            "checked_at": now.isoformat().replace("+00:00", "Z"),
        }
        write_json(result_path, result)
        print(str(exc), file=sys.stderr)
        return 1

    posted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not dry_run:
        for row in selected:
            posted[article_key(row)] = {
                "facebook_post_id": post_id,
                "posted_at": posted_at,
                "title": str(row.get("title") or ""),
                "slug": str(row.get("slug") or ""),
                "url": canonical_url(row),
                "roundup_slot": slot_key,
            }
        roundups[slot_key] = {
            "facebook_post_id": post_id,
            "posted_at": posted_at,
            "article_keys": keys,
        }
        state["updated_at"] = posted_at
        write_json(state_path, state)

    return report(
        "dry-run" if dry_run else "posted",
        slot=slot_key,
        facebook_post_id=post_id,
        posted_at=posted_at,
        article_count=len(selected),
        article_keys=keys,
        titles=titles,
        url=destination,
        remaining_unposted=max(0, len(candidates) - len(selected)),
        message_preview=message if dry_run else "",
    )


if __name__ == "__main__":
    raise SystemExit(main())
