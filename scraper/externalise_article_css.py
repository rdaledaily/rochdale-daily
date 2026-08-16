#!/usr/bin/env python3
"""Replace duplicated article-page site CSS with the cacheable shared stylesheet.

Generated article pages historically embedded the complete contents of
``assets/css/site.css`` inside every HTML document. That makes each article
heavier and forces repeat readers to download the same CSS again on every page.

This deployment-safe pass only replaces an inline ``<style>`` block when its
contents exactly match the current shared stylesheet. Older/custom inline styles
are left untouched rather than guessed at. The repository is not mutated by the
Pages workflow; this optimises the uploaded snapshot only.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_DIR = ROOT / "articles"
CSS_PATH = ROOT / "assets/css/site.css"
STYLESHEET_LINK = '<link rel="stylesheet" href="/assets/css/site.css">'


def externalise_page_css(text: str, css: str) -> tuple[str, bool]:
    """Return page HTML with one exact shared-CSS block replaced by a link."""
    if STYLESHEET_LINK in text:
        return text, False
    inline = f"<style>{css}</style>"
    if inline not in text:
        return text, False
    return text.replace(inline, STYLESHEET_LINK, 1), True


def externalise_directory(articles_dir: Path = ARTICLES_DIR, css_path: Path = CSS_PATH) -> tuple[int, int]:
    if not css_path.is_file():
        raise SystemExit(f"Shared stylesheet not found: {css_path}")
    if not articles_dir.is_dir():
        raise SystemExit(f"Article directory not found: {articles_dir}")

    css = css_path.read_text(encoding="utf-8")
    changed = 0
    scanned = 0
    for path in sorted(articles_dir.glob("*.html")):
        scanned += 1
        original = path.read_text(encoding="utf-8")
        updated, did_change = externalise_page_css(original, css)
        if did_change:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    return changed, scanned


def main() -> int:
    changed, scanned = externalise_directory()
    print(f"Externalised shared article CSS on {changed} of {scanned} HTML pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
