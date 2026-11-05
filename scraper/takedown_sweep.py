"""Final sweep for editorial takedowns: no public page may still list a removed story.

remove_story.py deletes the article page and rebuilds the generators it knows
about, but headlines and excerpts of a story are also baked into listing pages
built by other lanes (section hubs, topic hubs, month archives, ward pages,
"more from" lists inside other articles, the image sitemap). On 5 Nov 2026 a
takedown left the Little Oaks story listed on nine such pages.

sweep() removes, from every public .html/.xml file, the smallest element that
carries a link to a removed slug: a card (<article>), a list item (<li>), a
sitemap <url> entry, or a JSON-LD ListItem. verify() reports anything still
left, so the workflow can fail loudly instead of a partial takedown passing
as complete.

Usage:
  python scraper/takedown_sweep.py --slugs "a,b"            # sweep, then verify
  python scraper/takedown_sweep.py --verify --slugs "a,b"   # verify only
  (no --slugs: every slug in story_blocklist.json)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ENCLOSING_TAGS = ("article", "li", "url")
SKIP_DIRS = {".git", ".github", "scraper", "reports", "node_modules", "_preview"}


def public_files(root: Path) -> list[Path]:
    files = []
    for pattern in ("*.html", "*.xml"):
        for path in root.rglob(pattern):
            rel = path.relative_to(root)
            if rel.parts and rel.parts[0] in SKIP_DIRS:
                continue
            files.append(path)
    return sorted(files)


def is_own_page(rel: Path, slug: str) -> bool:
    """The story's own page (articles/<slug>.html or articles/<slug>/index.html).

    Deleting or redirecting that page is remove_story.py's job; the sweep only
    removes listings of the story from other pages, never cuts into a page's
    own body.
    """
    parts = rel.parts
    return len(parts) >= 2 and parts[0] == "articles" and (
        parts[1] in (slug, f"{slug}.html")
    )


def _link_pattern(slug: str) -> re.Pattern[str]:
    # The slug as a URL path segment: /articles/<slug>, optionally .html,
    # never a prefix of a longer slug.
    return re.compile(r"/articles/" + re.escape(slug) + r'(?:\.html)?(?=["\'<?#\s])')


def _list_item_pattern(slug: str) -> re.Pattern[str]:
    return re.compile(
        r'\{"@type":\s*"ListItem",\s*"position":\s*\d+,\s*"url":\s*"[^"]*/articles/'
        + re.escape(slug)
        + r'(?:\.html)?",\s*"name":\s*"(?:[^"\\]|\\.)*"\}'
    )


def _enclosing(text: str, index: int) -> tuple[int, int] | None:
    """Smallest balanced <article>/<li>/<url> element containing index."""
    best = None
    for tag in ENCLOSING_TAGS:
        opener = re.compile(r"<" + tag + r"(?=[\s>])")
        closer = f"</{tag}>"
        starts = [m.start() for m in opener.finditer(text, 0, index)]
        for start in reversed(starts):
            segment = text[start:index]
            if len(opener.findall(segment)) - 1 != segment.count(closer):
                continue  # this element closed before index
            end = text.find(closer, index)
            if end == -1:
                break
            span = (start, end + len(closer))
            if best is None or span[1] - span[0] < best[1] - best[0]:
                best = span
            break
    return best


def _drop_list_items(text: str, slug: str) -> tuple[str, int]:
    count = 0
    pattern = _list_item_pattern(slug)
    while True:
        match = pattern.search(text)
        if not match:
            return text, count
        start, end = match.span()
        after = re.match(r"\s*,\s*", text[end:])
        if after:
            end += after.end()
        else:
            before = re.search(r",\s*$", text[:start])
            if before:
                start = before.start()
        text = text[:start] + text[end:]
        count += 1


def sweep_text(text: str, slugs: list[str]) -> tuple[str, int, list[str]]:
    removed = 0
    unresolved: list[str] = []
    for slug in slugs:
        if slug not in text:
            continue
        text, n = _drop_list_items(text, slug)
        removed += n
        link = _link_pattern(slug)
        while True:
            match = link.search(text)
            if not match:
                break
            span = _enclosing(text, match.start())
            if span is None:
                unresolved.append(slug)
                break
            text = text[: span[0]] + text[span[1]:]
            removed += 1
    return text, removed, unresolved


def renumber_list_items(text: str) -> str:
    """Keep JSON-LD ItemList positions 1..n after an entry is cut."""
    def fix(block: re.Match[str]) -> str:
        body = block.group(2)
        try:
            data = json.loads(body)
        except ValueError:
            return block.group(0)
        changed = False
        for node in data if isinstance(data, list) else [data]:
            items = node.get("itemListElement") if isinstance(node, dict) else None
            if isinstance(items, list):
                for position, item in enumerate(items, 1):
                    if isinstance(item, dict) and item.get("position") != position:
                        item["position"] = position
                        changed = True
                if "numberOfItems" in node and node["numberOfItems"] != len(items):
                    node["numberOfItems"] = len(items)
                    changed = True
        if not changed:
            return block.group(0)
        return block.group(1) + json.dumps(data, ensure_ascii=False) + block.group(3)

    return re.sub(
        r'(<script type="application/ld\+json">)(.*?)(</script>)', fix, text, flags=re.S
    )


def sweep(root: Path, slugs: list[str]) -> dict[str, int]:
    changed: dict[str, int] = {}
    slugs = [slug for slug in slugs if slug]
    if not slugs:
        return changed
    for path in public_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(root)
        targets = [slug for slug in slugs if slug in text and not is_own_page(rel, slug)]
        if not targets:
            continue
        new, removed, _ = sweep_text(text, targets)
        if removed:
            path.write_text(renumber_list_items(new), encoding="utf-8")
            changed[path.relative_to(root).as_posix()] = removed
    return changed


def verify(root: Path, slugs: list[str]) -> list[str]:
    leftovers = []
    patterns = [(slug, _link_pattern(slug)) for slug in slugs if slug]
    for path in public_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(root)
        for slug, pattern in patterns:
            if is_own_page(rel, slug):
                continue
            if slug in text and pattern.search(text):
                leftovers.append(f"{path.relative_to(root).as_posix()}: {slug}")
    return leftovers


def blocklisted_slugs(root: Path) -> list[str]:
    try:
        data = json.loads((root / "story_blocklist.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(slug).lower() for slug in data.get("slugs", []) if slug]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slugs", default="")
    parser.add_argument("--verify", action="store_true", help="report only, change nothing")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root)
    slugs = [s.strip().lower() for s in args.slugs.split(",") if s.strip()] or blocklisted_slugs(root)

    if not args.verify:
        for rel, count in sweep(root, slugs).items():
            print(f"Swept {count} listing(s) from {rel}")
    leftovers = verify(root, slugs)
    for line in leftovers:
        print(f"STILL LISTED: {line}")
    if leftovers:
        print(f"ERROR: {len(leftovers)} public file(s) still link to a removed story.")
        return 1
    print(f"Takedown sweep clean: no public page links to {len(slugs)} removed slug(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
