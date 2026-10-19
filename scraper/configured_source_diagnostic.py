"""Read-only diagnostic: where does each configured source stop producing stories?

Runs every named source through the scraper's OWN code path (robots, fetch,
link pattern, page metadata, freshness, locality) and records the first stage
at which it yields nothing. Publishes nothing and changes no newsroom state.

Usage: python scraper/configured_source_diagnostic.py [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("RESPECT_ROBOTS", "true")

import feedparser  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

import scraper as core  # noqa: E402

TARGETS = [
    "Greater Manchester Police",
    "Roch Valley Radio", "Roch Valley Radio Local News", "Roch Valley Radio Notices",
    "Greater Manchester Fire and Rescue Service",
    "BBC Manchester", "GMCA News", "United Utilities Incidents",
    "National Highways North West", "Rochdale Boroughwide Housing", "Rochdale Riverside News",
    "Northern Care Alliance Rochdale", "Northern Care Alliance News", "Pennine Care NHS",
    "Hopwood Hall College", "Rochdale Sixth Form College", "Falinge Park High School",
    "Oulder Hill Leadership Academy", "Wardle Academy", "St Cuthbert's RC High School",
    "Edgar Wood Academy",
    "Action Together Rochdale News", "Action Together Latest News",
    "Your Trust Rochdale News", "Your Trust Rochdale News Archive",
    "Groundwork Greater Manchester", "Rochdale Creates What's On", "Rochdale Creates News",
    "Visit Rochdale", "Rochdale Town Hall", "Rochdale Town Hall Events",
    "Rochdale Development Agency",
    "Rochdale Hornets", "Rochdale AFC Community Trust",
]
SAMPLE_LINKS = int(os.getenv("DIAG_SAMPLE_LINKS", "6"))


def now() -> datetime:
    return datetime.now(timezone.utc)


def http_probe(url: str) -> dict:
    out: dict = {"url": url}
    try:
        started = time.time()
        response = core.SESSION.get(url, timeout=max(10, core.REQUEST_TIMEOUT), allow_redirects=True)
        out.update({
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content or b""),
            "seconds": round(time.time() - started, 2),
            "server": response.headers.get("server", ""),
        })
        text = response.text or ""
        low = text[:4000].lower()
        out["looks_like_challenge"] = any(m in low for m in (
            "just a moment", "cf-chl", "attention required", "access denied",
            "captcha", "incapsula", "request unsuccessful", "akamai"))
        soup = BeautifulSoup(text, "lxml")
        out["anchors"] = len(soup.find_all("a", href=True))
        out["visible_text_chars"] = len(soup.get_text(" ", strip=True))
        out["feeds_advertised"] = [
            urljoin(response.url, link.get("href"))
            for link in soup.find_all("link", attrs={"type": ["application/rss+xml", "application/atom+xml"]})
            if link.get("href")
        ][:5]
        out["_text"] = text
    except Exception as exc:  # network refusal, timeout, TLS
        out.update({"status": 0, "error": f"{type(exc).__name__}: {exc}"[:300]})
    return out


def robots(url: str) -> dict:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    try:
        response = core.SESSION.get(base + "/robots.txt", timeout=max(10, core.REQUEST_TIMEOUT))
        status = response.status_code
    except Exception as exc:
        return {"robots_status": 0, "robots_error": str(exc)[:200], "allowed": True}
    allowed = core.robots_allows(url)
    return {"robots_status": status, "allowed": bool(allowed)}


def diagnose_rss(source: dict) -> dict:
    result = {"kind": "rss", "name": source["name"], "url": source["url"]}
    probe = http_probe(source["url"])
    text = probe.pop("_text", "")
    result["http"] = probe
    result["robots"] = robots(source["url"])
    feed = feedparser.parse(text.encode("utf-8") if text else b"")
    result["parse_error"] = str(getattr(feed, "bozo_exception", "")) if getattr(feed, "bozo", False) else ""
    ages = []
    for entry in feed.entries:
        published = core.entry_datetime(entry)
        if published:
            ages.append((now() - published).total_seconds() / 86400)
    result["entries"] = len(feed.entries)
    result["newest_entry_days"] = round(min(ages), 2) if ages else None
    result["entries_last_7d"] = sum(1 for a in ages if a <= 7)
    # What the real collector keeps from this one feed.
    saved_rss, saved_google = core.RSS_SOURCES[:], core.google_news_sources
    try:
        core.RSS_SOURCES[:] = [source]
        core.google_news_sources = lambda: []
        kept = core.collect_rss_candidates()
        result["candidates_produced"] = len(kept)
        result["candidate_titles"] = [c.source_title[:100] for c in kept[:5]]
    except Exception as exc:
        result["collector_error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        core.RSS_SOURCES[:] = saved_rss
        core.google_news_sources = saved_google
    return result


def diagnose_discovery(source: dict) -> dict:
    result = {"kind": "discovery", "name": source["name"], "url": source["url"],
              "link_pattern": source.get("link_pattern"), "render": bool(source.get("render"))}
    listing = core.discovery_listing_urls(source)[0]
    probe = http_probe(listing)
    text = probe.pop("_text", "")
    result["http"] = probe
    result["robots"] = robots(listing)
    try:
        links = core.discovery_links(source)
    except Exception as exc:
        links = []
        result["links_error"] = f"{type(exc).__name__}: {exc}"[:300]
    result["matched_links"] = len(links)
    result["sample_links"] = links[:SAMPLE_LINKS]
    if text and not links:
        # Show what the page does link to, so the pattern can be corrected.
        soup = BeautifulSoup(text, "lxml")
        same_host = []
        host = urlparse(probe.get("final_url") or listing).netloc
        for anchor in soup.find_all("a", href=True):
            url = urljoin(probe.get("final_url") or listing, anchor["href"])
            if urlparse(url).netloc == host and url not in same_host:
                same_host.append(url)
        result["unmatched_same_host_links"] = same_host[:25]
    outcomes = []
    for url in links[:SAMPLE_LINKS]:
        row = {"url": url}
        try:
            meta = core.page_metadata(url, render=bool(source.get("render")))
            published = core.parse_datetime(meta.get("published"))
            row.update({
                "title": (meta.get("title") or "")[:100],
                "published": meta.get("published") or "",
                "fresh": bool(core.is_fresh(published)),
                "body_chars": len(meta.get("body_excerpt") or ""),
            })
            candidate = core._discovery_candidate(source, url)
            row["became_candidate"] = candidate is not None
            if candidate is None:
                text_all = f"{meta.get('title','')} {meta.get('description','')} {meta.get('body_excerpt','')}"
                row["local"] = bool(core.source_text_is_local(
                    text_all, source["name"], meta.get("url") or url, bool(source.get("trusted_local"))))
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"[:200]
        outcomes.append(row)
    result["link_outcomes"] = outcomes
    result["candidates_from_sample"] = sum(1 for r in outcomes if r.get("became_candidate"))
    return result


def verdict(row: dict) -> str:
    http = row.get("http", {})
    status = http.get("status", 0)
    if status == 0:
        return "UNREACHABLE: " + http.get("error", "")[:120]
    if status in (401, 403, 429) or http.get("looks_like_challenge"):
        return f"BLOCKED: HTTP {status}{' + challenge page' if http.get('looks_like_challenge') else ''}"
    if status >= 400:
        return f"BROKEN URL: HTTP {status}"
    if not row.get("robots", {}).get("allowed", True):
        return "ROBOTS DISALLOWS"
    if row["kind"] == "rss":
        if row.get("parse_error") and not row.get("entries"):
            return "NOT A FEED: " + row["parse_error"][:100]
        if not row.get("entries_last_7d"):
            return f"STALE FEED: newest entry {row.get('newest_entry_days')} days old"
        if not row.get("candidates_produced"):
            return f"FILTERED: {row['entries_last_7d']} fresh entries, 0 candidates"
        return f"OK: {row['candidates_produced']} candidates"
    if not row.get("matched_links"):
        if http.get("visible_text_chars", 0) < 1500 or http.get("anchors", 0) < 15:
            return "NEEDS BROWSER: page body is empty without JavaScript"
        return "LINK PATTERN MATCHES NOTHING"
    if row.get("candidates_from_sample"):
        return f"OK: {row['candidates_from_sample']}/{len(row['link_outcomes'])} sampled links became candidates"
    stale = sum(1 for r in row["link_outcomes"] if r.get("fresh") is False)
    if stale:
        return f"NO FRESH ITEMS / NO DATES: {stale}/{len(row['link_outcomes'])} sampled pages not fresh"
    return "FILTERED AT CANDIDATE STAGE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/configured_source_diagnostic.json")
    args = parser.parse_args(argv)
    sources = {s["name"]: ("rss", s) for s in core.RSS_SOURCES}
    for s in core.DISCOVERY_PAGES:
        sources.setdefault(s["name"], ("discovery", s))
        if s["name"] in sources and sources[s["name"]][0] == "rss":
            sources[s["name"] + " (page)"] = ("discovery", s)
    rows = []
    for name in TARGETS:
        for key in (name, name + " (page)"):
            if key not in sources:
                continue
            kind, source = sources[key]
            try:
                row = diagnose_rss(source) if kind == "rss" else diagnose_discovery(source)
            except Exception:
                row = {"kind": kind, "name": key, "url": source.get("url"), "http": {},
                       "crash": traceback.format_exc()[-800:]}
            row["verdict"] = verdict(row) if "crash" not in row else "DIAGNOSTIC CRASHED"
            print(f"{row['verdict'][:70]:70} | {key}", flush=True)
            rows.append(row)
        if not any(k in sources for k in (name, name + " (page)")):
            rows.append({"name": name, "verdict": "NOT CONFIGURED"})
            print(f"{'NOT CONFIGURED':70} | {name}", flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({
        "checked_at": now().isoformat().replace("+00:00", "Z"),
        "runner": os.getenv("RUNNER_NAME", "local"),
        "user_agent": core.SESSION.headers.get("User-Agent", ""),
        "results": rows,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
