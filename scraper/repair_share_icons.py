#!/usr/bin/env python3
"""Rebuild every published article's share row from the official icons.

Why this exists
---------------
Measured 7 Nov 2026: content_hygiene.py cleaned whole HTML files with a
"no space before punctuation" rule, which removed the space in '.401 0 .955'
inside the Facebook icon's path data (and Bluesky's), so 1,448 pages showed a
sliver for Facebook and a triangle for Bluesky. A further 469 older pages
carried an earlier hand-drawn set (copy, Facebook, WhatsApp only).
content_hygiene now cleans reader text only; this rebuilds the rows.

Each row is replaced with generate_pages.share_icons_markup(): the official
brand marks from Simple Icons (CC0) for Facebook, WhatsApp, X and Bluesky, and
plain copy-link and email glyphs. An older page whose script handles only
copy, Facebook and WhatsApp also gets a small handler for X, Bluesky and email.
Idempotent: a page already carrying the current row is left as it is.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_pages import share_icons_markup  # noqa: E402

SHARE_ROW_RE = re.compile(r'<div class="article-share"[^>]*>.*?</div>', re.S)
EXTRA_HANDLER_ID = "rd-share-extra"
EXTRA_HANDLER = (
    f'<script id="{EXTRA_HANDLER_ID}">document.addEventListener("click",function(e){{'
    'var t=e.target.closest("[data-share]");if(!t)return;'
    'var a=t.dataset.share,u=t.dataset.url,ti=t.dataset.title||document.title;'
    'if(a==="x")window.open("https://twitter.com/intent/tweet?text="+encodeURIComponent(ti)+"&url="+encodeURIComponent(u),"_blank","noopener,noreferrer");'
    'if(a==="bluesky")window.open("https://bsky.app/intent/compose?text="+encodeURIComponent(ti+" "+u),"_blank","noopener,noreferrer");'
    'if(a==="email")window.location.href="mailto:?subject="+encodeURIComponent(ti)+"&body="+encodeURIComponent(u);'
    '});</script>'
)


def repair(page: str) -> str:
    row = SHARE_ROW_RE.search(page)
    if not row:
        return page
    url_match = re.search(r'data-url="([^"]+)"', row.group(0))
    if not url_match:
        return page
    title_match = re.search(r'data-title="([^"]*)"', row.group(0)) or re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    url = html.unescape(url_match.group(1))
    title = html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))) if title_match else ""
    fresh = share_icons_markup(url, title)
    out = page[:row.start()] + fresh + page[row.end():]
    handles_all = all(f'action === "{a}"' in out for a in ("x", "bluesky", "email"))
    if not handles_all and EXTRA_HANDLER_ID not in out and "</body>" in out:
        out = out.replace("</body>", EXTRA_HANDLER + "</body>", 1)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles-dir", type=Path, default=Path("articles"))
    parser.add_argument("--check", action="store_true", help="report pages that need repair; change nothing")
    args = parser.parse_args(argv)
    changed = 0
    for path in sorted(args.articles_dir.glob("*.html")):
        page = path.read_text(encoding="utf-8")
        fixed = repair(page)
        if fixed != page:
            changed += 1
            if not args.check:
                path.write_text(fixed, encoding="utf-8")
    print(f"{'would repair' if args.check else 'repaired'} share rows on {changed} page(s)")
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
