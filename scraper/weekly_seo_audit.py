#!/usr/bin/env python3
"""Weekly static SEO health and opportunity audit for Rochdale Daily.

Works without private credentials and does NOT pretend it contains Google/Bing
query-performance data. Those come from Search Console and Bing Webmaster.
Preserves article pages and archive URLs; generates a report only.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

SITE = "https://rochdaledaily.co.uk"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
DESC = re.compile(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', re.I | re.S)
CANON = re.compile(r'<link\s+rel=["\']canonical["\']\s+href=["\'](.*?)["\']', re.I | re.S)
ROBOTS = re.compile(r'<meta\s+name=["\']robots["\']\s+content=["\'](.*?)["\']', re.I | re.S)
IMG = re.compile(r'<img\s+[^>]*src=["\']([^"\']+)["\']', re.I)
HEAD = re.compile(r'<head\b[^>]*>(.*?)</head>', re.I | re.S)


def site_path(root: Path, url: str) -> Path | None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "rochdaledaily.co.uk":
        return None
    relative = unquote(parts.path.lstrip("/"))
    if ".." in Path(relative).parts:
        return None
    if not relative or relative.endswith("/"):
        relative += "index.html"
    elif not Path(relative).suffix:
        relative += ".html"
    return root / relative


def head_meta(page: str) -> dict[str, str]:
    head = HEAD.search(page[:45000])
    content = head.group(1) if head else page[:12000]
    fields = {}
    for key, regex in (("title", TITLE), ("description", DESC), ("canonical", CANON), ("robots", ROBOTS)):
        m = regex.search(content)
        fields[key] = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return fields


def report(root: Path) -> dict:
    sitemap = root / "sitemap.xml"
    tree = ET.parse(sitemap)
    urls = [
        (node.findtext(NS + "loc") or "").strip()
        for node in tree.getroot().findall(NS + "url")
    ]
    checks = Counter()
    problems: list[dict[str, str]] = []
    pages: dict[str, dict[str, str]] = {}
    canonicals: dict[str, list[str]] = {}
    titles: dict[str, list[str]] = {}
    max_problems = 1000

    def issue(kind: str, severity: str, path: str, detail: str = "") -> None:
        checks[kind] += 1
        if len(problems) < max_problems:
            problems.append({"code": kind, "severity": severity, "url": path, "detail": detail})

    for url in urls:
        local = site_path(root, url)
        if local is None:
            issue("bad_sitemap_host", "error", url)
            continue
        if not local.is_file():
            issue("sitemap_missing_page", "error", url)
            continue
        text = local.read_text(encoding="utf-8", errors="replace")
        fields = head_meta(text)
        pages[url] = fields

        if not fields["title"]:
            issue("missing_title", "error", url)
        if not fields["description"]:
            issue("missing_description", "warning", url)
        if fields["title"].lower().startswith("news news"):
            issue("duplicate_word_title", "warning", url, fields["title"])
        if "noindex" in fields["robots"].lower():
            issue("sitemap_noindex", "error", url)
        if not fields["canonical"]:
            issue("missing_canonical", "error", url)
        elif fields["canonical"].rstrip("/") != url.rstrip("/"):
            issue("canonical_mismatch", "warning", url, fields["canonical"])

        if fields["title"]:
            titles.setdefault(fields["title"].lower(), []).append(url)
        if fields["canonical"]:
            canonicals.setdefault(fields["canonical"].lower(), []).append(url)

        # Check the actual article hero image rather than every icon/logo on page.
        if "/articles/" in url:
            hero = re.search(r'<figure\s+class="article-hero-image"[^>]*>(.*?)</figure>', text, re.I | re.S)
            if hero:
                match = IMG.search(hero.group(1))
                if not match:
                    issue("hero_without_image", "warning", url)
                else:
                    path = match.group(1)
                    img_file = site_path(root, path if path.startswith(SITE) else SITE + (path if path.startswith("/") else "/" + path))
                    if img_file is None or not img_file.is_file():
                        issue("broken_hero_image", "error", url, path)
                    elif "generated-card" in path:
                        checks["generated_hero_cards"] += 1
            else:
                issue("article_without_hero", "warning", url)

    for title, group in titles.items():
        if len(group) > 1 and "/articles/" in " ".join(group):
            issue("duplicate_page_title", "warning", group[0], ", ".join(group[1:4]))
    for canonical, group in canonicals.items():
        if len(group) > 1:
            issue("duplicate_sitemap_canonical", "error", group[0], ", ".join(group[1:4]))

    for hub in ["wards/index.html", "heywood.html", "milnrow.html"]:
        if (root / hub).is_file():
            url = SITE + ("/wards/" if hub == "wards/index.html" else "/" + hub)
            if url not in urls:
                issue("missing_locality_hub", "warning", url)

    legacy = root / "rochdale.html"
    if legacy.is_file():
        x = head_meta(legacy.read_text(encoding="utf-8", errors="replace"))
        if "noindex" not in x["robots"].lower() or x["canonical"].rstrip("/") != SITE:
            issue("legacy_preview_indexable", "error", SITE + "/rochdale")
        redirects = (root / "_redirects").read_text(encoding="utf-8") if (root / "_redirects").exists() else ""
        if not re.search(r"(?m)^/rochdale\s+/\s+301\s*$", redirects):
            issue("legacy_preview_no_redirect", "warning", SITE + "/rochdale")

    sorted_issues = sorted(problems, key=lambda x: (0 if x["severity"] == "error" else 1, x["code"], x["url"]))
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "website": SITE,
        "sitemap_url_count": len(urls),
        "pages_checked": len(pages),
        "issue_totals": dict(checks),
        "priority_issues": sorted_issues[:75],
        "notes": [
            "This is an on-disk technical audit, not a live Google or Bing indexing report.",
            "Do not interpret sitemap inclusion as proof of indexation.",
            "Generated headline-card count is an editorial opportunity, not a crawl error.",
            "Existing article URLs and the archive are never deleted or rewritten by this audit.",
        ],
    }
    return data


def markdown(data: dict) -> str:
    counts = data["issue_totals"]
    lines = [
        "# Rochdale Daily weekly SEO technical audit", "",
        f"Generated: {data['generated_at']}",
        f"URLs in sitemap: **{data['sitemap_url_count']}**",
        f"Files inspected: **{data['pages_checked']}**", "",
        "## Priorities", "",
    ]
    for key, count in sorted(counts.items(), key=lambda t: (-t[1], t[0])):
        lines.append(f"- {key.replace('_', ' ')}: **{count}**")
    lines.extend(["", "## Top actionable issues", ""])
    for item in data["priority_issues"][:30]:
        lines.append(f"- **{item['severity'].upper()}** {item['code']} at {item['url']}" + (f" ({item['detail']})" if item["detail"] else ""))
    if not data["priority_issues"]:
        lines.append("No priority errors detected in these static checks.")
    lines.extend([
        "", "## What this does not tell us", "",
        "Actual top keywords, impressions, clicks, click-through rates, countries,",
        "and average position require connected Google Search Console and Bing",
        "Webmaster Tools accounts. Never invent those numbers.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("reports/seo-weekly-latest.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/seo-weekly-latest.md"))
    args = parser.parse_args()
    result = report(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(result), encoding="utf-8")
    print(json.dumps({"pages_checked": result["pages_checked"], "issues": result["issue_totals"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
