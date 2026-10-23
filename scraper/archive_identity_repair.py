"""Keep article URLs and canonicals honest on every run.

Why (23 Oct 2026): the old story-merge bug (root cause fixed in #71) left
archived pages showing the wrong story for their URL, wrong headlines over
other stories, and canonicals pointing at unrelated stories -- e.g. six
URLs, including grooming-gang deportation and councillors' pay, displayed
"Man Arrested Following Thefts in Bamford Area", and the 3-0 Shrewsbury win
declared a youth-team defeat as its canonical.

Static edits to those pages conflict with the pipeline, which rewrites
archived pages on most runs, so the repair lives here and runs inside
generate_pages.main() in every lane:

1. Retired URLs. Every `/articles/<slug>` source in `_redirects` is a
   retired URL. Its page file is deleted so it can never return to the
   sitemap or serve stale content. A slug that is still in the live feed is
   never deleted (logged instead): the feed wins over a stale rule.
2. Canonicals. A page whose canonical names a missing page is pointed at
   that URL's redirect destination when that destination carries the same
   story, otherwise at itself. A page whose canonical names an unrelated
   story (headlines share under half their distinctive words) is pointed at
   itself. Near-duplicate consolidation (consolidate_duplicate_article_signals)
   only ever pairs strongly similar headlines, so it is unaffected.
3. Identical archived headlines. When two or more archived (not live) pages
   carry exactly the same <title> and each claims to be the original, they
   compete with each other in search. All but the earliest-published point
   their canonical at the earliest. Groups containing a live story are left
   to consolidate_duplicate_article_signals, which owns live duplicates.
   The story text must match as well as the headline. Measured on the full
   lane 23 Oct 2026: 3 groups, 5 competing pages, all archived AFC reports.
4. Deference. Where two pages carry the same copied body, archive_integrity.py
   (which every lane runs after this) owns the canonical; this module leaves it.

Only the canonical <link> and og:url are touched. Idempotent.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://rochdaledaily.co.uk"
_STOP = set(
    "the a an and of in to for on at with by from as is are new rochdale "
    "rochdales after over amid its their into up has have be will live update "
    "latest".split()
)
_CANONICAL = re.compile(r'<link rel="canonical" href="([^"]+)"')
_OG_URL = re.compile(r'(<meta property="og:url" content=")[^"]+(")')
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_BODY = re.compile(r'<div class="article-copy"[^>]*>(.*?)(?:<details|<section|</article>|$)', re.S)
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_PUBLISHED = re.compile(r'<meta property="article:published_time" content="([^"]+)"')
_NOINDEX = re.compile(r'<meta name="robots" content="[^"]*noindex')


def _tokens(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2 and word not in _STOP and not word.isdigit()
    }


def _headline(page: str) -> set[str]:
    match = _H1.search(page)
    return _tokens(html.unescape(re.sub(r"<[^>]+>", "", match.group(1)))) if match else set()


def _body(page: str) -> set[str]:
    match = _BODY.search(page)
    return _tokens(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))) if match else set()


def _same_body(left: set[str], right: set[str]) -> bool:
    """Identical or near-identical story text (the old body-copy bug).
    archive_integrity.py owns canonicals for such pages and runs after this,
    so this module must not overrule it."""
    if len(left) < 20 or len(right) < 20:
        return False
    return len(left & right) / len(left | right) >= 0.6


def _same_story(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return True  # redirect stubs and headline-less pages: never second-guess
    return len(left & right) / min(len(left), len(right)) >= 0.5


def _slug_of(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")


def retired_article_redirects(redirects_path: Path) -> dict[str, str]:
    """Map retired article slug -> redirect destination, from _redirects."""
    retired: dict[str, str] = {}
    try:
        lines = redirects_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return retired
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and not line.lstrip().startswith("#") and parts[0].startswith("/articles/"):
            if "*" in parts[0] or ":" in parts[0]:
                continue  # dynamic rules are not page retirements
            retired.setdefault(_slug_of(parts[0]), parts[1])
    return retired


def repair(articles_dir: Path, redirects_path: Path, live_slugs: Iterable[str]) -> dict[str, int]:
    live = set(live_slugs)
    retired = retired_article_redirects(redirects_path)
    stats = {"retired_pages_removed": 0, "retired_but_live_kept": 0,
             "canonicals_to_new_home": 0, "canonicals_to_self": 0,
             "duplicate_titles_consolidated": 0}

    for slug in retired:
        page = articles_dir / f"{slug}.html"
        if slug in live:
            if page.exists():
                stats["retired_but_live_kept"] += 1
                print(f"Archive repair: {slug} is retired in _redirects but still live; page kept.")
            continue
        if page.exists():
            page.unlink()
            stats["retired_pages_removed"] += 1

    pages = {path.stem: path for path in articles_dir.glob("*.html")}
    headlines: dict[str, set[str]] = {}

    def headline(slug: str) -> set[str]:
        if slug not in headlines:
            headlines[slug] = _headline(pages[slug].read_text(encoding="utf-8"))
        return headlines[slug]

    bodies: dict[str, set[str]] = {}

    def body(slug: str) -> set[str]:
        if slug not in bodies:
            bodies[slug] = _body(pages[slug].read_text(encoding="utf-8"))
        return bodies[slug]

    for slug, path in pages.items():
        text = path.read_text(encoding="utf-8")
        match = _CANONICAL.search(text)
        if not match:
            continue
        target = _slug_of(match.group(1))
        if target == slug or "/articles/" not in match.group(1):
            continue
        new = None
        if target not in pages:
            destination = retired.get(target, "")
            home = _slug_of(destination) if destination.startswith("/articles/") else ""
            new = home if home in pages and home != slug and _same_story(headline(slug), headline(home)) else slug
        elif not _same_story(headline(slug), headline(target)):
            if _same_body(body(slug), body(target)):
                continue  # same copied text: archive_integrity's decision stands
            new = slug
        if not new:
            continue
        url = f"{SITE}/articles/{new}.html"
        fixed = _CANONICAL.sub(f'<link rel="canonical" href="{url}"', text, count=1)
        if new == slug:
            fixed = _OG_URL.sub(lambda m: m.group(1) + url + m.group(2), fixed, count=1)
            stats["canonicals_to_self"] += 1
        else:
            stats["canonicals_to_new_home"] += 1
        path.write_text(fixed, encoding="utf-8")

    # 3. Identical archived headlines that each claim to be the original.
    groups: dict[str, list[tuple[str, str, Path]]] = {}
    for slug, path in pages.items():
        if slug in live:
            continue
        text = path.read_text(encoding="utf-8")
        title = _TITLE.search(text)
        match = _CANONICAL.search(text)
        if not title or not match or _NOINDEX.search(text):
            continue
        if _slug_of(match.group(1)) != slug:
            continue
        name = html.unescape(title.group(1)).strip()
        if not name or name.lower().startswith("redirecting"):
            continue
        published = _PUBLISHED.search(text)
        groups.setdefault(name, []).append((published.group(1) if published else "9999", slug, path))
    live_titles = set()
    for slug in live & set(pages):
        title = _TITLE.search(pages[slug].read_text(encoding="utf-8"))
        if title:
            live_titles.add(html.unescape(title.group(1)).strip())
    for name, members in groups.items():
        if len(members) < 2 or name in live_titles:
            continue
        members.sort()
        keeper = members[0][1]
        url = f"{SITE}/articles/{keeper}.html"
        for _, slug, path in members[1:]:
            # Same headline is not proof of the same story (a Bradford City
            # preview and a Tranmere shoot-out report shared one): the text
            # must match too.
            if not _same_body(body(slug), body(keeper)):
                continue
            text = path.read_text(encoding="utf-8")
            path.write_text(_CANONICAL.sub(f'<link rel="canonical" href="{url}"', text, count=1), encoding="utf-8")
            stats["duplicate_titles_consolidated"] += 1
    return stats


if __name__ == "__main__":
    import json
    feed = json.loads((ROOT / "articles.json").read_text(encoding="utf-8"))
    print(repair(ROOT / "articles", ROOT / "_redirects", {row.get("slug") for row in feed}))
