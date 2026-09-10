#!/usr/bin/env python3
"""Make the Rochdale Daily design contract explicit on every public HTML page.

The site has accumulated several generations of static HTML. Their content and
page-specific layouts are still useful, but no public page may choose its own
publication identity. This normaliser is run after page generation and stamps
all reader-facing HTML with the canonical token + editorial layers.

It is intentionally idempotent: running it repeatedly makes no further edits.
Internal newsroom/moderation tools are excluded because they are applications,
not reader-facing publication pages.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_ROOT_FILES = {
    "404.html",
    "about.html",
    "accessibility.html",
    "archive.html",
    "category.html",
    "contact.html",
    "corrections-and-complaints.html",
    "corrections-log.html",
    "editor.html",
    "editorial-standards.html",
    "feel-good-live.html",
    "food-banks.html",
    "heywood.html",
    "index.html",
    "milnrow.html",
    "post.html",
    "privacy.html",
    "residents-corner.html",
    "rochdale.html",
    "search.html",
    "status.html",
    "terms.html",
}

PUBLIC_DIRS = ("articles", "news", "wards", "showbiz")

# These two rebuilt routes have their own token-driven first-class stylesheet.
# Forcing the much broader editorial-theme.css over it would create an
# unnecessary second cascade. Their dedicated stylesheet is part of the same
# design contract and is validated separately.
DEDICATED_ROUTE_FILES = {"category.html", "post.html"}

TOKEN_HREF = "/assets/css/rd-tokens.css"
EDITORIAL_HREF = "/assets/css/editorial-theme.css"
ROUTE_HREF = "/assets/css/legacy-routing-pages.css"
TOKEN_LINK = f'<link rel="stylesheet" href="{TOKEN_HREF}" data-rd-universal="tokens">'
EDITORIAL_LINK = (
    f'<link rel="stylesheet" href="{EDITORIAL_HREF}" '
    'data-rd-universal="editorial">'
)
THEME_COLOUR = "#0d2137"

HTML_TAG_RE = re.compile(r"<html(?P<attrs>[^>]*)>", re.I)
THEME_META_RE = re.compile(
    r'<meta\s+name=["\']theme-color["\']\s+content=["\'][^"\']*["\']\s*/?>',
    re.I,
)


def public_pages(root: Path = ROOT) -> list[Path]:
    pages: set[Path] = set()
    for filename in PUBLIC_ROOT_FILES:
        path = root / filename
        if path.exists():
            pages.add(path)
    for dirname in PUBLIC_DIRS:
        folder = root / dirname
        if folder.exists():
            pages.update(path for path in folder.rglob("*.html") if path.is_file())
    return sorted(pages)


def _stamp_html_tag(text: str) -> str:
    match = HTML_TAG_RE.search(text)
    if not match:
        return text
    attrs = match.group("attrs")
    if "data-rd-theme=" in attrs:
        return text
    replacement = f'<html{attrs} data-rd-theme="newspaper">'
    return text[: match.start()] + replacement + text[match.end() :]


def _normalise_theme_colour(text: str) -> str:
    if not THEME_META_RE.search(text):
        return text
    return THEME_META_RE.sub(
        f'<meta name="theme-color" content="{THEME_COLOUR}">', text, count=1
    )


def _has_stylesheet(text: str, href: str) -> bool:
    return href in text


def normalise_text(path: Path, text: str) -> str:
    if "</head>" not in text.lower():
        return text

    result = _stamp_html_tag(text)
    result = _normalise_theme_colour(result)

    # Rebuilt route pages already consume the canonical tokens through their
    # dedicated stylesheet. Merely stamp the HTML contract; do not add a second
    # broad component layer over them.
    if path.name in DEDICATED_ROUTE_FILES and _has_stylesheet(result, ROUTE_HREF):
        if not _has_stylesheet(result, TOKEN_HREF):
            result = result.replace("</head>", f"  {TOKEN_LINK}\n</head>", 1)
        return result

    links: list[str] = []
    if not _has_stylesheet(result, TOKEN_HREF):
        links.append(TOKEN_LINK)
    if not _has_stylesheet(result, EDITORIAL_HREF):
        links.append(EDITORIAL_LINK)

    if links:
        insertion = "  <!-- Universal Rochdale Daily newspaper theme -->\n  " + "\n  ".join(links) + "\n"
        result = result.replace("</head>", insertion + "</head>", 1)
    return result


def normalise(root: Path = ROOT, *, check: bool = False) -> tuple[int, list[str]]:
    changed: list[str] = []
    for path in public_pages(root):
        original = path.read_text(encoding="utf-8")
        updated = normalise_text(path, original)
        if updated == original:
            continue
        changed.append(path.relative_to(root).as_posix())
        if not check:
            path.write_text(updated, encoding="utf-8")
    return len(changed), changed


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for path in public_pages(root):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(root).as_posix()
        if 'data-rd-theme="newspaper"' not in text:
            errors.append(f"{rel}: missing data-rd-theme newspaper stamp")
        if path.name in DEDICATED_ROUTE_FILES and ROUTE_HREF in text:
            if TOKEN_HREF not in text:
                errors.append(f"{rel}: dedicated route is missing rd-tokens.css")
            continue
        if TOKEN_HREF not in text:
            errors.append(f"{rel}: missing direct rd-tokens.css link")
        if EDITORIAL_HREF not in text:
            errors.append(f"{rel}: missing editorial-theme.css link")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if any page needs normalising")
    args = parser.parse_args()

    if args.check:
        changed_count, changed = normalise(check=True)
        errors = validate()
        if changed_count or errors:
            if changed:
                print("Public theme normalisation required:")
                for path in changed[:80]:
                    print(f"  {path}")
                if len(changed) > 80:
                    print(f"  ... and {len(changed) - 80} more")
            for error in errors[:80]:
                print(f"ERROR: {error}")
            return 1
        print(f"Universal theme contract passed for {len(public_pages())} public pages.")
        return 0

    count, changed = normalise()
    print(f"Normalised universal theme on {count} public pages.")
    for path in changed[:30]:
        print(f"  {path}")
    if len(changed) > 30:
        print(f"  ... and {len(changed) - 30} more")
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
