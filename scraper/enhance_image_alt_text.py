#!/usr/bin/env python3
"""Add descriptive alt text to generated news imagery at deployment time.

Rochdale Daily's article heroes and crawlable homepage cards historically used
empty alt attributes even when the image is editorially tied to a specific
story. Empty alt is appropriate for purely decorative imagery, but these images
are meaningful story content. This deployment-safe pass uses the visible story
headline as a conservative fallback, improving accessibility and image-search
context without inventing a visual description.

The rewrite is intentionally narrow and idempotent:
- only article hero images inside ``figure.article-hero-image``;
- only images inside generated ``article.news-card`` homepage cards;
- only when the existing alt attribute is empty.
Existing human-written alt text is never replaced.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLES_DIR = ROOT / "articles"

ARTICLE_H1_RE = re.compile(r"<h1[^>]*>(?P<title>.*?)</h1>", re.I | re.S)
HERO_FIGURE_RE = re.compile(
    r"(?P<figure><figure\b[^>]*class=\"[^\"]*\barticle-hero-image\b[^\"]*\"[^>]*>.*?</figure>)",
    re.I | re.S,
)
NEWS_CARD_RE = re.compile(
    r"(?P<card><article\b[^>]*class=\"[^\"]*\bnews-card\b[^\"]*\"[^>]*>.*?</article>)",
    re.I | re.S,
)
CARD_TITLE_RE = re.compile(r"<h3\b[^>]*class=\"[^\"]*\bcard-headline\b[^\"]*\"[^>]*>(?P<title>.*?)</h3>", re.I | re.S)
EMPTY_ALT_RE = re.compile(r'\balt\s*=\s*([\"\'])\s*\1', re.I)
TAG_RE = re.compile(r"<[^>]+>")


def visible_text(markup: str) -> str:
    text = TAG_RE.sub(" ", markup)
    return " ".join(html.unescape(text).split()).strip()


def escaped_alt(text: str) -> str:
    return html.escape(text, quote=True)


def replace_first_empty_alt(markup: str, title: str) -> str:
    if not title:
        return markup
    return EMPTY_ALT_RE.sub(f'alt="{escaped_alt(title)}"', markup, count=1)


def enhance_article_html(text: str) -> str:
    title_match = ARTICLE_H1_RE.search(text)
    if not title_match:
        return text
    title = visible_text(title_match.group("title"))
    if not title:
        return text

    def repl(match: re.Match[str]) -> str:
        figure = match.group("figure")
        return replace_first_empty_alt(figure, title)

    return HERO_FIGURE_RE.sub(repl, text, count=1)


def enhance_homepage_html(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        card = match.group("card")
        title_match = CARD_TITLE_RE.search(card)
        if not title_match:
            return card
        title = visible_text(title_match.group("title"))
        return replace_first_empty_alt(card, title)

    return NEWS_CARD_RE.sub(repl, text)


def update_file(path: Path, transform) -> bool:
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    updated = transform(original)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    homepage_changed = update_file(INDEX, enhance_homepage_html)
    article_changes = 0
    if ARTICLES_DIR.is_dir():
        for path in ARTICLES_DIR.glob("*.html"):
            if update_file(path, enhance_article_html):
                article_changes += 1
    print(
        "Image alt enhancement complete: "
        f"homepage={'updated' if homepage_changed else 'unchanged'}, "
        f"article pages updated={article_changes}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
