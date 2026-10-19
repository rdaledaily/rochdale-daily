"""Trace official council and NHS releases through the real collector, item by item.

Read-only. Publishes nothing and changes no source configuration. It calls the
newsroom's own functions (feedparser call, robots check, page_metadata, the
locality / drop / freshness gates) in the same order the collectors do, and
records the first step that stops each item, so a silent zero can be told
apart from "nothing new was published".

Why it exists (20 Oct 2026): the council published 20 releases between 3 Sep
and 16 Oct; six never appeared on Rochdale Daily, including the two newest, and
not one Northern Care Alliance item has ever reached the candidate reservoir.
GitHub Actions logs are not readable from the editing session, so the trace
writes its findings to reports/official_source_trace.json.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import feedparser  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

import scraper as core  # noqa: E402

try:  # the fast lane's own source adjustments, so the trace sees what it sees
    import run_fast_local_pipeline as fast

    fast.configure_sources()
except Exception as error:  # noqa: BLE001
    print(f"::warning::fast-lane source configuration not applied: {error}")

OUT = Path(core.ROOT) / "reports" / "official_source_trace.json"
FEED_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
OFFICIAL_RSS = {"Rochdale Borough Council RSS"}
OFFICIAL_DISCOVERY = {"Northern Care Alliance Rochdale", "Northern Care Alliance News"}
ITEMS_PER_SOURCE = int(os.getenv("TRACE_ITEMS_PER_SOURCE", "12"))


def now() -> datetime:
    return datetime.now(timezone.utc)


def age_hours(value: datetime | None) -> float | None:
    if value is None:
        return None
    return round((now() - value).total_seconds() / 3600, 1)


def robots_verdict(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    verdict: dict[str, Any] = {"base": base}
    try:
        response = core.SESSION.get(base + "/robots.txt", timeout=core.REQUEST_TIMEOUT)
        verdict["robots_status"] = response.status_code
        verdict["robots_excerpt"] = response.text[:1500] if response.status_code == 200 else ""
    except Exception as error:  # noqa: BLE001
        verdict["robots_status"] = f"{type(error).__name__}: {error}"[:200]
    try:
        parser = core.load_robots(base)
        if parser is None:
            verdict["allowed_by_pipeline"] = True
            verdict["note"] = "robots not served with 200, pipeline allows"
        else:
            agent = getattr(core, "ROBOTS_USER_AGENT", None) or getattr(core, "USER_AGENT", "*")
            verdict["agent_checked"] = str(agent)[:120]
            verdict["allowed_by_pipeline"] = bool(parser.can_fetch(str(agent), url))
    except Exception as error:  # noqa: BLE001
        verdict["allowed_by_pipeline"] = f"error: {type(error).__name__}: {error}"[:200]
    return verdict


def raw_fetch(url: str) -> dict[str, Any]:
    try:
        response = core.SESSION.get(url, timeout=core.REQUEST_TIMEOUT)
        return {
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content or b""),
            "starts_with": (response.text or "")[:120],
        }
    except Exception as error:  # noqa: BLE001
        return {"status": f"{type(error).__name__}: {error}"[:200]}


def metadata_step(url: str, render: bool = False) -> dict[str, Any]:
    try:
        meta = core.page_metadata(url, render=render)
    except PermissionError as error:
        return {"error": f"PermissionError (robots): {error}"[:300]}
    except Exception as error:  # noqa: BLE001
        return {"error": f"{type(error).__name__}: {error}"[:300]}
    page_date = core.parse_datetime(meta.get("published"))
    return {
        "final_url": meta.get("url"),
        "title": meta.get("title", "")[:160],
        "description_chars": len(meta.get("description") or ""),
        "body_chars": len(meta.get("body_excerpt") or ""),
        "image": bool(meta.get("image")),
        "page_published_raw": meta.get("published", ""),
        "page_published_age_h": age_hours(page_date),
        "content_type": meta.get("content_type", ""),
    }


def trace_rss(source: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {"source": source["name"], "kind": "rss", "url": source["url"]}
    report["robots"] = robots_verdict(source["url"])
    report["http"] = raw_fetch(source["url"])
    try:
        feed = feedparser.parse(source["url"], agent=FEED_AGENT)
    except Exception as error:  # noqa: BLE001
        report["stopped_at"] = f"feedparser raised {type(error).__name__}: {error}"[:300]
        return report
    report["bozo"] = str(getattr(feed, "bozo_exception", "")) if getattr(feed, "bozo", False) else ""
    report["raw_entries"] = len(feed.entries)
    items = []
    for entry in list(feed.entries)[:ITEMS_PER_SOURCE]:
        url = core.canonicalise_url(str(getattr(entry, "link", "") or ""))
        title = core.strip_markdown(getattr(entry, "title", ""))
        summary_html = str(getattr(entry, "summary", "") or getattr(entry, "description", "") or "")
        summary = core.strip_markdown(BeautifulSoup(summary_html, "lxml").get_text(" ", strip=True))
        published = core.entry_datetime(entry)
        text = f"{title} {summary}"
        item: dict[str, Any] = {
            "title": title[:120],
            "url": url,
            "rss_published_age_h": age_hours(published),
            "summary_chars": len(summary),
            "rss_image": bool(core.rss_image(entry)),
        }
        steps = [
            ("denied source", lambda: core.source_is_denied(source["name"], url)),
            ("missing url/title", lambda: not url or not title),
            ("rss date outside window", lambda: not core.is_fresh(published)),
            ("drop pattern / job / classified", lambda: core.should_drop(text, url)),
            ("location query filter", lambda: not core.location_query_result_allowed(text, source["name"], url, "")),
            ("not local", lambda: not core.source_text_is_local(text, source["name"], url, bool(source.get("trusted_local")))),
        ]
        stopped = ""
        for name, check in steps:
            try:
                if check():
                    stopped = name
                    break
            except Exception as error:  # noqa: BLE001
                stopped = f"{name} (error {type(error).__name__}: {error})"[:200]
                break
        if not stopped and not source.get("rss_only") and (not item["rss_image"] or len(summary) < 100):
            meta = metadata_step(url)
            item["page"] = meta
            if "error" not in meta:
                page_date = core.parse_datetime(meta.get("page_published_raw"))
                effective = page_date or published
                item["effective_published_age_h"] = age_hours(effective)
                if not core.is_fresh(effective):
                    stopped = "page date replaced RSS date and is outside window" if page_date else "date outside window after metadata"
        item["stopped_at"] = stopped or "PASSES COLLECTOR"
        items.append(item)
    report["items"] = items
    return report


def trace_discovery(source: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "source": source["name"],
        "kind": "html discovery",
        "url": source["url"],
        "link_pattern": source.get("link_pattern"),
        "listing_urls": core.discovery_listing_urls(source),
    }
    report["robots"] = robots_verdict(source["url"])
    report["http"] = raw_fetch(source["url"])
    # Every same-site anchor on the listing, with the reason each is or is not taken.
    anchors = []
    try:
        final_url, raw_html = core.fetch_markup(source["url"], render=bool(source.get("render")))
        report["listing_final_url"] = final_url
        report["listing_bytes"] = len(raw_html or "")
        soup = BeautifulSoup(raw_html, "lxml")
        import re

        pattern = re.compile(source["link_pattern"], re.IGNORECASE)
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            url = core.canonicalise_url(core.urljoin(final_url, anchor["href"]))
            if url in seen:
                continue
            seen.add(url)
            if core.domain_of(url) != core.domain_of(final_url):
                continue
            parsed = urlparse(url)
            matches = bool(pattern.search(parsed.path + "?" + parsed.query))
            navigation = core.discovery_link_is_navigation(url, final_url)
            if "news" in parsed.path.lower():
                anchors.append({"url": url, "pattern": matches, "navigation": navigation})
    except PermissionError as error:
        report["stopped_at"] = f"listing refused by robots: {error}"[:300]
        return report
    except Exception as error:  # noqa: BLE001
        report["stopped_at"] = f"listing fetch failed: {type(error).__name__}: {error}"[:300]
        return report
    report["news_anchors_on_listing"] = anchors[:60]
    try:
        links = core.discovery_links(source)
    except Exception as error:  # noqa: BLE001
        report["stopped_at"] = f"discovery_links raised {type(error).__name__}: {error}"[:300]
        return report
    report["links_taken"] = links
    items = []
    for url in links[:ITEMS_PER_SOURCE]:
        item: dict[str, Any] = {"url": url, "page": metadata_step(url, render=bool(source.get("render")))}
        try:
            candidate = core._discovery_candidate(source, url)
        except Exception as error:  # noqa: BLE001
            candidate = None
            item["candidate_error"] = f"{type(error).__name__}: {error}"[:200]
        item["stopped_at"] = "PASSES COLLECTOR" if candidate else "rejected by _discovery_candidate"
        if candidate:
            item["candidate_published_at"] = candidate.source_published_at
        items.append(item)
    report["items"] = items
    if not links:
        report["stopped_at"] = "no article links taken from listing"
    return report


def replay_without_age_limit() -> dict[str, Any]:
    """Run the REAL collectors for the official sources with the age limit lifted.

    The per-item trace above stops at "too old" for anything already past its
    window, which hides whatever would have stopped it when it was fresh. Here
    the window is widened to TRACE_REPLAY_AGE_HOURS so every recent release
    travels the whole collector and the candidate-reservoir door, exactly as a
    run would have taken it. Read-only: nothing is saved but the report.
    """
    replay_hours = int(os.getenv("TRACE_REPLAY_AGE_HOURS", "720"))
    result: dict[str, Any] = {"replay_age_hours": replay_hours}
    saved = (
        core.MAX_NEWS_AGE_HOURS,
        list(core.RSS_SOURCES),
        list(core.DISCOVERY_PAGES),
        core.google_news_sources,
    )
    try:
        core.MAX_NEWS_AGE_HOURS = replay_hours
        try:
            fast.RESERVOIR_HOURS = replay_hours
        except Exception:  # noqa: BLE001
            pass
        core.google_news_sources = lambda: []
        core.RSS_SOURCES[:] = [s for s in saved[1] if s.get("name") in OFFICIAL_RSS]
        official_pages = OFFICIAL_DISCOVERY | {"Rochdale Borough Council News"}
        core.DISCOVERY_PAGES[:] = [s for s in saved[2] if s.get("name") in official_pages]
        result["rss_sources"] = [s["name"] for s in core.RSS_SOURCES]
        result["discovery_sources"] = [s["name"] for s in core.DISCOVERY_PAGES]

        collected: list[Any] = []
        for label, collector in (
            ("rss", core.collect_rss_candidates),
            ("discovery", core.collect_discovery_candidates),
        ):
            try:
                found = list(collector())
                result[f"{label}_collected"] = len(found)
                collected.extend((label, c) for c in found)
            except Exception:  # noqa: BLE001
                result[f"{label}_crash"] = traceback.format_exc()[-1500:]

        blocklist = core.load_story_blocklist()
        rows = []
        for label, candidate in collected:
            door = ""
            try:
                door = fast.reservoir_junk_reason(candidate, blocklist)
                if not door and not fast._reservoir_candidate_allowed(candidate, blocklist):
                    door = "reservoir door: event kind or undated"
            except Exception as error:  # noqa: BLE001
                door = f"door check error {type(error).__name__}: {error}"[:200]
            rows.append(
                {
                    "via": label,
                    "source_name": candidate.source_name,
                    "title": str(candidate.source_title)[:110],
                    "url": candidate.source_url,
                    "published_at": candidate.source_published_at,
                    "kind": candidate.source_kind,
                    "category": candidate.category,
                    "reservoir_door": door or "ADMITTED",
                }
            )
        result["candidates"] = rows
        seen = {row["url"] for row in rows}
        # Official releases the feed lists that no collector produced at all.
        missing = []
        for source in saved[1]:
            if source.get("name") not in OFFICIAL_RSS:
                continue
            feed = feedparser.parse(source["url"], agent=FEED_AGENT)
            for entry in list(feed.entries)[:ITEMS_PER_SOURCE]:
                url = core.canonicalise_url(str(getattr(entry, "link", "") or ""))
                if url and url not in seen:
                    missing.append({"title": core.strip_markdown(getattr(entry, "title", ""))[:110], "url": url})
        result["feed_items_no_collector_produced"] = missing
    finally:
        core.MAX_NEWS_AGE_HOURS = saved[0]
        core.RSS_SOURCES[:] = saved[1]
        core.DISCOVERY_PAGES[:] = saved[2]
        core.google_news_sources = saved[3]
    return result


def main() -> int:
    started = now()
    sources: list[dict[str, Any]] = []
    for source in core.RSS_SOURCES:
        if source.get("name") in OFFICIAL_RSS:
            try:
                sources.append(trace_rss(source))
            except Exception:  # noqa: BLE001
                sources.append({"source": source.get("name"), "crash": traceback.format_exc()[-1500:]})
    for source in core.DISCOVERY_PAGES:
        if source.get("name") in OFFICIAL_DISCOVERY:
            try:
                sources.append(trace_discovery(source))
            except Exception:  # noqa: BLE001
                sources.append({"source": source.get("name"), "crash": traceback.format_exc()[-1500:]})
    try:
        replay = replay_without_age_limit()
    except Exception:  # noqa: BLE001
        replay = {"crash": traceback.format_exc()[-1500:]}
    payload = {
        "traced_at": started.isoformat().replace("+00:00", "Z"),
        "max_news_age_hours": core.MAX_NEWS_AGE_HOURS,
        "sources": sources,
        "replay_without_age_limit": replay,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for report in sources:
        stops: dict[str, int] = {}
        for item in report.get("items", []):
            stops[item["stopped_at"]] = stops.get(item["stopped_at"], 0) + 1
        print(
            f"::notice title={report.get('source')}::"
            f"http={report.get('http', {}).get('status')} robots_ok={report.get('robots', {}).get('allowed_by_pipeline')} "
            f"raw={report.get('raw_entries', len(report.get('links_taken', []) or []))} "
            f"stopped={report.get('stopped_at', '')} items={json.dumps(stops)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
