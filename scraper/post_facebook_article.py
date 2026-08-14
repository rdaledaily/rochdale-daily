#!/usr/bin/env python3
"""Post one previously-unposted Rochdale Daily article to a Facebook Page.

Required environment variables:
  FACEBOOK_PAGE_ACCESS_TOKEN
  FACEBOOK_PAGE_ID

Optional:
  FACEBOOK_GRAPH_VERSION (default: v26.0)
  FACEBOOK_STATE_PATH (default: facebook/facebook_posted.json)
  FACEBOOK_RESULT_PATH (default: facebook/facebook_last_result.json)
  FACEBOOK_QUEUE_ORDER (oldest|newest, default: newest)
  FACEBOOK_MAX_ARTICLE_AGE_HOURS (default: 48; 0 disables age filtering)
  FACEBOOK_DRY_RUN (1/true/yes to avoid the Graph API call)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
SITE_BASE = "https://rochdaledaily.co.uk/articles/"


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def truthy(name: str) -> bool:
    return env(name).lower() in {"1", "true", "yes", "on"}


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
    if published != datetime.max.replace(tzinfo=timezone.utc) and published > now:
        return False
    if max_age_hours > 0 and published != datetime.max.replace(tzinfo=timezone.utc):
        if published < now - timedelta(hours=max_age_hours):
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
            message_text = detail.get("error", {}).get("message") or f"HTTP {exc.code}"
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
    page_id = env("FACEBOOK_PAGE_ID")
    graph_version = env("FACEBOOK_GRAPH_VERSION", "v26.0")
    state_path = Path(env("FACEBOOK_STATE_PATH", str(ROOT / "facebook/facebook_posted.json")))
    result_path = Path(env("FACEBOOK_RESULT_PATH", str(ROOT / "facebook/facebook_last_result.json")))
    queue_order = env("FACEBOOK_QUEUE_ORDER", "newest").lower()
    dry_run = truthy("FACEBOOK_DRY_RUN")
    try:
        max_age_hours = max(0, int(env("FACEBOOK_MAX_ARTICLE_AGE_HOURS", "48") or "48"))
    except ValueError:
        max_age_hours = 48

    if not ARTICLES_PATH.exists():
        print("articles.json not found", file=sys.stderr)
        return 2
    if not dry_run and (not token or not page_id):
        print("FACEBOOK_PAGE_ACCESS_TOKEN and FACEBOOK_PAGE_ID are required", file=sys.stderr)
        return 2
    if queue_order not in {"oldest", "newest"}:
        print("FACEBOOK_QUEUE_ORDER must be oldest or newest", file=sys.stderr)
        return 2

    articles = load_json(ARTICLES_PATH, [])
    if not isinstance(articles, list):
        print("articles.json must contain a JSON array", file=sys.stderr)
        return 2

    state = load_json(state_path, {"posted": {}})
    if not isinstance(state, dict):
        state = {"posted": {}}
    posted = state.setdefault("posted", {})
    if not isinstance(posted, dict):
        posted = {}
        state["posted"] = posted

    candidates = [a for a in articles if eligible(a, max_age_hours) and article_key(a) not in posted]
    candidates.sort(
        key=lambda a: (
            1 if is_urgent(a) else 0,
            parse_dt(a.get("first_published_at") or a.get("published_at")),
            str(a.get("slug") or ""),
        ),
        reverse=(queue_order == "newest"),
    )

    if not candidates:
        result = {
            "status": "idle",
            "reason": "No fresh unpublished Facebook queue items remain",
            "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        write_json(result_path, result)
        print("No fresh unposted eligible articles remain.")
        return 0

    article = candidates[0]
    key = article_key(article)
    title = " ".join(str(article.get("title") or "").split())
    excerpt = clean_excerpt(article)
    url = canonical_url(article)
    message = title if not excerpt else f"{title}\n\n{excerpt}"

    try:
        if dry_run:
            post_id = "dry-run"
        else:
            post_id = graph_post(page_id, token, message, url, graph_version)
    except RuntimeError as exc:
        result = {
            "status": "error",
            "reason": str(exc),
            "article_key": key,
            "title": title,
            "url": url,
            "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        write_json(result_path, result)
        print(str(exc), file=sys.stderr)
        return 1

    posted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    posted[key] = {
        "facebook_post_id": post_id,
        "posted_at": posted_at,
        "title": title,
        "slug": str(article.get("slug") or ""),
        "url": url,
    }
    state["updated_at"] = posted_at
    state["page_id"] = page_id
    write_json(state_path, state)

    result = {
        "status": "dry-run" if dry_run else "posted",
        "article_key": key,
        "title": title,
        "url": url,
        "facebook_post_id": post_id,
        "posted_at": posted_at,
        "remaining_unposted": max(0, len(candidates) - 1),
    }
    write_json(result_path, result)
    print(f"Facebook post created for: {title}")
    print(f"Article: {url}")
    print(f"Facebook post id: {post_id}")
    print(f"Remaining queue: {max(0, len(candidates) - 1)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
