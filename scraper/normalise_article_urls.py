"""Align public article URLs with the extensionless URLs served by the live host.

Keep the .html files and every archive entry. Only public URL references change;
duplicate canonicals keep their chosen target and source publisher URLs are untouched.
This also runs at the final deployment boundary after all sitemap generators.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ABSOLUTE = re.compile(r'https://(?:www\.)?rochdaledaily\.co\.uk/articles/([a-z0-9-]+)\.html(?=[?#\s\"\'<>]|$)')
RELATIVE = re.compile(r'([\"\'](?:/|\.\./)?articles/[a-z0-9-]+)\.html(?=[?#\"\'])')


def normalise_text(text: str, article_slugs: set[str], article_page: bool = False) -> str:
    text = ABSOLUTE.sub(r'https://rochdaledaily.co.uk/articles/\1', text)
    text = RELATIVE.sub(r'\1', text)
    if article_page:
        def related(match: re.Match) -> str:
            return match[1] + match[2] if match[2] in article_slugs else match[0]
        text = re.sub(r'(href=[\"\'])([a-z0-9-]+)\.html(?=[?#\"\'])', related, text)
    return text


def normalise_snapshot(root: Path = ROOT) -> int:
    pages = list((root / 'articles').glob('*.html'))
    slugs = {p.stem for p in pages}
    public_pages = pages + list(root.glob('*.html'))
    for folder in ('news', 'wards'):
        public_pages.extend((root / folder).glob('*.html'))
    paths = public_pages + [root / name for name in (
        'sitemap.xml', 'news-sitemap.xml', 'image-sitemap.xml', 'rss.xml', 'archive-index.json'
    )]
    changed = 0
    for path in paths:
        if not path.is_file():
            continue
        before = path.read_text(encoding='utf-8')
        after = normalise_text(before, slugs, path.parent == root / 'articles')
        if after != before:
            path.write_text(after, encoding='utf-8')
            changed += 1
    return changed


if __name__ == '__main__':
    print(f'Public article URL alignment: {normalise_snapshot()} file(s) updated.')
