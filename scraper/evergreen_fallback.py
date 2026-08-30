#!/usr/bin/env python3
"""Publish one researched evergreen feature when Rochdale's live-news supply is thin.

The trigger is deliberately mechanical:

* fewer than 6 qualifying new local-news stories in the trailing 12 hours;
* only between 09:00 and 20:00 Europe/London time;
* no evergreen fallback published in the previous 24 hours;
* no more than one article is added by a single invocation.

Events, weather, utility/service pages, previous evergreen features and updates to
older stories do not count towards the six-story threshold.  Generation failure
is non-fatal: a quiet-news feature must never stop the real-news edition from
publishing.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
TOPICS_PATH = Path(__file__).with_name("evergreen_topics.json")
STATUS_PATH = ROOT / "scraper_status.json"

THRESHOLD = int(os.getenv("EVERGREEN_THIN_THRESHOLD", "6"))
LOOKBACK_HOURS = int(os.getenv("EVERGREEN_LOOKBACK_HOURS", "12"))
COOLDOWN_HOURS = int(os.getenv("EVERGREEN_COOLDOWN_HOURS", "24"))
START_HOUR = int(os.getenv("EVERGREEN_START_HOUR", "9"))
END_HOUR = int(os.getenv("EVERGREEN_END_HOUR", "20"))
TIMEZONE_NAME = os.getenv("EVERGREEN_TIMEZONE", "Europe/London")
MODEL = os.getenv("EVERGREEN_MODEL", "gpt-5-mini")
BYLINE = os.getenv("EVERGREEN_BYLINE", "Rochdale Daily")
RIGHT_TO_REPLY_EMAIL = os.getenv("RIGHT_TO_REPLY_EMAIL", "news@rochdaledaily.co.uk")

EXCLUDED_SOURCE_KINDS = {"event", "weather", "utility", "service", "evergreen"}
EXCLUDED_PUBLICATION_ROUTES = {"evergreen_fallback", "weather", "event"}
LOCAL_AREAS = {
    "rochdale", "heywood", "middleton", "milnrow", "newhey", "littleborough",
    "wardle", "smallbridge", "smithy-bridge", "whitworth", "castleton",
    "spotland", "falinge", "deeplish", "balderstone", "firgrove", "kirkholt",
    "norden", "bamford", "shawclough", "healey", "syke", "wardleworth",
    "sudden", "lowerplace", "meanwood", "cutgate", "darnhill", "hopwood",
    "alkrington", "boarshaw",
}
BLOCKED_RESEARCH_HOSTS = {
    "rochdaletimes.co.uk", "rochdaleonline.co.uk", "rochdaleobserver.co.uk",
}


@dataclass(frozen=True)
class TriggerDecision:
    should_publish: bool
    reason: str
    qualifying_count: int
    threshold: int
    lookback_hours: int
    local_time: str
    last_evergreen_at: str | None = None


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def first_published_at(article: dict[str, Any]) -> datetime | None:
    """Use original publication only; a later update does not become a new story."""
    return parse_dt(article.get("first_published_at") or article.get("published_at"))


def is_qualifying_new_local_story(article: Any, now: datetime) -> bool:
    if not isinstance(article, dict):
        return False
    if str(article.get("status") or "published").strip().lower() != "published":
        return False
    if article.get("requires_approval") or article.get("exclude_from_frontpage") is True:
        return False
    if article.get("is_evergreen") is True or article.get("evergreen_id"):
        return False

    category = str(article.get("category") or "").strip().lower()
    source_kind = str(article.get("source_kind") or "").strip().lower()
    route = str(article.get("publication_route") or "").strip().lower()
    if category == "events" or source_kind in EXCLUDED_SOURCE_KINDS or route in EXCLUDED_PUBLICATION_ROUTES:
        return False
    if article.get("weather") is True or article.get("service_page") is True or article.get("is_utility") is True:
        return False

    area = str(article.get("area") or "").strip().lower().replace(" ", "-")
    if area not in LOCAL_AREAS:
        return False

    published = first_published_at(article)
    if published is None:
        return False
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    return cutoff <= published <= now + timedelta(minutes=5)


def qualifying_story_count(articles: list[Any], now: datetime) -> int:
    return sum(1 for article in articles if is_qualifying_new_local_story(article, now))


def evergreen_publication_times(articles: list[Any]) -> list[datetime]:
    result: list[datetime] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        if not (article.get("is_evergreen") is True or str(article.get("publication_route") or "") == "evergreen_fallback"):
            continue
        when = first_published_at(article)
        if when is not None:
            result.append(when)
    return sorted(result)


def latest_evergreen_at(articles: list[Any]) -> datetime | None:
    values = evergreen_publication_times(articles)
    return values[-1] if values else None


def within_publishing_window(now: datetime) -> bool:
    local = now.astimezone(ZoneInfo(TIMEZONE_NAME))
    return START_HOUR <= local.hour < END_HOUR


def evaluate_trigger(articles: list[Any], now: datetime | None = None) -> TriggerDecision:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local = now.astimezone(ZoneInfo(TIMEZONE_NAME))
    count = qualifying_story_count(articles, now)
    last = latest_evergreen_at(articles)
    last_text = last.isoformat().replace("+00:00", "Z") if last else None

    if count >= THRESHOLD:
        return TriggerDecision(False, "normal_supply", count, THRESHOLD, LOOKBACK_HOURS, local.isoformat(), last_text)
    if not within_publishing_window(now):
        return TriggerDecision(False, "outside_publishing_window", count, THRESHOLD, LOOKBACK_HOURS, local.isoformat(), last_text)
    if last is not None and now - last < timedelta(hours=COOLDOWN_HOURS):
        return TriggerDecision(False, "evergreen_cooldown", count, THRESHOLD, LOOKBACK_HOURS, local.isoformat(), last_text)
    return TriggerDecision(True, "thin_news_supply", count, THRESHOLD, LOOKBACK_HOURS, local.isoformat(), last_text)


def used_topic_ids(articles: list[Any]) -> set[str]:
    return {
        str(article.get("evergreen_id")).strip()
        for article in articles
        if isinstance(article, dict) and str(article.get("evergreen_id") or "").strip()
    }


def choose_topic(topics: list[Any], articles: list[Any]) -> dict[str, Any] | None:
    used = used_topic_ids(articles)
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        ident = str(topic.get("id") or "").strip()
        if ident and ident not in used:
            return topic
    return None


def extract_response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return str(text).strip()
    parts: list[str] = []
    for item in getattr(response, "output", None) or []:
        for block in getattr(item, "content", None) or []:
            value = getattr(block, "text", None)
            if value:
                parts.append(str(value))
    return "\n".join(parts).strip()


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    decoder = json.JSONDecoder()
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("model returned no JSON object")
    payload, _end = decoder.raw_decode(cleaned[start:])
    if not isinstance(payload, dict):
        raise ValueError("model JSON is not an object")
    return payload


def build_prompt(topic: dict[str, Any]) -> str:
    return f"""You are writing one researched evergreen feature for Rochdale Daily, a local newspaper serving Rochdale borough, Greater Manchester.

