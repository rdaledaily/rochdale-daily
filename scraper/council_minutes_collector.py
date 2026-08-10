#!/usr/bin/env python3
"""Discover Rochdale Council meeting documents without relying on ModernGov indexes.

ModernGov intermittently blocks GitHub Actions IPs with HTTP 403.  Search engines
still index the council's public meeting/document URLs, so this collector uses
Bing's public RSS search endpoint as a discovery layer, then probes discovered
URLs directly.  It writes council_documents.json for the newsroom pipeline and
retains previously discovered records so a temporary block never erases history.
"""
from __future__ import annotations

import email.utils
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import feedparser
import requests

OUT = Path("council_documents.json")
HOSTS = {"democracy.rochdale.gov.uk", "rochdale.moderngov.co.uk", "www.rochdale.gov.uk", "rochdale.gov.uk"}
QUERIES = [
    'site:democracy.rochdale.gov.uk Rochdale "Minutes" council',
    'site:democracy.rochdale.gov.uk Rochdale "Agenda" council',
    'site:democracy.rochdale.gov.uk Rochdale Cabinet minutes',
    'site:democracy.rochdale.gov.uk Rochdale Planning committee minutes',
    'site:democracy.rochdale.gov.uk Rochdale township minutes',
    'site:democracy.rochdale.gov.uk filetype:pdf Rochdale minutes',
    'site:rochdale.moderngov.co.uk Rochdale minutes',
]
UA = "RochdaleDaily-council-documents/1.0 (news@rochdaledaily.co.uk)"


def load_existing() -> dict[str, dict]:
    if not OUT.exists():
        return {}
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {str(x.get("url")): x for x in data if isinstance(x, dict) and x.get("url")}


def clean_title(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def allowed(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return host.lower() in HOSTS


def discover() -> list[dict]:
    found: dict[str, dict] = {}
    for query in QUERIES:
        rss = f"https://www.bing.com/search?format=rss&q={quote_plus(query)}"
        feed = feedparser.parse(rss, request_headers={"User-Agent": UA})
        for entry in feed.entries:
            url = str(entry.get("link") or "").strip()
            if not url or not allowed(url):
                continue
            title = clean_title(str(entry.get("title") or ""))
            summary = clean_title(str(entry.get("summary") or entry.get("description") or ""))
            published = str(entry.get("published") or "")
            found[url] = {
                "url": url,
                "title": title,
                "search_snippet": summary,
                "search_published": published,
                "discovered_at": datetime.now(timezone.utc).isoformat(),
                "discovery_query": query,
            }
    return list(found.values())


def probe(record: dict) -> dict:
    url = record["url"]
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"}, timeout=20, allow_redirects=True)
        record["http_status"] = r.status_code
        record["final_url"] = r.url
        record["content_type"] = r.headers.get("content-type", "")
        record["content_length"] = len(r.content)
        record["direct_access"] = r.status_code == 200 and len(r.content) > 500
        if record["direct_access"] and "text/html" in record["content_type"].lower():
            text = r.text
            m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
            if m:
                record["page_title"] = clean_title(m.group(1))
            # Preserve a small text fingerprint for change detection, never whole pages.
            body = clean_title(re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.I | re.S))
            record["text_preview"] = body[:1200]
    except Exception as exc:
        record["direct_access"] = False
        record["probe_error"] = str(exc)[:240]
    return record


def main() -> int:
    existing = load_existing()
    for rec in discover():
        prior = existing.get(rec["url"], {})
        merged = {**prior, **rec}
        existing[rec["url"]] = probe(merged)
    records = sorted(existing.values(), key=lambda x: (x.get("search_published", ""), x.get("discovered_at", "")), reverse=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    accessible = sum(1 for x in records if x.get("direct_access"))
    blocked = sum(1 for x in records if x.get("http_status") == 403)
    print(f"Council document index: {len(records)} records; {accessible} directly accessible; {blocked} currently 403-blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
