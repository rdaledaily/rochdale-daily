#!/usr/bin/env python3
"""Backfill story-related Wikimedia Commons images with strict relevance checks.

This is deliberately conservative: a Commons image is only accepted when its
file title/description metadata matches both the story's subject and, for local
stories, its place/entity context. If no suitably related reusable image is
found, the existing image pipeline is left to use a curated local image or a
fallback card instead of attaching an unrelated photograph.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "RochdaleDailyRelatedCommons/1.0 (news@rochdaledaily.co.uk)"
MIN_BYTES = 7000
MIN_WIDTH = 700
MIN_HEIGHT = 400

LOCAL_PLACES = {
    "rochdale", "heywood", "middleton", "littleborough", "milnrow", "newhey",
    "castleton", "norden", "bamford", "falinge", "spotland", "smallbridge",
    "whitworth", "wardle", "smithy bridge", "shawclough", "healey", "kingsway",
    "greater manchester", "manchester", "manchester victoria",
}

STOP = {
    "about", "after", "again", "against", "amid", "among", "and", "are", "as",
    "at", "before", "between", "but", "by", "for", "from", "has", "have", "in",
    "into", "is", "it", "its", "new", "no", "of", "on", "over", "says", "the",
    "this", "to", "under", "with", "will", "week", "today", "latest", "more",
    "could", "should", "would", "than", "their", "they", "them", "there",
}

# Words which describe the visible subject we actually want in a photograph.
TOPIC_GROUPS = {
    "transport": {
        "train", "trains", "rail", "railway", "station", "tram", "metrolink",
        "bus", "buses", "road", "traffic", "motorway", "junction", "bridge",
    },
    "traffic": {"road", "traffic", "motorway", "junction", "street", "bridge", "vehicle"},
    "crime": {"police", "station", "court", "courthouse", "crime", "officer", "officers"},
    "politics": {"council", "councillor", "town", "hall", "parliament", "election", "mayor"},
    "business": {"shop", "shops", "store", "market", "business", "factory", "office", "restaurant"},
    "education": {"school", "college", "university", "academy", "education"},
    "health": {"hospital", "clinic", "health", "ambulance", "medical"},
    "sport": {"stadium", "football", "club", "sport", "ground", "match"},
    "environment": {"park", "river", "reservoir", "nature", "environment", "moor", "canal"},
    "events": {"festival", "event", "fair", "park", "town", "hall", "market"},
    "community": {"community", "centre", "park", "town", "hall", "library"},
    "news": set(),
}

LICENSE_PREFIXES = (
    "cc by ", "cc-by-", "cc by-sa", "cc-by-sa", "public domain", "pd-", "cc0",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def plain(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    return BeautifulSoup(html.unescape(clean(value)), "html.parser").get_text(" ", strip=True)


def tokens(value: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9']+", value.lower())
        if len(word) >= 4 and word not in STOP
    }


def story_text(article: dict[str, Any]) -> str:
    body = re.sub(r"<[^>]+>", " ", clean(article.get("content_html") or article.get("body")))
    return " ".join([
        clean(article.get("title")), clean(article.get("excerpt")), body[:2400],
        clean(article.get("area")), clean(article.get("category")),
    ])


def story_places(article: dict[str, Any]) -> set[str]:
    text = story_text(article).lower()
    found = {place for place in LOCAL_PLACES if place in text}
    area = clean(article.get("area")).lower()
    if area:
        found.add(area)
    return found


def story_topics(article: dict[str, Any]) -> set[str]:
    title_words = tokens(clean(article.get("title")))
    category = clean(article.get("category")).lower()
    group = TOPIC_GROUPS.get(category, set())
    direct = title_words & set().union(*TOPIC_GROUPS.values())
    if direct:
        return direct | (title_words & group)
    # If the headline has no explicit visual noun, use category terms but keep
    # the set small so Commons search remains specific to the story location.
    return set(list(group)[:5])


def proper_phrases(article: dict[str, Any]) -> list[str]:
    title = clean(article.get("title"))
    phrases = re.findall(r"\b(?:[A-Z][A-Za-z0-9'&.-]+(?:\s+|$)){1,4}", title)
    result = []
    for phrase in phrases:
        phrase = clean(phrase)
        if len(phrase) < 4 or phrase.lower() in {"rochdale daily"}:
            continue
        if phrase not in result:
            result.append(phrase)
    return result[:4]


def queries(article: dict[str, Any]) -> list[str]:
    places = list(story_places(article))
    topics = list(story_topics(article))
    entities = proper_phrases(article)
    title = clean(article.get("title"))
    qs: list[str] = []

    # Specific named entities and locations first.
    for entity in entities[:3]:
        for topic in topics[:2] or [""]:
            qs.append(clean(f"{entity} {topic}"))
    for place in places[:4]:
        for topic in topics[:4] or [clean(article.get('category'))]:
            qs.append(clean(f"{place} {topic}"))

    useful = [w for w in tokens(title) if w not in {p for place in places for p in place.split()}]
    if useful:
        qs.append(" ".join(useful[:6]))
    return list(dict.fromkeys(q for q in qs if q))[:16]


def licence_allowed(metadata: dict[str, Any]) -> bool:
    combined = f"{plain(metadata.get('LicenseShortName'))} {plain(metadata.get('UsageTerms'))}".lower()
    return any(prefix in combined for prefix in LICENSE_PREFIXES)


def candidate_score(article: dict[str, Any], file_text: str) -> int:
    hay = file_text.lower()
    file_words = tokens(hay)
    places = story_places(article)
    topics = story_topics(article)
    title_words = tokens(clean(article.get("title")))
    entities = [p.lower() for p in proper_phrases(article)]

    place_hits = {p for p in places if p in hay}
    topic_hits = topics & file_words
    title_hits = title_words & file_words
    entity_hits = {e for e in entities if e in hay}

    # This is the important safety rail: a local image needs a matching local
    # place/entity AND a matching visible story subject. A named entity match
    # can stand in for the location when the entity is itself the story subject.
    if places and not place_hits and not entity_hits:
        return -1
    if topics and not topic_hits and len(title_hits) < 2 and not entity_hits:
        return -1

    return (
        len(place_hits) * 5
        + len(entity_hits) * 7
        + len(topic_hits) * 4
        + min(len(title_hits), 5) * 2
    )


def fetch_json(url: str) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def find_candidate(article: dict[str, Any]) -> dict[str, str] | None:
    best: tuple[int, dict[str, str]] | None = None
    seen: set[str] = set()
    for query in queries(article):
        params = {
            "action": "query", "format": "json", "formatversion": "2",
            "generator": "search", "gsrnamespace": "6", "gsrsearch": query,
            "gsrlimit": "12", "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "1600", "origin": "*",
        }
        try:
            data = fetch_json(f"{COMMONS_API}?{urlencode(params)}")
        except (HTTPError, URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
            continue
        for page in data.get("query", {}).get("pages", []):
            if not isinstance(page, dict):
                continue
            title = clean(page.get("title"))
            info_list = page.get("imageinfo") or []
            if not info_list or not isinstance(info_list[0], dict):
                continue
            info = info_list[0]
            metadata = info.get("extmetadata") or {}
            mime = clean(info.get("mime")).lower()
            width, height = int(info.get("width") or 0), int(info.get("height") or 0)
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            if width < MIN_WIDTH or height < MIN_HEIGHT or not licence_allowed(metadata):
                continue
            description = " ".join([
                title,
                plain(metadata.get("ImageDescription")),
                plain(metadata.get("ObjectName")),
                plain(metadata.get("Categories")),
            ])
            score = candidate_score(article, description)
            if score < 7:
                continue
            image_url = clean(info.get("thumburl") or info.get("url"))
            if not image_url or image_url in seen:
                continue
            seen.add(image_url)
            artist = plain(metadata.get("Artist")) or plain(metadata.get("Credit"))
            page_url = "https://commons.wikimedia.org/wiki/" + quote(title.replace(" ", "_"), safe=":_/()")
            candidate = {
                "url": image_url,
                "credit": f"{artist} / Wikimedia Commons" if artist else "Wikimedia Commons",
                "credit_url": page_url,
                "title": title,
            }
            if best is None or score > best[0]:
                best = (score, candidate)
        if best and best[0] >= 14:
            break
    return best[1] if best else None


def download(url: str) -> tuple[bytes, str] | None:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
    try:
        with urlopen(req, timeout=25) as response:
            payload = response.read(15 * 1024 * 1024 + 1)
            content_type = clean(response.headers.get_content_type()).lower()
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None
    if len(payload) < MIN_BYTES or len(payload) > 15 * 1024 * 1024:
        return None
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(content_type)
    if not ext:
        return None
    return payload, ext


def needs_related_commons(article: dict[str, Any]) -> bool:
    image = clean(article.get("image_url"))
    status = clean(article.get("image_status")).lower()
    reuse = clean(article.get("source_image_reuse_status")).lower()
    return (
        not image
        or "placeholder" in image.lower()
        or "area-category-card" in image.lower()
        or status in {"generated-placeholder", "area-category-card", "wikimedia-commons"}
        or reuse in {"category-fallback", "wikimedia-commons-reusable"}
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("assets/article-images"))
    args = parser.parse_args()

    data = json.loads(args.articles.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("articles", [])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    changed = 0

    for article in rows:
        if not isinstance(article, dict) or not needs_related_commons(article):
            continue
        candidate = find_candidate(article)
        if not candidate:
            # If a previous automatic Commons match fails today's stricter
            # relevance test, mark it replaceable so the normal pipeline can
            # use a curated local photograph/card instead of a dubious match.
            if clean(article.get("image_status")).lower() == "wikimedia-commons":
                article["source_image_reuse_status"] = "category-fallback"
            continue
        fetched = download(candidate["url"])
        if not fetched:
            continue
        payload, ext = fetched
        slug = re.sub(r"[^a-z0-9]+", "-", clean(article.get("slug") or article.get("id") or article.get("title")).lower()).strip("-")[:80] or "story"
        digest = hashlib.sha256(payload).hexdigest()[:12]
        path = args.output_dir / f"{slug}-commons-{digest}{ext}"
        if not path.exists():
            path.write_bytes(payload)
        article["image_url"] = path.as_posix()
        article["image_credit"] = candidate["credit"]
        article["image_credit_url"] = candidate["credit_url"]
        article["source_image_candidate_url"] = candidate["url"]
        article["image_status"] = "wikimedia-commons-related"
        article["image_backfill_method"] = "wikimedia-commons-related"
        article["source_image_reuse_status"] = "wikimedia-commons-reusable"
        article["image_match_title"] = candidate["title"]
        article.pop("image_placeholder_reason", None)
        changed += 1
        print(f"commons-related  {slug}  <- {candidate['title']}")

    args.articles.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {changed} article image(s) with strictly related Wikimedia Commons media.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