TOPIC: {topic.get('title')}
RESEARCH BRIEF: {topic.get('brief')}
AREA: {topic.get('area')}
CATEGORY: {topic.get('category')}

Research this topic on the live web before writing. Prefer primary and authoritative material: Rochdale Council, UK government, ONS, Ofsted, Historic England, archives, museums, academic/heritage organisations and original records. Use at least two credible source pages. Do not use Rochdale Times, Rochdale Online or Rochdale Observer. For current statistics, planning or inspections, use the newest official data available and state the data period. For folklore, ghosts, fairies, boggarts, tunnels or disputed stories, explicitly distinguish legend/tradition from documented fact. Never invent a quote, witness, date, source, document, inspection result, statistic or planning status. If a claim cannot be verified, say so plainly. For allegations or abuse history, rely on official findings and attribute claims precisely; protect victims and avoid sensationalism.

Write an engaging local-newspaper feature of roughly 500-800 words. No emojis. No clickbait. No model/citation tokens. Do not mention competing local news publishers in the title or body. Do not add a bibliography to the body.

Return ONLY one valid JSON object with exactly these keys:
{{
  "title": "headline",
  "excerpt": "one-sentence standfirst",
  "body": "plain text article with paragraphs separated by two newlines",
  "source_name": "name of strongest primary source",
  "source_url": "https://...",
  "sources": [
    {{"name": "source name", "url": "https://..."}},
    {{"name": "source name", "url": "https://..."}}
  ]
}}
"""


def ask_model(topic: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    client = OpenAI(api_key=key)
    prompt = build_prompt(topic)
    last_error: Exception | None = None
    for tool_type in ("web_search", "web_search_preview"):
        try:
            response = client.responses.create(
                model=MODEL,
                tools=[{"type": tool_type}],
                input=prompt,
            )
            text = extract_response_text(response)
            if not text:
                raise RuntimeError("OpenAI returned an empty response")
            return extract_json_object(text)
        except Exception as exc:  # compatibility retry for old/new Responses web-search names
            last_error = exc
    raise RuntimeError(f"web-researched generation failed: {last_error}")


def normalise_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def acceptable_source_url(url: Any) -> bool:
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = normalise_host(text)
    return not any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_RESEARCH_HOSTS)


def url_appears_to_exist(url: str) -> bool:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "RochdaleDaily/1.0 (+https://rochdaledaily.co.uk/)"},
            timeout=10,
            allow_redirects=True,
            stream=True,
        )
    except requests.RequestException:
        return False
    return response.status_code < 400 or response.status_code in {401, 403, 429}


def clean_sources(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw = payload.get("sources")
    if not isinstance(raw, list):
        raw = []
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if not name or not acceptable_source_url(url) or url in seen:
            continue
        if not url_appears_to_exist(url):
            continue
        seen.add(url)
        candidates.append({"name": name[:160], "url": url})
        if len(candidates) >= 5:
            break
    return candidates


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:90] or "rochdale-feature"


def paragraphs_to_html(body: str) -> str:
    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    return "\n".join(f"<p>{html.escape(part)}</p>" for part in paragraphs)


def validate_generated_payload(payload: dict[str, Any], topic: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    title = re.sub(r"\s+", " ", str(payload.get("title") or "")).strip()
    excerpt = re.sub(r"\s+", " ", str(payload.get("excerpt") or "")).strip()
    body = str(payload.get("body") or "").strip()
    if not 20 <= len(title) <= 130:
        raise ValueError("generated title length is outside 20-130 characters")
    if not 50 <= len(excerpt) <= 260:
        raise ValueError("generated excerpt length is outside 50-260 characters")
    words = word_count(body)
    if words < 350 or words > 1100:
        raise ValueError(f"generated body has {words} words; expected 350-1100")
    if re.search(r"|oai_citation|oaicite|contentReference|utm_source=chatgpt", title + excerpt + body, re.I):
        raise ValueError("generated copy contains model/citation artefacts")
    if re.search(r"Rochdale\s+(?:Times|Online|Observer)", title + " " + body, re.I):
        raise ValueError("generated reader-facing copy names a blocked local publisher")

    sources = clean_sources(payload)
    if len(sources) < 2:
        raise ValueError("fewer than two reachable, permitted research sources were returned")

    primary_url = str(payload.get("source_url") or "").strip()
    primary_name = str(payload.get("source_name") or "").strip()
    if not any(source["url"] == primary_url for source in sources):
        primary_url = sources[0]["url"]
        primary_name = sources[0]["name"]
    if not primary_name:
        primary_name = sources[0]["name"]

    cleaned = {
        "title": title,
        "excerpt": excerpt,
        "body": body,
        "source_name": primary_name[:160],
        "source_url": primary_url,
    }
    return cleaned, sources


def make_article(
    generated: dict[str, Any],
    sources: list[dict[str, str]],
    topic: dict[str, Any],
    decision: TriggerDecision,
    now: datetime,
) -> dict[str, Any]:
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    slug = slugify(generated["title"])
    return {
        "id": f"evergreen-{topic['id']}-{now.strftime('%Y%m%d')}",
        "slug": slug,
        "title": generated["title"],
        "excerpt": generated["excerpt"],
        "summary": generated["excerpt"],
        "body": generated["body"],
        "content_html": paragraphs_to_html(generated["body"]),
        "category": str(topic.get("category") or "community"),
        "area": str(topic.get("area") or "rochdale"),
        "byline": BYLINE,
        "status": "published",
        "requires_approval": False,
        "publication_route": "evergreen_fallback",
        "source_kind": "evergreen",
        "source_name": generated["source_name"],
        "source_url": generated["source_url"],
        "sources": sources,
        "published_at": stamp,
        "first_published_at": stamp,
        "last_updated_at": stamp,
        "scraped_at": stamp,
        "ingested_at": stamp,
        "image_url": "",
        "image_credit": "",
        "image_credit_url": "",
        "is_evergreen": True,
        "evergreen_id": str(topic["id"]),
        "evergreen_trigger": {
            "qualifying_new_local_stories": decision.qualifying_count,
            "threshold": decision.threshold,
            "lookback_hours": decision.lookback_hours,
            "cooldown_hours": COOLDOWN_HOURS,
            "rule": f"publish when count < {decision.threshold}",
        },
        "legal_disclaimer": "This article was compiled from identified public sources and may be updated when further verified information becomes available.",
        "right_to_reply": f"For corrections or a right of reply, email {RIGHT_TO_REPLY_EMAIL}.",
    }


def update_status_on_publish(decision: TriggerDecision, topic: dict[str, Any], article: dict[str, Any]) -> None:
    status = read_json(STATUS_PATH, {})
    if not isinstance(status, dict):
        status = {}
    status["source_led_fallback_enabled"] = True
    status["evergreen_fallback"] = {
        "enabled": True,
        "thin_threshold": THRESHOLD,
        "lookback_hours": LOOKBACK_HOURS,
        "cooldown_hours": COOLDOWN_HOURS,
        "publishing_window": f"{START_HOUR:02d}:00-{END_HOUR:02d}:00 {TIMEZONE_NAME}",
        "last_trigger_reason": decision.reason,
        "qualifying_count": decision.qualifying_count,
        "last_topic_id": topic.get("id"),
        "last_article_slug": article.get("slug"),
        "last_published_at": article.get("published_at"),
    }
    write_json_atomic(STATUS_PATH, status)


def log_result(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main() -> int:
    articles = read_json(ARTICLES_PATH, [])
    topics = read_json(TOPICS_PATH, [])
    if not isinstance(articles, list):
        log_result({"evergreen": "skip", "reason": "articles_json_not_list"})
        return 0
    if not isinstance(topics, list) or not topics:
        log_result({"evergreen": "skip", "reason": "topic_bank_empty"})
        return 0

    now = datetime.now(timezone.utc)
    decision = evaluate_trigger(articles, now)
    if not decision.should_publish:
        log_result({"evergreen": "skip", **decision.__dict__})
        return 0

    topic = choose_topic(topics, articles)
    if topic is None:
        log_result({"evergreen": "skip", "reason": "topic_bank_exhausted", **decision.__dict__})
        return 0

    try:
        raw = ask_model(topic)
        generated, sources = validate_generated_payload(raw, topic)
        article = make_article(generated, sources, topic, decision, now)
    except Exception as exc:
        log_result({
            "evergreen": "generation_failed",
            "reason": decision.reason,
            "topic_id": topic.get("id"),
            "error": str(exc)[:1000],
        })
        return 0

    articles.insert(0, article)
    write_json_atomic(ARTICLES_PATH, articles)
    update_status_on_publish(decision, topic, article)
    log_result({
        "evergreen": "published",
        "reason": decision.reason,
        "qualifying_count": decision.qualifying_count,
        "threshold": decision.threshold,
        "lookback_hours": decision.lookback_hours,
        "topic_id": topic.get("id"),
        "slug": article.get("slug"),
        "source_count": len(sources),
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"evergreen": "fatal_guarded", "error": str(exc)[:1000]}), file=sys.stderr)
        raise SystemExit(0)
