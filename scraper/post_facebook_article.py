#!/usr/bin/env python3
"""Post Rochdale Daily's strongest fresh stories to its Facebook Page.

Rebuilt 28 October 2026 from the reader-behaviour report:

* GA (9-27 Oct): 894 readers came from Facebook and stayed 9 seconds; 890
  never returned. Story views by type: crime and court 11.7 per story,
  council money 9.7, events 6.9, roadworks 5.6, folklore 4.3, Morning
  Briefings 2.6.
* Meta is testing a cap of two link posts a month for unverified Pages; links
  in comments are not capped, and only about 2% of Facebook's most-viewed
  posts carry a link.

So each post is now a PHOTO post (the story's own image: the source
organisation's original where Rochdale Daily holds its permission, cached
under assets/img/cards/ by licensed_source_images.py) carrying the social
headline and the key facts, with the article link placed as the Page's first
comment. Posts go out in four fixed local-time slots, at most five a day, and
the strongest story wins each slot.

It does not automate likes, follows, messages or comments on anyone else's
posts. The only comment it writes is the Page's own link under its own post.

Required environment variables:
  FACEBOOK_PAGE_ACCESS_TOKEN  (Page token with pages_manage_posts and
                               pages_manage_engagement)

Optional:
  FACEBOOK_GRAPH_VERSION (default: v26.0)
  FACEBOOK_STATE_PATH (default: facebook/facebook_posted.json)
  FACEBOOK_RESULT_PATH (default: facebook/facebook_last_result.json)
  FACEBOOK_MAX_ARTICLE_AGE_HOURS (default: 36; 0 disables age filtering)
  FACEBOOK_MIN_POST_INTERVAL_MINUTES (default: 60)
  FACEBOOK_SLOT_HOURS (default: "7,12,17,20", Europe/London)
  FACEBOOK_MAX_POSTS_PER_DAY (default: 5)
  FACEBOOK_DRY_RUN (1/true/yes to avoid the Graph API calls)
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reader_copy import clean_social_headline, split_sentences  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
SITE = "https://rochdaledaily.co.uk"
SITE_BASE = SITE + "/articles/"
LONDON = ZoneInfo("Europe/London")

# Measured mean views per story, 9-27 Oct 2026 (reader-behaviour report),
# scaled to a weight. Briefings, sponsored items and filler features are not
# eligible at all.
CATEGORY_WEIGHT = {
    "crime": 3.0, "court": 3.0, "politics": 2.6, "council": 2.6, "health": 2.2,
    "education": 2.2, "news": 2.0, "community": 2.0, "business": 1.9,
    "sport": 1.9, "environment": 1.8, "housing": 2.2, "events": 1.6,
    "traffic": 1.3, "transport": 1.3, "roadworks": 1.2, "weather": 1.2,
}
REAL_PHOTO_STATUSES = {
    "editorial-photo", "source-photo-cached", "commons-photo-cached",
    "cards-library-photo",
}
NO_COMMENT_INVITE = {"crime", "court"}


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def truthy(name: str) -> bool:
    return env(name).lower() in {"1", "true", "yes", "on"}


def int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(env(name, str(default)) or str(default)))
    except ValueError:
        return default


def slot_hours() -> tuple[int, ...]:
    hours: list[int] = []
    for part in env("FACEBOOK_SLOT_HOURS", "7,12,17,20").split(","):
        try:
            value = int(part.strip())
        except ValueError:
            continue
        if 0 <= value <= 23:
            hours.append(value)
    return tuple(sorted(set(hours))) or (7, 12, 17, 20)


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


MISSING = datetime.max.replace(tzinfo=timezone.utc)


def article_key(article: dict[str, Any]) -> str:
    return str(article.get("id") or article.get("story_key") or article.get("slug") or "").strip()


def canonical_url(article: dict[str, Any]) -> str:
    """The clean address: /articles/x.html answers 308 to /articles/x."""
    slug = str(article.get("slug") or "").strip().strip("/")
    return f"{SITE_BASE}{slug}"


def image_url(article: dict[str, Any]) -> str:
    raw = str(article.get("image_url") or article.get("img") or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    return SITE + "/" + raw.lstrip("/")


def one_line(value: Any) -> str:
    return " ".join(html.unescape(str(value or "")).split())


def is_urgent(article: dict[str, Any]) -> bool:
    title = str(article.get("title") or "").lower()
    return bool(
        article.get("featured") is True
        or article.get("breaking") is True
        or article.get("breaking_news") is True
        or article.get("live") is True
        or article.get("live_story") is True
        or title.startswith("live:")
    )


def eligible(article: Any, max_age_hours: int, now: datetime | None = None) -> bool:
    if not isinstance(article, dict):
        return False
    if str(article.get("status") or "published").lower() != "published":
        return False
    if article.get("requires_approval") is True:
        return False
    if not str(article.get("title") or "").strip() or not str(article.get("slug") or "").strip():
        return False
    if not article_key(article):
        return False
    published = parse_dt(article.get("first_published_at") or article.get("published_at"))
    now = now or datetime.now(timezone.utc)
    # Missing publication timestamps must not cause archive stories to be reposted.
    if published == MISSING or published > now:
        return False
    if max_age_hours > 0 and published < now - timedelta(hours=max_age_hours):
        return False
    return True


def roundup_eligible(article: Any, max_age_hours: int, now: datetime | None = None) -> bool:
    """Name kept for older callers: is this story allowed on Facebook at all?"""
    if not eligible(article, max_age_hours, now):
        return False
    if article.get("sponsored") or article.get("paid_submission"):
        return False
    if article.get("briefing_slot"):
        return False
    route = str(article.get("publication_route") or "").lower()
    if route in {"daily-briefing", "evergreen_fallback"}:
        return False
    if article.get("is_evergreen") or article.get("feature_category"):
        # Quiet-day filler features are never front-page news (24 Oct 2026),
        # and they are not what a Facebook follower comes for either.
        return False
    if str(article.get("source_kind") or "").lower() in {
        "paid_reader_submission", "advertisement", "utility", "weather",
    }:
        return False
    if not image_url(article):
        return False
    return True


def score(article: dict[str, Any], now: datetime) -> float:
    category = str(article.get("category") or "news").lower()
    weight = CATEGORY_WEIGHT.get(category, 1.8)
    if str(article.get("image_status") or "") in REAL_PHOTO_STATUSES:
        weight += 0.6
    if article.get("manual_article"):
        weight += 0.5
    if is_urgent(article):
        weight += 2.0
    published = parse_dt(article.get("first_published_at") or article.get("published_at"))
    age_hours = max(0.0, (now - published).total_seconds() / 3600) if published != MISSING else 48
    # Half the pull every 12 hours: today's story beats yesterday's.
    return weight * (0.5 ** (age_hours / 12))


def compose_caption(article: dict[str, Any]) -> str:
    """Social headline, the key facts, and where the full story is.

    No link in the post body (the link goes in the first comment), no emoji,
    no engagement bait. Crime and court posts carry no comment invitation:
    comments are closed on those stories on the site too."""
    title = one_line(article.get("title"))
    headline = clean_social_headline(article.get("social_headline"), title) or title
    excerpt = one_line(article.get("excerpt") or article.get("summary"))
    facts = " ".join(split_sentences(excerpt)[:2]) if excerpt else ""
    if len(facts) > 420:
        facts = facts[:417].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    parts = [headline]
    if facts and facts.casefold() != headline.casefold():
        parts.append(facts)
    category = str(article.get("category") or "").lower()
    closing = "Full story in the first comment."
    if category not in NO_COMMENT_INVITE and not article.get("police_matter"):
        closing += " Tell us what you think below."
    parts.append(closing)
    return "\n\n".join(parts)


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
    """One timestamp per Facebook post, even when several articles share it."""
    unique: dict[str, datetime] = {}
    for key, value in posted.items():
        if not isinstance(value, dict):
            continue
        parsed = parse_dt(value.get("posted_at"))
        if parsed == MISSING:
            continue
        identifier = str(value.get("facebook_post_id") or key)
        unique[identifier] = parsed
    return list(unique.values())


def posts_today(posted: dict[str, Any], now: datetime) -> int:
    day = now.astimezone(LONDON).date()
    return sum(1 for when in recent_post_times(posted) if when.astimezone(LONDON).date() == day)


def current_slot(now: datetime) -> str:
    """'2026-10-28:12' when the London hour is a posting slot, else ''."""
    local = now.astimezone(LONDON)
    return f"{local.date().isoformat()}:{local.hour:02d}" if local.hour in slot_hours() else ""


def slot_used(state: dict[str, Any], slot: str) -> bool:
    return bool(slot) and slot in (state.get("slots") or {})


def schedule_reason(state: dict[str, Any], posted: dict[str, Any], now: datetime,
                    urgent_waiting: bool) -> str:
    """Why this run must not post, or '' when it may."""
    min_interval = int_env("FACEBOOK_MIN_POST_INTERVAL_MINUTES", 60)
    max_day = int_env("FACEBOOK_MAX_POSTS_PER_DAY", 5)
    times = recent_post_times(posted)
    if min_interval > 0 and times:
        next_allowed = max(times) + timedelta(minutes=min_interval)
        if now < next_allowed:
            remaining = max(1, int((next_allowed - now).total_seconds() // 60) + 1)
            return f"Facebook cooldown active; next post allowed in about {remaining} minutes"
    if max_day and posts_today(posted, now) >= max_day:
        return f"Daily Facebook limit reached ({max_day} posts)"
    local_hour = now.astimezone(LONDON).hour
    slot = current_slot(now)
    if slot and not slot_used(state, slot):
        return ""
    if urgent_waiting and 7 <= local_hour <= 22:
        return ""
    if not slot:
        return "Outside the Facebook posting slots (" + ", ".join(f"{h:02d}:00" for h in slot_hours()) + " UK time)"
    return "This slot has already been used"


def _graph_error(exc: urllib.error.HTTPError, action: str) -> RuntimeError:
    raw = exc.read().decode("utf-8", errors="replace")
    try:
        detail = json.loads(raw).get("error", {})
        message = detail.get("message") or f"HTTP {exc.code}"
        diagnostics = [f"HTTP {exc.code}", f"code={detail.get('code', 'unknown')}"]
        if detail.get("error_subcode") is not None:
            diagnostics.append(f"subcode={detail['error_subcode']}")
        message += " (" + ", ".join(diagnostics) + ")"
    except (json.JSONDecodeError, AttributeError):
        message = f"HTTP {exc.code}"
    return RuntimeError(f"Facebook Graph API rejected {action}: {message}")


def _graph_request(path: str, fields: dict[str, str], token: str, version: str, action: str) -> dict[str, Any]:
    endpoint = f"https://graph.facebook.com/{version}/{path}"
    body = urllib.parse.urlencode({**fields, "access_token": token}).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise _graph_error(exc, action) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Facebook Graph API request failed ({action}): {exc.reason}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Facebook Graph API returned invalid JSON ({action})") from exc
    return payload if isinstance(payload, dict) else {}


def resolve_page_id(token: str, version: str) -> str:
    """Resolve the real Graph API Page ID from the token, not a Facebook URL ID."""
    query = urllib.parse.urlencode({"fields": "id,name", "access_token": token})
    endpoint = f"https://graph.facebook.com/{version}/me?{query}"
    try:
        with urllib.request.urlopen(endpoint, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _graph_error(exc, "the Page token check") from exc
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


def graph_photo_post(page_id: str, token: str, photo_url: str, caption: str, version: str) -> str:
    """A published photo post on the Page. Returns the feed post id."""
    payload = _graph_request(
        f"{urllib.parse.quote(page_id)}/photos",
        {"url": photo_url, "caption": caption, "published": "true"},
        token, version, "the photo post",
    )
    post_id = str(payload.get("post_id") or "").strip()
    if not post_id and payload.get("id"):
        post_id = f"{page_id}_{payload['id']}"
    if not post_id:
        raise RuntimeError("Facebook Graph API returned no post id for the photo post")
    return post_id


def graph_comment(post_id: str, token: str, message: str, version: str) -> str:
    payload = _graph_request(
        f"{urllib.parse.quote(post_id)}/comments", {"message": message},
        token, version, "the link comment",
    )
    comment_id = str(payload.get("id") or "").strip()
    if not comment_id:
        raise RuntimeError("Facebook Graph API returned no comment id")
    return comment_id


def graph_edit_caption(post_id: str, token: str, message: str, version: str) -> None:
    _graph_request(urllib.parse.quote(post_id), {"message": message}, token, version, "the caption edit")


def main() -> int:
    token = env("FACEBOOK_PAGE_ACCESS_TOKEN")
    graph_version = env("FACEBOOK_GRAPH_VERSION", "v26.0")
    state_path = Path(env("FACEBOOK_STATE_PATH", str(ROOT / "facebook/facebook_posted.json")))
    result_path = Path(env("FACEBOOK_RESULT_PATH", str(ROOT / "facebook/facebook_last_result.json")))
    dry_run = truthy("FACEBOOK_DRY_RUN")
    max_age_hours = int_env("FACEBOOK_MAX_ARTICLE_AGE_HOURS", 36)
    now = datetime.now(timezone.utc)

    def report(status: str, reason: str = "", **details: Any) -> int:
        result = {"status": status, "checked_at": now.isoformat().replace("+00:00", "Z"), **details}
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

    state = load_json(state_path, {"posted": {}})
    if not isinstance(state, dict):
        state = {"posted": {}}
    posted = state.setdefault("posted", {})
    if not isinstance(posted, dict):
        posted = state["posted"] = {}
    slots = state.setdefault("slots", {})
    if not isinstance(slots, dict):
        slots = state["slots"] = {}

    posted_urls = {str(v.get("url") or "").replace(".html", "") for v in posted.values() if isinstance(v, dict)}
    candidates = [
        row for row in articles
        if roundup_eligible(row, max_age_hours, now)
        and article_key(row) not in posted
        and canonical_url(row) not in posted_urls
    ]
    if not candidates:
        return report("idle", "No fresh unposted stories", remaining_unposted=0)
    candidates.sort(key=lambda row: (score(row, now), str(row.get("slug") or "")), reverse=True)
    urgent_waiting = any(
        is_urgent(row)
        and parse_dt(row.get("first_published_at") or row.get("published_at")) > now - timedelta(hours=3)
        for row in candidates
    )
    reason = schedule_reason(state, posted, now, urgent_waiting)
    if reason:
        return report("idle", reason, remaining_unposted=len(candidates))

    article = candidates[0]
    if urgent_waiting and not current_slot(now):
        article = next(row for row in candidates if is_urgent(row))
    caption = compose_caption(article)
    photo = image_url(article)
    destination = canonical_url(article)
    link_comment = f"Read the full story: {destination}"
    slot = current_slot(now) or now.astimezone(LONDON).strftime("%Y-%m-%d:%H") + "-urgent"
    link_route = "first-comment"

    try:
        if dry_run:
            post_id, comment_id = "dry-run", "dry-run"
        else:
            page_id = resolve_page_id(token, graph_version)
            post_id = graph_photo_post(page_id, token, photo, caption, graph_version)
            try:
                comment_id = graph_comment(post_id, token, link_comment, graph_version)
            except RuntimeError as comment_error:
                # The post is live without its link. Put the link in the
                # caption so readers can reach the story; the workflow then
                # fails the run so the missing permission is fixed, not lived with.
                graph_edit_caption(post_id, token, caption + "\n\n" + link_comment, graph_version)
                link_route = "caption-after-comment-failed"
                comment_id = ""
                print(f"Link comment failed; link added to the caption instead: {comment_error}", file=sys.stderr)
    except RuntimeError as exc:
        write_json(result_path, {
            "status": "error", "reason": str(exc), "slot": slot,
            "article_keys": [article_key(article)], "title": article.get("title"),
            "checked_at": now.isoformat().replace("+00:00", "Z"),
        })
        print(str(exc), file=sys.stderr)
        return 1

    posted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not dry_run:
        posted[article_key(article)] = {
            "facebook_post_id": post_id,
            "link_comment_id": comment_id,
            "link_route": link_route,
            "posted_at": posted_at,
            "title": str(article.get("title") or ""),
            "social_headline": caption.split("\n\n", 1)[0],
            "slug": str(article.get("slug") or ""),
            "url": destination,
            "image_url": photo,
            "image_status": str(article.get("image_status") or ""),
            "slot": slot,
        }
        slots[slot] = {"facebook_post_id": post_id, "posted_at": posted_at, "article_key": article_key(article)}
        state["updated_at"] = posted_at
        state["schema_version"] = 2
        write_json(state_path, state)

    report(
        "dry-run" if dry_run else "posted",
        slot=slot, facebook_post_id=post_id, link_route=link_route, posted_at=posted_at,
        article_count=1, article_keys=[article_key(article)], titles=[str(article.get("title") or "")],
        url=destination, image_url=photo, image_status=str(article.get("image_status") or ""),
        remaining_unposted=max(0, len(candidates) - 1),
        message_preview=caption if dry_run else "",
    )
    # Exit 0 even when the link had to go in the caption: the post IS live, so
    # the workflow must still save state or the next run would post it again.
    # The workflow's last step fails the run on link_route afterwards.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
