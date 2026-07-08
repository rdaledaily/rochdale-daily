#!/usr/bin/env python3
"""
Rochdale Daily autonomous news pipeline.

What this replacement fixes:
- Uses the source publication date instead of the scrape time.
- Rejects stale or undated stories.
- Removes Markdown from every public field.
- Requests strict structured JSON from OpenAI.
- Never invents missing dates, quotes, contacts, prices or facts.
- Extracts image candidates from RSS, Open Graph, Twitter cards and JSON-LD.
- Only publishes source images from an explicit allow-list.
- Sends crime, court, death, child-safeguarding and allegation stories to
  review_queue.json instead of automatically publishing them.
- Avoids Facebook-group scraping and search-result scraping.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import time
import urllib.robotparser
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "articles.json"
REVIEW_FILE = ROOT / "review_queue.json"
LOG_FILE = ROOT / "scraper" / "scraper.log"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_NEWS_AGE_HOURS = int(os.getenv("MAX_NEWS_AGE_HOURS", "168"))
RETENTION_DAYS = int(os.getenv("ARTICLE_RETENTION_DAYS", "14"))
MAX_PUBLISHED_ARTICLES = int(os.getenv("MAX_PUBLISHED_ARTICLES", "60"))
MAX_AI_ARTICLES_PER_RUN = int(os.getenv("MAX_AI_ARTICLES_PER_RUN", "20"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
RESPECT_ROBOTS = os.getenv("RESPECT_ROBOTS", "true").lower() not in {"0", "false", "no"}

# Add a domain only after confirming that Rochdale Daily may reuse images from it.
# Commercial publishers such as MEN and BBC are deliberately excluded.
IMAGE_REUSE_SOURCE_DOMAINS = {
    item.strip().lower()
    for item in os.getenv(
        "IMAGE_REUSE_SOURCE_DOMAINS",
        "rochdale.gov.uk,gmp.police.uk,manchesterfire.gov.uk,rochdaleafc.co.uk,tfgm.com",
    ).split(",")
    if item.strip()
}

RSS_SOURCES = [
    {
        "name": "Rochdale Borough Council",
        "url": "https://www.rochdale.gov.uk/news/rss.xml",
        "default_area": "rochdale",
    },
    {
        "name": "Greater Manchester Police",
        "url": "https://www.gmp.police.uk/news/rss.xml",
        "default_area": "rochdale",
    },
    {
        "name": "BBC Manchester",
        "url": "https://feeds.bbci.co.uk/news/england/manchester/rss.xml",
        "default_area": "rochdale",
    },
    {
        "name": "Manchester Fire and Rescue",
        "url": "https://www.manchesterfire.gov.uk/news-events/news/feed/",
        "default_area": "rochdale",
    },
    {
        "name": "Rochdale AFC",
        "url": "https://www.rochdaleafc.co.uk/news/feed",
        "default_area": "rochdale",
    },
]

DISCOVERY_PAGES = [
    {
        "name": "Rochdale Borough Council",
        "url": "https://www.rochdale.gov.uk/news",
        "default_area": "rochdale",
        "link_pattern": r"/news/",
    },
    {
        "name": "Greater Manchester Police",
        "url": "https://www.gmp.police.uk/news/",
        "default_area": "rochdale",
        "link_pattern": r"/news/",
    },
    {
        "name": "Manchester Fire and Rescue",
        "url": "https://www.manchesterfire.gov.uk/news-events/news/",
        "default_area": "rochdale",
        "link_pattern": r"/news",
    },
    {
        "name": "Rochdale AFC",
        "url": "https://www.rochdaleafc.co.uk/news/",
        "default_area": "rochdale",
        "link_pattern": r"/news/",
    },
    {
        "name": "Manchester Evening News",
        "url": "https://www.manchestereveningnews.co.uk/all-about/rochdale",
        "default_area": "rochdale",
        "link_pattern": r"/news/",
    },
    {
        "name": "BBC Manchester",
        "url": "https://www.bbc.co.uk/news/england/manchester",
        "default_area": "rochdale",
        "link_pattern": r"/news/",
    },
]

LOCAL_TERMS = {
    "rochdale", "heywood", "littleborough", "milnrow", "newhey", "norden",
    "bamford", "kirkholt", "shawclough", "healey", "whitworth", "wardle",
    "smithy bridge", "castleton", "spotland", "falinge", "balderstone",
    "dera", "deeplish", "smallbridge", "firgrove", "syke", "cutgate",
}

AREA_KEYWORDS = {
    "heywood": {"heywood", "darnhill"},
    "littleborough": {"littleborough", "smithy bridge"},
    "milnrow": {"milnrow", "newhey"},
    "whitworth": {"whitworth"},
    "norden": {"norden", "bamford", "cutgate", "caldershaw"},
    "kirkholt": {"kirkholt"},
    "shawclough_healey": {"shawclough", "healey"},
    "rochdale": {
        "rochdale", "spotland", "falinge", "castleton", "balderstone",
        "deeplish", "smallbridge", "firgrove", "syke",
    },
}

CATEGORY_KEYWORDS = {
    "crime": {
        "arrest", "police", "charged", "court", "burglary", "robbery",
        "assault", "stabbing", "theft", "fraud", "wanted", "jailed",
    },
    "transport": {
        "bus", "train", "traffic", "road", "closure", "diversion",
        "metrolink", "bee network", "m62", "parking",
    },
    "politics": {
        "council", "councillor", "election", "cabinet", "committee",
        "planning", "mayor", "mp ",
    },
    "education": {
        "school", "college", "university", "ofsted", "teacher", "pupil",
        "student", "education",
    },
    "sport": {
        "football", "rochdale afc", "dale", "match", "fixture", "league",
        "rugby", "cricket", "boxing",
    },
    "events": {
        "festival", "concert", "event", "fair", "market", "open day",
        "exhibition", "gig", "performance", "parade",
    },
    "business": {
        "business", "shop", "restaurant", "pub", "company", "jobs",
        "investment", "opening", "closure",
    },
    "community": {
        "community", "charity", "fundraiser", "volunteer", "library",
        "support group", "appeal",
    },
}

SENSITIVE_PATTERNS = [
    r"\b(alleged|allegedly|accused|charged|arrested|court|trial|jury|inquest|coroner)\b",
    r"\b(murder|manslaughter|rape|sexual|assault|abuse|grooming|stabbing|death|died|killed)\b",
    r"\b(child|children|minor|youth|under[- ]?18|schoolgirl|schoolboy)\b",
    r"\b(suicide|self-harm|domestic abuse|domestic violence)\b",
]

DROP_PATTERNS = [
    r"\b(opinion|comment|column|editorial|analysis)\b",
    r"\bfor sale\b|\bfor rent\b|\broom to let\b|\bjob vacancy\b",
    r"\brecommendations please\b|\bdoes anyone know\b|\bgetting rid of\b",
]

PLACEHOLDER_PATTERNS = [
    r"\[(?:insert|relevant|contact|date|number|details|link)[^\]]*\]",
    r"\babout this article\b.*$",
    r"\brelated topics\b.*$",
    r"#rochdalenews|#greatermanchester",
    r"\bfact-checked local journalism\b",
]

ARTICLE_SCHEMA = {
    "name": "rochdale_daily_article",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "publishable": {"type": "boolean"},
            "title": {"type": "string"},
            "excerpt": {"type": "string"},
            "paragraphs": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 8,
            },
            "category": {
                "type": "string",
                "enum": [
                    "news", "crime", "transport", "politics", "education",
                    "sport", "events", "business", "community",
                ],
            },
            "area": {
                "type": "string",
                "enum": [
                    "rochdale", "heywood", "littleborough", "milnrow",
                    "whitworth", "norden", "kirkholt", "shawclough_healey",
                ],
            },
            "reason": {"type": "string"},
        },
        "required": [
            "publishable", "title", "excerpt", "paragraphs",
            "category", "area", "reason",
        ],
    },
}

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("rochdale_daily")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "RochdaleDaily/2.0 (+https://rochdaledaily.co.uk; "
            "editorial contact: news@rochdaledaily.co.uk)"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
    }
)

ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser] = {}


@dataclass
class Candidate:
    source_name: str
    source_url: str
    source_title: str
    source_summary: str
    source_published_at: str
    area: str
    category: str
    image_candidate_url: str = ""
    source_body_excerpt: str = ""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def canonicalise_url(url: str) -> str:
    parsed = urlparse(url)
    clean_query = "&".join(
        part for part in parsed.query.split("&")
        if part and not part.lower().startswith(
            ("utm_", "at_medium=", "at_campaign=", "fbclid=", "gclid=")
        )
    )
    return urlunparse(
        (parsed.scheme or "https", parsed.netloc.lower(), parsed.path, "", clean_query, "")
    )


def stable_id(url: str) -> str:
    return hashlib.sha256(canonicalise_url(url).encode("utf-8")).hexdigest()[:18]


def normalise_ws(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_markdown(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", text)
    text = re.sub(r"`{1,3}([^`]+)`{1,3}", r"\1", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    for pattern in PLACEHOLDER_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
    return normalise_ws(text).strip("*_#- ")


def make_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", strip_markdown(title).lower()).strip("-")
    return slug[:80] or "local-news-update"


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value).strip()
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                result = parsedate_to_datetime(text)
            except (TypeError, ValueError, OverflowError):
                return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def is_fresh(value: datetime | None) -> bool:
    if value is None:
        return False
    age = utc_now() - value
    return timedelta(minutes=-15) <= age <= timedelta(hours=MAX_NEWS_AGE_HOURS)


def detect_area(text: str, fallback: str = "rochdale") -> str:
    lowered = text.lower()
    for area, terms in AREA_KEYWORDS.items():
        if any(term in lowered for term in terms):
            return area
    return fallback


def categorise(text: str) -> str:
    lowered = text.lower()
    scores = {
        category: sum(1 for keyword in keywords if keyword in lowered)
        for category, keywords in CATEGORY_KEYWORDS.items()
    }
    category, score = max(scores.items(), key=lambda item: item[1])
    return category if score else "news"


def is_local(text: str, source_name: str) -> bool:
    lowered = text.lower()
    if source_name in {"Rochdale Borough Council", "Rochdale AFC"}:
        return True
    return any(term in lowered for term in LOCAL_TERMS)


def should_drop(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in DROP_PATTERNS)


def requires_editorial_review(text: str, category: str) -> tuple[bool, str]:
    matches = [
        pattern for pattern in SENSITIVE_PATTERNS
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    if category == "crime" or matches:
        return True, "Crime, court, death, safeguarding or allegation content requires human review."
    return False, ""


def robots_allows(url: str) -> bool:
    if not RESPECT_ROBOTS:
        return True
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    robot = ROBOTS_CACHE.get(base)
    if robot is None:
        robot = urllib.robotparser.RobotFileParser()
        robot.set_url(urljoin(base, "/robots.txt"))
        try:
            robot.read()
        except Exception:
            # If robots.txt itself cannot be retrieved, make only the ordinary
            # metadata request; never attempt login, paywall or anti-bot bypasses.
            log.warning("Could not read robots.txt for %s; allowing metadata request only.", base)
            return True
        ROBOTS_CACHE[base] = robot
    try:
        return robot.can_fetch(SESSION.headers["User-Agent"], url)
    except Exception:
        return True


def fetch_html(url: str) -> tuple[str, str]:
    if not robots_allows(url):
        raise PermissionError(f"robots.txt does not permit fetching {url}")
    response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "<html" not in response.text[:500].lower():
        raise ValueError(f"Not an HTML page: {content_type}")
    return response.url, response.text


def first_meta(soup: BeautifulSoup, selectors: Iterable[tuple[str, dict[str, str]]]) -> str:
    for tag, attrs in selectors:
        node = soup.find(tag, attrs=attrs)
        if node and node.get("content"):
            return normalise_ws(node.get("content"))
    return ""


def extract_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        queue = payload if isinstance(payload, list) else [payload]
        for item in queue:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                queue.extend(item["@graph"])
            elif isinstance(item, dict):
                objects.append(item)
    return objects


def image_from_jsonld(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return image_from_jsonld(value[0])
    if isinstance(value, dict):
        return str(value.get("url") or value.get("contentUrl") or "")
    return ""


def page_metadata(url: str) -> dict[str, str]:
    final_url, raw_html = fetch_html(url)
    soup = BeautifulSoup(raw_html, "lxml")
    jsonld = extract_jsonld(soup)

    title = first_meta(
        soup,
        [
            ("meta", {"property": "og:title"}),
            ("meta", {"name": "twitter:title"}),
        ],
    )
    if not title:
        h1 = soup.find("h1")
        title = normalise_ws(h1.get_text(" ", strip=True) if h1 else "")
    if not title and soup.title:
        title = normalise_ws(soup.title.get_text(" ", strip=True))

    description = first_meta(
        soup,
        [
            ("meta", {"property": "og:description"}),
            ("meta", {"name": "description"}),
            ("meta", {"name": "twitter:description"}),
        ],
    )

    image_url = first_meta(
        soup,
        [
            ("meta", {"property": "og:image:secure_url"}),
            ("meta", {"property": "og:image"}),
            ("meta", {"name": "twitter:image"}),
        ],
    )

    published = first_meta(
        soup,
        [
            ("meta", {"property": "article:published_time"}),
            ("meta", {"name": "article:published_time"}),
            ("meta", {"name": "date"}),
            ("meta", {"name": "pubdate"}),
        ],
    )

    body_parts: list[str] = []
    for item in jsonld:
        kind = item.get("@type")
        kinds = set(kind if isinstance(kind, list) else [kind])
        if kinds.intersection({"NewsArticle", "Article", "ReportageNewsArticle"}):
            title = title or normalise_ws(item.get("headline"))
            description = description or normalise_ws(item.get("description"))
            published = published or normalise_ws(item.get("datePublished"))
            image_url = image_url or image_from_jsonld(item.get("image"))
            article_body = normalise_ws(item.get("articleBody"))
            if article_body:
                body_parts.append(article_body[:2500])

    if not body_parts:
        paragraphs = [
            normalise_ws(p.get_text(" ", strip=True))
            for p in soup.select("article p, main p")
        ]
        body_parts.extend([p for p in paragraphs if len(p) >= 40][:4])

    return {
        "url": canonicalise_url(final_url),
        "title": strip_markdown(title),
        "description": strip_markdown(description),
        "published": published,
        "image": urljoin(final_url, image_url) if image_url else "",
        "body_excerpt": normalise_ws(" ".join(body_parts))[:3000],
    }


def entry_datetime(entry: Any) -> datetime | None:
    for key in ("published", "updated", "created"):
        value = getattr(entry, key, None)
        parsed = parse_datetime(value)
        if parsed:
            return parsed
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, key, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def rss_image(entry: Any) -> str:
    for attr in ("media_content", "media_thumbnail"):
        values = getattr(entry, attr, None) or []
        for item in values:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    for item in getattr(entry, "enclosures", None) or []:
        if isinstance(item, dict):
            content_type = str(item.get("type") or "")
            if content_type.startswith("image/") and item.get("href"):
                return str(item["href"])
    return ""


def collect_rss_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    for source in RSS_SOURCES:
        log.info("Reading RSS: %s", source["name"])
        feed = feedparser.parse(source["url"])
        if getattr(feed, "bozo", False):
            log.warning("RSS warning for %s: %s", source["name"], getattr(feed, "bozo_exception", "unknown"))
        for entry in list(feed.entries)[:30]:
            source_url = canonicalise_url(str(getattr(entry, "link", "") or ""))
            source_title = strip_markdown(getattr(entry, "title", ""))
            summary_html = str(
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
                or ""
            )
            summary = strip_markdown(BeautifulSoup(summary_html, "lxml").get_text(" ", strip=True))
            published = entry_datetime(entry)
            text = f"{source_title} {summary}"
            if not source_url or not source_title or not is_fresh(published):
                continue
            if should_drop(text) or not is_local(text, source["name"]):
                continue

            image_url = rss_image(entry)
            body_excerpt = summary
            # Metadata fallback provides a real date/image when RSS omits one.
            if not image_url or len(summary) < 80:
                try:
                    meta = page_metadata(source_url)
                    source_title = meta["title"] or source_title
                    summary = meta["description"] or summary
                    image_url = image_url or meta["image"]
                    body_excerpt = meta["body_excerpt"] or body_excerpt
                    page_date = parse_datetime(meta["published"])
                    if page_date:
                        published = page_date
                except Exception as exc:
                    log.debug("Metadata fallback failed for %s: %s", source_url, exc)

            if not is_fresh(published):
                continue
            area = detect_area(text, source["default_area"])
            category = categorise(text)
            candidates.append(
                Candidate(
                    source_name=source["name"],
                    source_url=source_url,
                    source_title=source_title,
                    source_summary=summary,
                    source_published_at=iso_utc(published),
                    area=area,
                    category=category,
                    image_candidate_url=image_url,
                    source_body_excerpt=body_excerpt,
                )
            )
    return candidates


def discovery_links(source: dict[str, str]) -> list[str]:
    try:
        final_url, raw_html = fetch_html(source["url"])
    except Exception as exc:
        log.warning("Discovery page failed for %s: %s", source["name"], exc)
        return []
    soup = BeautifulSoup(raw_html, "lxml")
    pattern = re.compile(source["link_pattern"], re.IGNORECASE)
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = canonicalise_url(urljoin(final_url, anchor["href"]))
        if url in seen or domain_of(url) != domain_of(final_url):
            continue
        if not pattern.search(urlparse(url).path):
            continue
        seen.add(url)
        links.append(url)
        if len(links) >= 20:
            break
    return links


def collect_discovery_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    for source in DISCOVERY_PAGES:
        log.info("Discovering pages: %s", source["name"])
        for url in discovery_links(source):
            try:
                meta = page_metadata(url)
            except PermissionError as exc:
                log.info("%s", exc)
                continue
            except Exception as exc:
                log.debug("Page metadata failed for %s: %s", url, exc)
                continue

            published = parse_datetime(meta["published"])
            text = f"{meta['title']} {meta['description']} {meta['body_excerpt']}"
            if not meta["title"] or not is_fresh(published):
                continue
            if should_drop(text) or not is_local(text, source["name"]):
                continue

            candidates.append(
                Candidate(
                    source_name=source["name"],
                    source_url=meta["url"],
                    source_title=meta["title"],
                    source_summary=meta["description"],
                    source_published_at=iso_utc(published),
                    area=detect_area(text, source["default_area"]),
                    category=categorise(text),
                    image_candidate_url=meta["image"],
                    source_body_excerpt=meta["body_excerpt"],
                )
            )
            time.sleep(0.25)
    return candidates


def deduplicate(candidates: Iterable[Candidate]) -> list[Candidate]:
    by_url: dict[str, Candidate] = {}
    by_title: dict[str, Candidate] = {}
    for candidate in sorted(
        candidates,
        key=lambda item: item.source_published_at,
        reverse=True,
    ):
        url_key = canonicalise_url(candidate.source_url)
        title_key = re.sub(r"[^a-z0-9]+", " ", candidate.source_title.lower()).strip()
        title_key = " ".join(title_key.split()[:12])
        if url_key in by_url or title_key in by_title:
            continue
        by_url[url_key] = candidate
        by_title[title_key] = candidate
    return list(by_url.values())


def load_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def recent_existing_articles() -> list[dict[str, Any]]:
    cutoff = utc_now() - timedelta(days=RETENTION_DAYS)
    kept: list[dict[str, Any]] = []
    for article in load_json_list(OUTPUT_FILE):
        published = parse_datetime(article.get("published_at"))
        if published and published >= cutoff and article.get("status", "published") == "published":
            article["title"] = strip_markdown(article.get("title"))
            article["excerpt"] = strip_markdown(article.get("excerpt"))
            kept.append(article)
    return kept


def source_image(candidate: Candidate, category: str) -> tuple[str, str, bool]:
    fallback = f"assets/img/category_{category}.svg"
    if not candidate.image_candidate_url:
        return fallback, "", False
    source_domain = domain_of(candidate.source_url)
    if source_domain in IMAGE_REUSE_SOURCE_DOMAINS:
        return candidate.image_candidate_url, candidate.source_name, False
    return fallback, "", True


def rewrite_candidate(candidate: Candidate, client: OpenAI | None) -> dict[str, Any]:
    raw_facts = normalise_ws(
        " ".join(
            part for part in [
                candidate.source_title,
                candidate.source_summary,
                candidate.source_body_excerpt,
            ]
            if part
        )
    )[:6000]

    sensitive, review_reason = requires_editorial_review(raw_facts, candidate.category)

    if client is None:
        draft = {
            "publishable": False,
            "title": candidate.source_title,
            "excerpt": candidate.source_summary,
            "paragraphs": [candidate.source_summary or candidate.source_title, "Editorial review required."],
            "category": candidate.category if candidate.category in CATEGORY_KEYWORDS else "news",
            "area": candidate.area,
            "reason": "OPENAI_API_KEY is missing; source retained for review only.",
        }
    else:
        system_message = (
            "You are the sub-editor for Rochdale Daily, an independent UK local-news publication. "
            "Use only facts contained in the supplied source material. Never invent or infer dates, "
            "quotes, prices, addresses, identities, contact details, statistics, organisations or "
            "local impacts. Do not claim that material is fact-checked. Do not output Markdown, "
            "asterisks, headings, hashtags, links or HTML. Write original wording rather than closely "
            "following the source's expressive language. If the source is too thin, stale, promotional, "
            "speculative or not clearly relevant to Rochdale borough, set publishable to false. "
            "Separate allegation from fact. Do not decide that legally sensitive material is safe for "
            "automatic publication."
        )
        user_message = json.dumps(
            {
                "source_name": candidate.source_name,
                "source_url": candidate.source_url,
                "source_published_at": candidate.source_published_at,
                "detected_area": candidate.area,
                "detected_category": candidate.category,
                "source_material": raw_facts,
                "requested_style": (
                    "A concise headline, a 35-60 word standfirst and 3-6 short factual paragraphs "
                    "in neutral UK English. Mention Rochdale only where the source itself establishes "
                    "the connection."
                ),
            },
            ensure_ascii=False,
        )
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ARTICLE_SCHEMA,
            },
            temperature=0.2,
            max_tokens=1000,
        )
        draft = json.loads(response.choices[0].message.content or "{}")

    title = strip_markdown(draft.get("title"))[:160]
    excerpt = strip_markdown(draft.get("excerpt"))[:320]
    paragraphs = [
        strip_markdown(item)
        for item in draft.get("paragraphs", [])
        if strip_markdown(item)
    ][:8]
    category = str(draft.get("category") or candidate.category)
    area = str(draft.get("area") or candidate.area)
    publishable = bool(draft.get("publishable")) and bool(title and excerpt and len(paragraphs) >= 2)

    public_image, image_credit, image_review_required = source_image(candidate, category)
    article = {
        "id": stable_id(candidate.source_url),
        "title": title or candidate.source_title,
        "slug": make_slug(title or candidate.source_title),
        "excerpt": excerpt or strip_markdown(candidate.source_summary)[:320],
        "content_html": "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs),
        "area": area,
        "category": category,
        "types": [category],
        "published_at": candidate.source_published_at,
        "scraped_at": iso_utc(utc_now()),
        "image_url": public_image,
        "image_candidate_url": candidate.image_candidate_url,
        "image_credit": image_credit,
        "image_review_required": image_review_required,
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "status": "review" if sensitive or not publishable else "published",
        "review_reason": review_reason or strip_markdown(draft.get("reason")),
        "byline": "Rochdale Daily Newsdesk",
    }

    if not article["content_html"]:
        article["content_html"] = f"<p>{html.escape(article['excerpt'])}</p>"
    return article


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    log.info("Starting Rochdale Daily pipeline")
    existing = recent_existing_articles()
    existing_by_source = {
        canonicalise_url(str(item.get("source_url") or "")): item
        for item in existing
        if item.get("source_url")
    }

    candidates = deduplicate(
        collect_rss_candidates() + collect_discovery_candidates()
    )
    log.info("Fresh, local candidates: %d", len(candidates))

    api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key) if api_key else None

    published_new: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    ai_count = 0

    for candidate in candidates:
        source_key = canonicalise_url(candidate.source_url)
        if source_key in existing_by_source:
            continue
        if ai_count >= MAX_AI_ARTICLES_PER_RUN:
            break
        try:
            article = rewrite_candidate(candidate, client)
        except Exception as exc:
            log.exception("Rewrite failed for %s: %s", candidate.source_url, exc)
            continue
        ai_count += 1
        if article["status"] == "published":
            published_new.append(article)
        else:
            review_queue.append(article)

    merged: dict[str, dict[str, Any]] = {}
    for article in published_new + existing:
        key = canonicalise_url(str(article.get("source_url") or article.get("id") or ""))
        if key and key not in merged:
            merged[key] = article

    published = sorted(
        merged.values(),
        key=lambda article: parse_datetime(article.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:MAX_PUBLISHED_ARTICLES]

    review_queue.extend(load_json_list(REVIEW_FILE))
    review_by_source: dict[str, dict[str, Any]] = {}
    for article in review_queue:
        key = canonicalise_url(str(article.get("source_url") or article.get("id") or ""))
        if key:
            review_by_source[key] = article
    reviews = sorted(
        review_by_source.values(),
        key=lambda article: parse_datetime(article.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:100]

    write_json_atomic(OUTPUT_FILE, published)
    write_json_atomic(REVIEW_FILE, reviews)
    log.info(
        "Complete: %d live articles, %d review items, %d AI rewrites",
        len(published), len(reviews), ai_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
