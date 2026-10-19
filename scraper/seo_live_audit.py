#!/usr/bin/env python3
"""Check the live site the way a search engine crawler meets it.

Reads robots.txt and every sitemap from rochdaledaily.co.uk, then requests each
listed URL WITHOUT following redirects and records what comes back. It checks
the things that decide whether a page can be indexed and ranked:

  * status code (200, or a redirect / error that wastes crawl and splits signals)
  * redirect target, when there is one
  * that the page's <link rel="canonical"> is the very URL listed in the sitemap
    and that the canonical URL itself answers 200
  * robots meta and X-Robots-Tag (no accidental noindex)
  * structured data blocks parse as JSON
  * response time

Writes reports/seo_live_audit.json and prints a short summary. Read-only: it
changes nothing on the site. Run it from GitHub Actions (seo-audit.yml), which
can reach the live site.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SITE = "https://rochdaledaily.co.uk"
ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "seo_live_audit.json"
UA = "Mozilla/5.0 (compatible; RochdaleDailySEOAudit/1.0; +https://rochdaledaily.co.uk)"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(url: str, read: bool = True) -> dict:
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with OPENER.open(request, timeout=30) as response:
            body = response.read(2_000_000).decode("utf-8", "replace") if read else ""
            return {"status": response.status, "headers": dict(response.headers), "body": body,
                    "ms": int((time.monotonic() - started) * 1000)}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "headers": dict(error.headers or {}), "body": "",
                "ms": int((time.monotonic() - started) * 1000)}
    except Exception as error:  # network failure
        return {"status": 0, "headers": {}, "body": "", "error": f"{type(error).__name__}: {error}",
                "ms": int((time.monotonic() - started) * 1000)}


def sitemap_urls(xml: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml or "")


def page_facts(html: str) -> dict:
    head = html.split("</head>", 1)[0]
    canonical = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', head)
    robots = re.search(r'<meta[^>]+name="robots"[^>]+content="([^"]+)"', head)
    title = re.search(r"<title>(.*?)</title>", head, re.S)
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    invalid = 0
    for block in blocks:
        try:
            json.loads(block)
        except ValueError:
            invalid += 1
    return {"canonical": canonical.group(1) if canonical else "", "robots": robots.group(1) if robots else "",
            "title": (title.group(1).strip() if title else "")[:120], "jsonld": len(blocks), "jsonld_invalid": invalid}


def check(url: str) -> dict:
    result = fetch(url)
    row = {"url": url, "status": result["status"], "ms": result["ms"]}
    if result.get("error"):
        row["error"] = result["error"]
    location = result["headers"].get("Location") or result["headers"].get("location")
    if location:
        row["redirect_to"] = location if location.startswith("http") else SITE + location
    xrobots = result["headers"].get("X-Robots-Tag") or result["headers"].get("x-robots-tag")
    if xrobots:
        row["x_robots_tag"] = xrobots
    if result["status"] == 200 and result["body"]:
        row.update(page_facts(result["body"]))
    return row


def main() -> int:
    started = datetime.now(timezone.utc)
    robots = fetch(SITE + "/robots.txt")
    maps = re.findall(r"(?im)^sitemap:\s*(\S+)", robots["body"]) or [SITE + "/sitemap.xml"]
    sitemaps: dict[str, dict] = {}
    urls: dict[str, list[str]] = {}
    for sitemap in maps:
        response = fetch(sitemap)
        listed = sitemap_urls(response["body"])
        sitemaps[sitemap] = {"status": response["status"], "urls": len(listed),
                             "content_type": response["headers"].get("Content-Type", "")}
        for url in listed:
            if url.startswith(SITE):
                urls.setdefault(url, []).append(sitemap.rsplit("/", 1)[-1])
    pages = [u for u in urls if not re.search(r"\.(jpg|jpeg|png|webp|gif)$", u, re.I)]
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(check, pages))

    problems: Counter = Counter()
    examples: dict[str, list[str]] = {}

    def flag(kind: str, url: str) -> None:
        problems[kind] += 1
        examples.setdefault(kind, [])
        if len(examples[kind]) < 15:
            examples[kind].append(url)

    canonical_targets = set()
    for row in rows:
        url = row["url"]
        if row["status"] in (301, 302, 307, 308):
            flag(f"sitemap URL redirects ({row['status']})", url)
        elif row["status"] != 200:
            flag(f"sitemap URL answers {row['status']}", url)
            continue
        if row["status"] != 200:
            continue
        canonical = row.get("canonical", "")
        if not canonical:
            flag("no canonical link", url)
        elif canonical.rstrip("/") != url.rstrip("/"):
            flag("canonical differs from sitemap URL", url)
            canonical_targets.add(canonical)
        if "noindex" in row.get("robots", "") or "noindex" in row.get("x_robots_tag", ""):
            flag("listed in sitemap but noindex", url)
        if row.get("jsonld_invalid"):
            flag("structured data does not parse", url)
        if row["ms"] > 2000:
            flag("slow response (>2s)", url)

    canonical_checks = {}
    for target in sorted(canonical_targets)[:200]:
        canonical_checks[target] = fetch(target, read=False)["status"]
        if canonical_checks[target] != 200:
            flag(f"canonical URL answers {canonical_checks[target]}", target)

    statuses = Counter(row["status"] for row in rows)
    report = {
        "checked_at": started.isoformat().replace("+00:00", "Z"),
        "robots_status": robots["status"],
        "robots_txt": robots["body"][:2000],
        "sitemaps": sitemaps,
        "pages_checked": len(rows),
        "status_counts": {str(k): v for k, v in sorted(statuses.items())},
        "median_ms": sorted(r["ms"] for r in rows)[len(rows) // 2] if rows else 0,
        "problems": dict(problems.most_common()),
        "examples": examples,
        "canonical_target_status": canonical_checks,
        "pages": rows,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"robots.txt {robots['status']}; sitemaps: " + ", ".join(f"{k.rsplit('/',1)[-1]} {v['status']} ({v['urls']} URLs)" for k, v in sitemaps.items()))
    print(f"pages checked {len(rows)}; statuses {dict(statuses)}; median {report['median_ms']} ms")
    for kind, count in problems.most_common():
        print(f"  {count:5d}  {kind}   e.g. {examples[kind][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
