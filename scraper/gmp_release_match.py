#!/usr/bin/env python3
"""Find GMP's own news release for a crime or police story, so its photo can
be used under the paper's GMP permission.

Why this exists
---------------
Measured 7 Nov 2026: 18 crime, court and sensitive stories sat on beige cards.
The editor's rule is that such stories get no guessed place photo, but may use
the photo the source published under a permission already held. Only 1 of the
18 linked to a GMP page (and that was GMP's home page): most reach the paper
through other outlets even when GMP issued its own release and photo.

What it does
------------
Reads GMP's News and Appeals listings (the first few pages, robots-respecting,
through gmp_watch.Fetcher) and matches each release headline to recent crime
and police stories on a card. A match needs, all at once:

  * the release published from 10 days before to 2 days after the story;
  * at least two distinctive words shared between the release headline and
    the story's headline or standfirst, one of them a proper name (a person,
    a street, a business) that is not a town or a police word;
  * the release to be about this borough: a borough town in its headline, or
    a shared street or person name.

Report first
------------
Mode "report" (the default) only records the matches in image_repair_report.json
so they can be checked against the stories. Mode "apply" (GMP_RELEASE_MATCH=apply)
adds the release URL to the story's sources, recorded as gmp_release_url, and
the granted-source photo step then takes the release's own photo.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

MODE = os.getenv("GMP_RELEASE_MATCH", "report").strip().lower()
LISTING_PAGES = int(os.getenv("GMP_RELEASE_PAGES", "3"))
DETAIL_FETCH_LIMIT = int(os.getenv("GMP_RELEASE_DETAIL_FETCHES", "40"))
STORY_MAX_AGE_DAYS = 45
BEFORE_DAYS, AFTER_DAYS = 10, 2

TOWNS = frozenset(
    "rochdale middleton heywood littleborough milnrow newhey whitworth wardle norden bamford castleton "
    "smallbridge kirkholt balderstone syke healey spotland deeplish falinge firgrove langley alkrington "
    "boarshaw darnhill hopwood".split()
)
# Words that look like names in a headline but name nobody in particular.
_COMMON = frozenset(
    "police officers officer gmp greater manchester man woman men women boy girl teenager teen child children "
    "people person driver drivers pedestrian appeal appeals arrest arrested arrests charged charge court jailed "
    "jail sentenced investigation update latest news missing found safe search help information witness "
    "witnesses cctv after following during into over under with from about their the and for this that "
    "was were has have had been being will would could should after against before since when where which "
    "who what why how two three four five six seven eight nine ten operation crime gang drugs drug vehicle "
    "vehicles car cars road street lane avenue town centre north south east west new old year years month "
    "months day days week weeks monday tuesday wednesday thursday friday saturday sunday january february "
    "march april may june july august september october november december uk british english".split()
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z’'-]+|\d{1,3}")
_POLICE_WORDS = re.compile(r"\b(?:police|gmp|officer|arrest|charged|jailed|court|appeal|crime|stolen|"
                           r"assault|stab|murder|burglar|robbery|missing|drugs?|seized|pursuit)\w*\b", re.I)


def _plain(value: Any) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", str(value or "")).split())


def _tokens(text: str) -> tuple[set[str], set[str]]:
    """(distinctive words, proper names) from a headline or standfirst."""
    words, names = set(), set()
    for raw in _WORD_RE.findall(text):
        word = re.sub(r"[’']s$", "", raw)
        low = word.casefold()
        if low in _COMMON or len(low) < 3 and not low.isdigit():
            continue
        words.add(low)
        if word[:1].isupper() and low not in TOWNS and not low.isdigit():
            names.add(low)
    return words, names


_MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
_DMY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")


def _when(value: Any) -> datetime | None:
    """ISO, RFC 822 or "29 September 2026" anywhere in the text; None when no
    full date (day, month and year) can be read."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        pass
    match = _DMY_RE.search(text)
    if match:
        day, month_name, year = match.groups()
        month = next((n for name, n in _MONTHS.items() if name.startswith(month_name.casefold()[:3])), 0)
        try:
            return datetime(int(year), month, int(day), tzinfo=timezone.utc) if month else None
        except ValueError:
            return None
    return None


