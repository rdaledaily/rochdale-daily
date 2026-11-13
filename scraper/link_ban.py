#!/usr/bin/env python3
"""Banned links: one rule, enforced everywhere the paper publishes.

Editor's rule (Rochdale Online, which became a casino-promotion site aimed at
people who had self-excluded from gambling): Rochdale Daily never carries a
gambling, betting-tips or piracy-stream site as a source, and never links one.
The same applies to the other permanently denied outlets in
locality_rules.SOURCE_DENY_DOMAINS (Rochdale Online, uklfi, spam hosts).

How they got in (traced 12 Nov 2026): from 16 Sep to 23 Oct 2026 Google News
searches for Rochdale AFC fixtures returned bet365 "how to watch / prediction
and tips" pages, oddschecker, bettingodds and apwin pages. story_identity
clustered them with the club's own fixture story, so their URLs were appended
to the published story's source_urls and rendered as "Open source N" links.
The 23 Oct collection filter stopped new ones, but 27 article pages built
before it were static HTML that no later run re-rendered, and the render-time
filter failed OPEN when its import failed.

This module is now the single test (is_banned_url) and the sweep that removes
banned links from every public file before each commit. `--check` exits 1 if
any public file still links a banned host; content_hygiene.py runs the fix and
the check in every publishing lane, and check_data_files.py fails CI on one.
functions/_middleware.js strips the same hosts from every HTML response at the
edge, so nothing that reaches the site by any other door is served either.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from locality_rules import (  # noqa: E402  (fail loudly if this is missing)
    GAMBLING_PIRACY_DENY_DOMAINS,
    GAMBLING_PIRACY_HOST_RE,
    SOURCE_DENY_DOMAINS,
)

ROOT = Path(__file__).resolve().parents[1]

# Outlets denied by name in generate_pages.py and the homepage filter that are
# not in locality_rules (kept here so there is one list for links).
EXTRA_DENY_DOMAINS = frozenset({
    "rochdaleonline.co.uk", "rochdaleobserver.co.uk", "pressreader.com", "uklfi.com",
})

_GN_CACHE: dict[str, str] | None = None


def host_of(url: str) -> str:
    try:
        host = (urlparse(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_banned_host(host: str) -> bool:
    host = str(host or "").lower().removeprefix("www.")
    if not host:
        return False
    for domain in (*SOURCE_DENY_DOMAINS, *GAMBLING_PIRACY_DENY_DOMAINS, *EXTRA_DENY_DOMAINS):
        if host == domain or host.endswith("." + domain):
            return True
    return bool(GAMBLING_PIRACY_HOST_RE.search(host))


def _google_news_target(url: str) -> str:
    global _GN_CACHE
    if _GN_CACHE is None:
        _GN_CACHE = {}
        try:
            data = json.loads((ROOT / "google_news_resolutions.json").read_text(encoding="utf-8"))
            for key, value in (data or {}).items():
                if isinstance(value, dict):
                    _GN_CACHE[str(key)] = str(value.get("url") or value.get("blocked") or "")
        except (OSError, ValueError):
            pass
    try:
        from google_news_resolver import _cache_key
        key = _cache_key(url)
    except Exception:  # noqa: BLE001
        key = url
    target = _GN_CACHE.get(key) or _GN_CACHE.get(url) or ""
    return target if "://" in target else ("https://" + target if target else "")


def is_banned_url(url: Any) -> bool:
    """True when a link (directly, or via a resolved Google News redirect)
    leads to a banned host."""
    text = str(url or "").strip()
    if not text:
        return False
    host = host_of(text)
    if is_banned_host(host):
        return True
    if host == "news.google.com":
        target = _google_news_target(text)
        if target and is_banned_host(host_of(target)):
            return True
    return False


# ------------------------------------------------------------------ HTML

_ANCHOR_RE = re.compile(r"<a\b[^>]*?\bhref\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)</a\s*>", re.I | re.S)
_LI_RE = re.compile(r"<li\b[^>]*>(?:(?!</?li\b).)*?</li\s*>", re.I | re.S)
_DETAILS_EMPTY_RE = re.compile(
    r'<details class="article-sources">\s*<summary>Sources</summary>\s*<ul>\s*</ul>\s*</details>', re.I)
_OPEN_SOURCE_RE = re.compile(r"(<a\b[^>]*>)Open source \d+(</a>)")


def _href_banned(match: re.Match) -> bool:
    return is_banned_url(_html.unescape(match.group(2)))


def strip_html(text: str) -> str:
    """Remove banned links. A list item that is only a banned link goes
    whole (the Sources list); any other banned anchor is unwrapped to its
    text. Sources are renumbered so no gap shows."""
    if not text or "href" not in text:
        return text

    def li(match: re.Match) -> str:
        item = match.group(0)
        anchors = list(_ANCHOR_RE.finditer(item))
        if anchors and all(_href_banned(a) for a in anchors):
            rest = _ANCHOR_RE.sub("", item)
            if not re.sub(r"<[^>]+>|\s", "", rest):
                return ""
        return item

    out = _LI_RE.sub(li, text)
    out = _ANCHOR_RE.sub(lambda m: m.group(3) if _href_banned(m) else m.group(0), out)
    if out != text:
        def renumber(block: re.Match) -> str:
            nums = iter(range(1, 10_000))
            return _OPEN_SOURCE_RE.sub(lambda m: f"{m.group(1)}Open source {next(nums)}{m.group(2)}", block.group(0))

        out = re.sub(r'<details class="article-sources">.*?</details>', renumber, out, flags=re.S)
        out = _DETAILS_EMPTY_RE.sub("", out)
    return out


def banned_links_in_html(text: str) -> list[str]:
    return [_html.unescape(m.group(2)) for m in _ANCHOR_RE.finditer(text or "") if _href_banned(m)]


# ------------------------------------------------------------------ JSON

def strip_value(value: Any) -> Any:
    """Remove banned URLs from any JSON structure: list entries that are
    banned URLs (or objects whose url/source_url is banned) are dropped,
    string URL fields that are banned are blanked, HTML strings are cleaned."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(item, str) and item.startswith(("http://", "https://")) and is_banned_url(item):
                out[key] = ""
            else:
                out[key] = strip_value(item)
        return out
    if isinstance(value, list):
        kept = []
        for item in value:
            if isinstance(item, str) and is_banned_url(item):
                continue
            if isinstance(item, dict) and any(
                    is_banned_url(item.get(k)) for k in ("url", "source_url", "href", "link")):
                continue
            kept.append(strip_value(item))
        return kept
    if isinstance(value, str) and "<a" in value:
        return strip_html(value)
    return value


