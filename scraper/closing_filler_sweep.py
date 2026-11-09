"""Remove closing fluff from EVERY published article page (9 Nov 2026, editor).

"Rewrite every single article removing the filler fluff at the end." Stories
end on their last fact. This removes, from every page in articles/ and every
record in articles.json:

  * the appended comment invitation (<p data-rd-reader-ending="1">), and
  * from the last two story paragraphs only: comment invitations with the
    reader question that sets them up, moralising summary lines, unattributed
    "this incident raises concerns about ... / the importance of ..." lines,
    and sympathy or good wishes in the paper's own voice
    (reader_copy._keep_reporting decides, sentence by sentence).

Never touched: anything inside quotation marks, any sentence with a figure,
quotation or attribution, right-of-reply paragraphs, paragraphs carrying
links or other markup, sources, related links, background boxes, adverts.

Runs inside generate_pages.main, so every lane applies it and commits the
result (lanes already stage articles/). Idempotent: a clean page is not
rewritten, so after the first pass it writes nothing.

    python scraper/closing_filler_sweep.py           # apply
    python scraper/closing_filler_sweep.py --check   # count only, write nothing
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from reader_copy import (
    RIGHT_OF_REPLY_RE,
    _closing_spans,
    _keep_reporting,
    _text_before,
    plain,
    split_sentences,
    strip_closing_html,
)

ROOT = Path(__file__).resolve().parents[1]

# Same story region archive_quality.py reads: from article-copy up to the
# sources, comments, read-next, legal note or sidebar.
BODY = re.compile(
    r'(<div\b[^>]*class=["\']article-copy["\'][^>]*>)(.*?)'
    r'(?=<details\b[^>]*class=["\']article-sources|<section\b[^>]*class=["\']'
    r'(?:comments|read-next|editorial-legal|report-box)|<aside\b|$)',
    re.S,
)
ENGAGEMENT = re.compile(r'<p\b[^>]*data-rd-reader-ending=["\']1["\'][^>]*>.*?</p>', re.S)
# Story paragraphs are attribute-free <p>. Furniture paragraphs carry a class.
STORY_P = re.compile(r'<p>(.*?)</p>', re.S)
# Blocks whose paragraphs are not story copy.
FURNITURE = re.compile(
    r'<div\b[^>]*data-rd-background=["\']1["\'][^>]*>.*?</div>'
    r'|<(details|aside|figure|blockquote|template|script)\b.*?</\1>',
    re.S | re.I,
)


def clean_fragment(fragment: str) -> str:
    fragment = ENGAGEMENT.sub('', fragment)
    masked = [m.span() for m in FURNITURE.finditer(fragment)]

    def inside(pos: int) -> bool:
        return any(a <= pos < b for a, b in masked)

    spans = [m for m in STORY_P.finditer(fragment) if not inside(m.start())]
    window = _closing_spans(spans)
    closing = [m for m in spans if m.span() in window]
    # Edit from the end so earlier offsets stay valid.
    for match in reversed(closing):
        inner = match.group(1)
        if '<' in inner or RIGHT_OF_REPLY_RE.search(plain(inner)):
            continue
        sentences = split_sentences(html.unescape(inner))
        kept = _keep_reporting(sentences, _text_before(fragment, match.start()))
        if len(kept) == len(sentences):
            continue
        replacement = '<p>' + html.escape(' '.join(kept), quote=False) + '</p>' if kept else ''
        fragment = fragment[:match.start()] + replacement + fragment[match.end():]
    return fragment


def clean_page(page: str) -> str:
    match = BODY.search(page)
    if not match:
        return page
    fragment = match.group(2)
    # Removing a closing line exposes the paragraph before it as the new
    # ending, which may carry its own filler: repeat until the ending is
    # clean (bounded; each pass only ever removes text).
    cleaned = fragment
    for _ in range(4):
        again = clean_fragment(cleaned)
        if again == cleaned:
            break
        cleaned = again
    if cleaned == fragment:
        return page
    return page[:match.start(2)] + cleaned + page[match.end(2):]


def sweep(root: Path = ROOT, write: bool = True, pages_dir: Path | None = None,
          feed_path: Path | None = None) -> dict:
    report = {'pages_scanned': 0, 'pages_cleaned': 0, 'records_cleaned': 0, 'cleaned': []}
    pages_dir = pages_dir or root / 'articles'
    feed_path = feed_path or root / 'articles.json'
    for path in sorted(pages_dir.glob('*.html')):
        report['pages_scanned'] += 1
        page = path.read_text(encoding='utf-8')
        new = clean_page(page)
        if new != page:
            report['pages_cleaned'] += 1
            report['cleaned'].append(path.stem)
            if write:
                path.write_text(new, encoding='utf-8')
    try:
        feed = json.loads(feed_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        feed = None
    records = feed.get('articles') if isinstance(feed, dict) else feed
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict) or not record.get('content_html'):
                continue
            body = ENGAGEMENT.sub('', str(record['content_html']))
            body = strip_closing_html(body)
            if body != record['content_html']:
                record['content_html'] = body
                report['records_cleaned'] += 1
        if write and report['records_cleaned']:
            feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main() -> None:
    check = '--check' in sys.argv
    report = sweep(write=not check)
    print(
        f"Closing filler {'found' if check else 'removed'}: {report['pages_cleaned']} of "
        f"{report['pages_scanned']} pages, {report['records_cleaned']} feed records"
    )


if __name__ == '__main__':
    main()