def candidate_story(article: dict[str, Any], now: datetime) -> bool:
    """A recent crime or police story still on a card or the stock police photo."""
    title = _plain(article.get("title"))
    crime = (str(article.get("category") or "").casefold() in {"crime", "courts"}
             or bool(article.get("police_matter")) or bool(_POLICE_WORDS.search(title)))
    if not crime or article.get("gmp_release_url"):
        return False
    status = str(article.get("image_status") or "")
    url = str(article.get("image_url") or "")
    on_card = ("generated" in status or "placeholder" in status or not url
               or status == "standard-police-image" or url.endswith("/police.jpg"))
    if not on_card or any("gmp.police.uk/news/" in str(u) for u in _sources(article)):
        return False
    published = _when(article.get("first_published_at") or article.get("published_at"))
    return bool(published) and now - published <= timedelta(days=STORY_MAX_AGE_DAYS)


def _sources(article: dict[str, Any]) -> list[str]:
    urls = [article.get("source_url")] + list(article.get("source_urls") or [])
    return [str(u) for u in urls if u]


_ALLOWED_HOLDS = frozenset({"sentencing", "conviction", "court", "court appearance", "plea"})
_MISSING_RE = re.compile(r"\bmissing\b|\bfound safe\b|\blocated\b", re.I)


def photo_safe(release_title: str) -> bool:
    """Whether a release's photo may be used at all.

    Taken: appeals (wanted people, witnesses, CCTV), general news, and
    sentencing releases, where GMP publishes a custody photo for that purpose.
    Never taken: active proceedings (charged, trial, remand: a photo can
    prejudice identification evidence), sexual offences (a defendant's photo
    can identify the complainant), missing people (GMP asks for their photos
    to come down once found), anything about a child or safeguarding, and
    inquests or suicides. Uses the GMP watcher's own legal patterns."""
    from gmp_watch import _COMPILED_HOLDS, SAFEGUARDING_PATTERN
    reasons = {reason for pattern, reason in _COMPILED_HOLDS if pattern.search(release_title)}
    if reasons - _ALLOWED_HOLDS:
        return False
    if reasons & {"court", "court appearance", "plea", "conviction"} and "sentencing" not in reasons:
        return False
    if _MISSING_RE.search(release_title) and not re.search(r"\bwanted\b", release_title, re.I):
        return False
    if mentions_child(release_title) or SAFEGUARDING_PATTERN.search(release_title):
        return False
    return True


_CHILD_WORDS_RE = re.compile(r"\b(?:child|children|kids?|boy|boys|girl|girls|teenager|teenagers|teen|teens|"
                             r"youngsters?|juveniles?|pupils?|schoolgirls?|schoolboys?|baby|babies|toddlers?|"
                             r"infants?|minors?)\b", re.I)
_AGE_RE = re.compile(r"\b(\d{1,2})[- ]year[- ]olds?\b|\baged? (\d{1,2})\b|,\s*(\d{1,2})\s*,", re.I)


def mentions_child(text: str) -> bool:
    """A child is named or described: a child word, or an age under 18
    ("13-year-old", "aged 15", "Boy, 13,"). gmp_watch's CHILD_PATTERN treats
    any age as a child because it is paired there with safeguarding words;
    used alone it rejected "wanted man, 35-year-old" appeals."""
    if _CHILD_WORDS_RE.search(text):
        return True
    for match in _AGE_RE.finditer(text):
        age = next(int(g) for g in match.groups() if g)
        if age < 18:
            return True
    return False