def banned_in_value(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            found.extend(banned_in_value(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(banned_in_value(item))
    elif isinstance(value, str):
        if value.startswith(("http://", "https://")) and is_banned_url(value):
            found.append(value)
        elif "<a" in value:
            found.extend(banned_links_in_html(value))
    return found


def recount_sources(record: Any) -> None:
    """Keep source_count honest after URLs are removed."""
    if isinstance(record, list):
        for item in record:
            recount_sources(item)
    elif isinstance(record, dict):
        if isinstance(record.get("source_urls"), list) and "source_count" in record:
            urls = [u for u in record["source_urls"] if u]
            if record.get("source_url") and record["source_url"] not in urls:
                urls.append(record["source_url"])
            record["source_count"] = max(1, len(urls))
        for key in ("articles", "events", "stories", "items"):
            if isinstance(record.get(key), list):
                recount_sources(record[key])


def clean_resolutions(data: dict) -> dict:
    """Google News redirects that resolved to a banned host keep a tombstone
    (blocked host, no URL) so they are never resolved, cached or linked again."""
    out = {}
    for key, entry in data.items():
        if isinstance(entry, dict) and is_banned_url(entry.get("url")):
            entry = {"url": "", "blocked": host_of(entry["url"]), "at": entry.get("at", "")}
        out[key] = entry
    return out


# ------------------------------------------------------------------ sweep

SKIP_DIRS = {".git", "node_modules", "scraper", "tests", "reports", ".github", "workers", "docs"}
# Files whose job is to NAME banned URLs so they stay blocked.
SKIP_FILES = {"story_blocklist.json", "slow_domains.json"}


def public_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in (".html", ".json", ".xml"):
            continue
        rel = path.relative_to(root)
        if (rel.parts and rel.parts[0] in SKIP_DIRS) or path.name in SKIP_FILES:
            continue
        yield path


def process(path: Path, fix: bool, root: Path) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if path.suffix == ".json":
        if "://" not in raw:
            return []
        try:
            data = json.loads(raw)
        except ValueError:
            return []
        if path.name == "google_news_resolutions.json" and isinstance(data, dict):
            found = [e.get("url") for e in data.values() if isinstance(e, dict) and is_banned_url(e.get("url"))]
            if found and fix:
                path.write_text(json.dumps(clean_resolutions(data), ensure_ascii=False, indent=2), encoding="utf-8")
            return found
        found = banned_in_value(data)
        if found and fix:
            cleaned = strip_value(data)
            recount_sources(cleaned)
            path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""),
                            encoding="utf-8")
        return found
    if path.suffix == ".xml":
        found = [u for u in re.findall(r"<(?:link|loc)>([^<]+)</(?:link|loc)>", raw) if is_banned_url(u)]
        return found  # report only: our feeds never link out
    found = banned_links_in_html(raw)
    if found and fix:
        path.write_text(strip_html(raw), encoding="utf-8")
    return found


def sweep(root: Path = ROOT, fix: bool = False) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    for path in public_files(root):
        found = process(path, fix, root)
        if found:
            results[str(path.relative_to(root))] = found
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fix", action="store_true", help="remove banned links in place")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    root = Path(args.root)
    found = sweep(root, fix=args.fix)
    if args.fix:
        after = sweep(root, fix=False)
        print(json.dumps({"files_cleaned": len(found), "links_removed": sum(map(len, found.values())),
                          "remaining": after}, indent=1))
        return 1 if after else 0
    if found:
        print("BANNED LINKS (gambling / betting / piracy / denied outlets) in public files:")
        for name, urls in sorted(found.items()):
            for url in urls:
                print(f"  {name}: {url}")
        return 1
    print("link_ban: no banned links in public files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
