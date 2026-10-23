"""One place that knows what an in-article advert slot looks like.

The slot is page furniture, never part of a story. It is added when a page is
rendered and must never be stored in an article record.

Why this module exists (23 Oct 2026): generate_pages.insert_incontent_ad()
added a slot on every render without checking for one already there, and
archive_quality.py read story bodies back out of the RENDERED page -- slot
included -- and wrote them into articles.json. Each lap of that loop added a
slot. 105 stories reached 13 stacked slots, and ads.js fills and counts every
slot, so readers saw the same advert up to 13 times in a row and impression
counts were inflated by the same factor.

Rule enforced here: strip every slot first, then insert exactly one.
"""

from __future__ import annotations

import re

AD_SLOT_HTML = (
    '<div class="ad-slot ad-slot-incontent" data-ad-slot="article-incontent" '
    'role="presentation" aria-hidden="true"></div>'
)

# Matches an empty in-content slot whatever its attribute order, plus any
# whitespace after it. ads.js fills slots in the browser only, so a stored or
# rendered slot is always empty markup.
_SLOT = re.compile(
    r'<div\b[^>]*\bad-slot-incontent\b[^>]*>\s*</div>\s*',
    re.I,
)


def strip_ad_slots(content_html: str) -> str:
    """Remove every in-content advert slot from a story body."""
    return _SLOT.sub('', str(content_html or ''))


def count_ad_slots(content_html: str) -> int:
    return len(_SLOT.findall(str(content_html or '')))


def insert_incontent_ad(content_html: str) -> str:
    """Place exactly one slot after the third paragraph (or after the last
    paragraph of a shorter story). Idempotent: running it on its own output
    returns the same HTML."""
    clean = strip_ad_slots(content_html)
    # Positions just after each closing </p>. The old split/insert/join
    # version emitted a stray "</p>" after the slot on every render.
    ends = [m.end() for m in re.finditer(r'</p>', clean, re.I)]
    if not ends:
        return clean
    at = ends[min(3, len(ends)) - 1]
    return clean[:at] + AD_SLOT_HTML + clean[at:]