def score(article: dict[str, Any], release: dict[str, str]) -> tuple[int, list[str]]:
    """Shared distinctive words, or 0 when the match rules are not all met."""
    story_text = _plain(article.get("title")) + " " + _plain(article.get("excerpt"))
    story_words, story_names = _tokens(story_text)
    rel_words, rel_names = _tokens(release.get("title", ""))
    shared = story_words & rel_words
    shared_names = story_names & rel_names
    if len(shared) < 2 or not shared_names:
        return 0, []
    # A release with no readable date never matches: the same person can be in
    # several releases, and only the date ties a photo to this incident.
    released, published = _when(release.get("published")), _when(
        article.get("first_published_at") or article.get("published_at"))
    if not released or not published or not (
            published - timedelta(days=BEFORE_DAYS) <= released <= published + timedelta(days=AFTER_DAYS)):
        return 0, []
    rel_low = release.get("title", "").casefold()
    if not (any(re.search(r"\b" + town + r"\b", rel_low) for town in TOWNS) or len(shared_names) >= 2):
        return 0, []
    return len(shared) + 2 * len(shared_names), sorted(shared)


def best_matches(articles: Iterable[dict[str, Any]], releases: list[dict[str, str]],
                 now: datetime | None = None) -> list[dict[str, Any]]:
    """One release per story and one story per release, strongest first."""
    now = now or datetime.now(timezone.utc)
    scored = []
    for article in articles:
        if not candidate_story(article, now):
            continue
        for release in releases:
            if not photo_safe(release.get("title", "")):
                continue
            points, shared = score(article, release)
            if points:
                scored.append((points, article, release, shared))
    scored.sort(key=lambda row: -row[0])
    taken_stories, taken_releases, out = set(), set(), []
    for points, article, release, shared in scored:
        slug, url = str(article.get("slug") or ""), release["url"]
        if slug in taken_stories or url in taken_releases:
            continue
        taken_stories.add(slug)
        taken_releases.add(url)
        out.append({"slug": slug, "story": _plain(article.get("title")), "release_url": url,
                    "release_title": release.get("title", ""), "release_published": release.get("published", ""),
                    "shared_words": shared, "score": points, "article": article})
    return out


def fetch_releases() -> list[dict[str, str]]:
    """GMP's News and Appeals listings, first LISTING_PAGES pages of each."""
    from gmp_watch import GMP_LISTINGS, Fetcher, parse_listing
    fetcher = Fetcher()
    releases: list[dict[str, str]] = []
    seen: set[str] = set()
    for listing in GMP_LISTINGS:
        for page in range(1, LISTING_PAGES + 1):
            url = listing if page == 1 else f"{listing}&page={page}"
            try:
                if not fetcher.robots_allows(url):
                    break
                status, text = fetcher.get(url)
            except Exception:
                break
            if status != 200 or not text:
                break
            items = [item for item in parse_listing(text, url) if "/news/greater-manchester/news/" in item["url"]]
            for item in items:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    releases.append(item)
            if not items:
                break
    # A listing without a machine-readable date: read the release's own page
    # for it. Still undated after that, the release cannot match (score()).
    from gmp_watch import parse_article
    fetched = 0
    for item in releases:
        if _when(item.get("published")) or fetched >= DETAIL_FETCH_LIMIT:
            continue
        fetched += 1
        try:
            if fetcher.robots_allows(item["url"]):
                status, html = fetcher.get(item["url"])
                if status == 200 and html:
                    item["published"] = parse_article(html).get("published", "") or ""
        except Exception:
            continue
    return releases


def run(articles: list[dict[str, Any]], mode: str = MODE,
        releases: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Match, and in apply mode attach the release to the story's sources."""
    try:
        releases = fetch_releases() if releases is None else releases
    except Exception as error:  # a failed listing never stops the image run
        return {"mode": mode, "releases_read": 0, "error": str(error)[:160], "matches": []}
    matches = best_matches(articles, releases)
    applied = 0
    if mode == "apply":
        for match in matches:
            article = match["article"]
            article["gmp_release_url"] = match["release_url"]
            urls = list(article.get("source_urls") or [])
            if match["release_url"] not in urls:
                urls.append(match["release_url"])
                names = list(article.get("source_names") or [])
                if len(names) == len(urls) - 1:
                    names.append("Greater Manchester Police")
                    article["source_names"] = names
                article["source_urls"] = urls
            applied += 1
    return {"mode": mode, "releases_read": len(releases), "applied": applied,
            "matches": [{k: v for k, v in m.items() if k != "article"} for m in matches]}
