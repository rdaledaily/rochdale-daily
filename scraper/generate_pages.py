"""Generate static, crawlable pages for Rochdale Daily articles.

This runs after ``scraper.py`` on each scheduled run. It first rebuilds the
homepage and derived archive feeds through ``frontpage_pipeline.py``, then
reads the permanent ``articles.json`` archive and writes one HTML file per
published article to ``articles/<slug>.html``.

Live article pages are regenerated so corrections and meaningful updates are
visible. Older pages that are no longer represented in legacy feed data are
retained to preserve published URLs. Explicit editorial takedowns are the
exception: blocklisted pages are deleted and omitted from the sitemap.
"""
from __future__ import annotations
from source_presentation import generic_sources_markup, sanitise_article
from story_blocklist import is_blocked_article, load_blocklist
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
SITE_BASE_URL = os.getenv('SITE_BASE_URL', 'https://rochdaledaily.co.uk').rstrip('/')
ARTICLES_JSON = Path(os.getenv('ARTICLES_JSON', 'articles.json'))
OUTPUT_DIR = Path(os.getenv('ARTICLE_PAGES_DIR', 'articles'))
SITEMAP_PATH = Path(os.getenv('SITEMAP_PATH', 'sitemap.xml'))
CSS_SOURCE_PATH = Path(os.getenv('CSS_SOURCE_PATH', 'assets/css/site.css'))
BLOCKLIST_JSON = Path(os.getenv('STORY_BLOCKLIST_JSON', 'story_blocklist.json'))

LEGACY_COMMENT_MARKUP = [
    re.compile(r'<section class="comments-section".*?</section>\s*', re.S),
    re.compile(r'<div id="fb-root"></div>\s*', re.S),
    re.compile(r'<script[^>]*src="https://connect\.facebook\.net/[^"]*"[^>]*>\s*</script>\s*', re.S),
    re.compile(r'if \(window\.FB && window\.FB\.XFBML\) \{[^}]*\}\s*', re.S),
    # Dead CSS rules for the retired comments block, embedded in each
    # archived page's inline stylesheet.
    re.compile(r'\.comments-section[^{]*\{[^}]*\}\s*'),
    re.compile(r'\.comments-fallback[^{]*\{[^}]*\}\s*'),
    re.compile(r'\.comment-signup-box[^{]*\{[^}]*\}\s*'),
    re.compile(r'\.comment-eyebrow[^{]*\{[^}]*\}\s*'),
    re.compile(r'\.comment-rules[^{]*\{[^}]*\}\s*'),
]


def scrub_legacy_comment_markup(pages_dir: Path, skip: set[str]) -> int:
    """Strip the retired Facebook comments block from archived pages.

    Meta discontinued the Comments plugin on 10 February 2026; it renders
    as an invisible 0x0 element, leaving an empty "Have your say" box on
    every page that still embeds it. Live pages are fully regenerated each
    run, but archived pages (stories no longer in articles.json) are never
    rewritten, so their embedded markup is scrubbed in place here instead.
    """
    scrubbed = 0
    if not pages_dir.exists():
        return scrubbed
    for path in pages_dir.glob('*.html'):
        if path.stem in skip:
            continue
        original = path.read_text(encoding='utf-8')
        cleaned = original
        for pattern in LEGACY_COMMENT_MARKUP:
            cleaned = pattern.sub('', cleaned)
        if cleaned != original:
            path.write_text(cleaned, encoding='utf-8')
            scrubbed += 1
    return scrubbed


# Masthead modernisation for archived pages. Live pages are fully
# regenerated each run, but archived pages (stories no longer in
# articles.json) keep whatever masthead they were generated with: a bare
# text wordmark and the retired "Send us a story" button. Rewrite them in
# place to the current masthead -- the logo image with a hidden text
# fallback -- matching index.html and the live-page template above.
ARCHIVED_MASTHEAD_OLD = (
    '<a class="brand" href="../index.html" aria-label="Rochdale Daily home">\n'
    '        <span class="brand-text-fallback">ROCHDALE DAILY</span>\n'
    '      </a>'
)
ARCHIVED_MASTHEAD_NEW = (
    '<a class="brand" href="../index.html" aria-label="Rochdale Daily home">\n'
    '        <img class="brand-logo" src="/assets/img/logo.png" width="1292" height="706" '
    'alt="Rochdale Daily — independent local news" loading="eager" decoding="sync" '
    'onerror="this.hidden=true;document.getElementById(\'brand-text-fallback\').hidden=false">'
    '<span id="brand-text-fallback" class="brand-text-fallback" hidden>ROCHDALE DAILY</span>\n'
    '      </a>'
)
SEND_US_A_STORY_MARKUP = re.compile(
    r'\s*<a class="header-button solid" href="mailto:news@rochdaledaily\.co\.uk[^"]*">Send us a story</a>'
)


def modernise_archived_masthead(pages_dir: Path, skip: set[str]) -> int:
    """Bring archived pages' mastheads in line with the current template.

    Applies two rewrites to pages absent from the current archive: swap the
    text-only wordmark for the logo image with hidden fallback, and remove
    the retired "Send us a story" button. Both are exact/no-op safe, so
    already-modernised pages are left untouched on later runs.
    """
    updated = 0
    if not pages_dir.exists():
        return updated
    for path in pages_dir.glob('*.html'):
        if path.stem in skip:
            continue
        original = path.read_text(encoding='utf-8')
        cleaned = original.replace(ARCHIVED_MASTHEAD_OLD, ARCHIVED_MASTHEAD_NEW)
        cleaned = SEND_US_A_STORY_MARKUP.sub('', cleaned)
        if cleaned != original:
            path.write_text(cleaned, encoding='utf-8')
            updated += 1
    return updated


def load_site_css() -> str:
    if CSS_SOURCE_PATH.exists():
        return CSS_SOURCE_PATH.read_text(encoding='utf-8')
    print(f'WARNING: {CSS_SOURCE_PATH} not found; generated pages will be unstyled.')
    return ''
SITE_CSS = load_site_css()
SOURCE_DENY_DOMAINS = {'rochdaletimes.co.uk', 'rochdaleonline.co.uk', 'pressreader.com', 'rochdaleobserver.co.uk'}
SOURCE_DENY_NAMES = {'rochdale times', 'rochdale times paper', 'rochdale online', 'rochdale observer', 'pressreader'}
CATEGORY_LABELS = {'crime': 'Crime', 'traffic': 'Traffic', 'transport': 'Transport', 'politics': 'Politics', 'education': 'Education', 'sport': 'Sport', 'events': 'Events', 'business': 'Business', 'community': 'Community', 'health': 'Health', 'environment': 'Environment', 'news': 'News'}

def parse_iso(value: object) -> datetime:
    """Parse a pipeline timestamp, returning an aware minimum on failure."""
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def first_published_at(article: dict[str, Any]) -> str:
    """Return the permanent original publication timestamp."""
    return str(
        article.get("first_published_at")
        or article.get("published_at")
        or article.get("scraped_at")
        or ""
    )


def last_modified_at(article: dict[str, Any]) -> str:
    """Return the most recent meaningful article modification timestamp."""
    return str(article.get("last_updated_at") or first_published_at(article))


def explicit_blocked_slugs(path: Path = BLOCKLIST_JSON) -> set[str]:
    """Extract explicit slug/id takedowns from the JSON blocklist.

    The project has used more than one blocklist schema over time, so this
    walks nested dictionaries and lists and recognises common slug/id fields
    without treating keyword rules as page names.
    """
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()

    blocked: set[str] = set()
    slug_keys = {"slug", "story_slug", "article_slug", "id", "story_id", "article_id"}
    list_keys = {"slugs", "blocked_slugs", "story_slugs", "ids", "blocked_ids"}

    def visit(value: Any, parent_key: str = "") -> None:
        key = parent_key.lower()
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                child_key_lower = str(child_key).lower()
                if child_key_lower in slug_keys and isinstance(child_value, (str, int)):
                    text = str(child_value).strip()
                    if text:
                        blocked.add(text)
                else:
                    visit(child_value, child_key_lower)
        elif isinstance(value, list):
            if key in list_keys:
                for item in value:
                    if isinstance(item, (str, int)) and str(item).strip():
                        blocked.add(str(item).strip())
                    else:
                        visit(item, key)
            else:
                for item in value:
                    visit(item, key)

    visit(payload)
    return blocked


def esc(value: Any) -> str:
    return html.escape(str(value or ''), quote=True)

def source_is_denied(source_name: str, source_url: str) -> bool:
    name = str(source_name or '').strip().lower()
    domain = re.sub('^www\\.', '', (re.findall('://([^/]+)', str(source_url or '')) or [''])[0]).lower()
    return domain in SOURCE_DENY_DOMAINS or any((denied in name for denied in SOURCE_DENY_NAMES))

def absolute_url(path_or_url: str) -> str:
    value = str(path_or_url or '').strip()
    if not value:
        # No image. Previously returned assets/img/stock_news.jpg, which was part
        # of the retired category artwork and no longer exists. Every published
        # article gets a composed story card, so this is only reached by records
        # that have not been through ensure_article_images yet; an empty value
        # is better than a URL that 404s in a social preview.
        return ''
    if value.startswith('http://') or value.startswith('https://'):
        return value
    return f"{SITE_BASE_URL}/{value.lstrip('/')}"

def meta_description(article: dict[str, Any]) -> str:
    text = str(article.get('excerpt') or article.get('summary') or '').strip()
    text = re.sub('\\s+', ' ', text)
    if len(text) > 155:
        text = text[:152].rsplit(' ', 1)[0] + '...'
    return text

def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(str(category or 'news').lower(), 'News')

def insert_incontent_ad(content_html: str) -> str:
    """Insert the ad slot after the third paragraph, or at the end for
    short articles, matching the same placement used in the homepage
    modal view."""
    parts = content_html.split('</p>')
    if len(parts) <= 1:
        return content_html
    ad_slot = '<div class="ad-slot ad-slot-incontent" data-ad-slot="article-incontent" role="presentation" aria-hidden="true"></div>'
    break_index = min(3, len(parts) - 1)
    parts.insert(break_index, ad_slot)
    rebuilt = '</p>'.join(parts)
    return rebuilt

def report_box_markup() -> str:
    return '<section class="report-box" style="margin-top:28px">\n        <h3>Report what you know</h3>\n        <p>This article is marked as a police matter. Send information directly through an official reporting channel.</p>\n        <div class="report-actions">\n          <a class="report-action" href="https://crimestoppers-uk.org/give-information/forms/give-information-anonymously" target="_blank" rel="noopener"><span>Crimestoppers &mdash; anonymous</span><span>0800 555 111</span></a>\n          <a class="report-action" href="https://www.gmp.police.uk/ro/report/" target="_blank" rel="noopener"><span>Greater Manchester Police online report</span><span>Open</span></a>\n          <a class="report-action" href="tel:999"><span>Emergency, immediate danger or crime in progress</span><span>999</span></a>\n        </div>\n        <p class="report-note">Do not send evidence or urgent reports to Rochdale Daily instead of the police.</p>\n      </section>'

def related_stories_markup(article: dict[str, Any], all_articles: list[dict[str, Any]]) -> str:
    category = str(article.get('category') or 'news').lower()
    slug = article.get('slug')
    related = [a for a in all_articles if a.get('slug') != slug and str(a.get('category') or 'news').lower() == category]
    related.sort(
        key=lambda item: parse_iso(first_published_at(item)),
        reverse=True,
    )
    related = related[:3]
    if not related:
        return ''
    items = []
    for item in related:
        title = esc(item.get('title') or 'Local news update')
        item_slug = esc(item.get('slug') or item.get('id') or '')
        image = esc(absolute_url(item.get('image_url') or ''))
        items.append(f'<a class="related-story" href="{item_slug}.html"><img src="{image}" alt="" loading="lazy"><span class="related-title">{title}</span></a>')
    return f'<div class="sidebar-box"><h3>More in {esc(category_label(category))}</h3>' + ''.join(items) + '</div>'


def visible_word_count(article: dict[str, Any]) -> int:
    body = re.sub(r"<[^>]+>", " ", str(article.get("content_html") or ""))
    body = html.unescape(body)
    return len(re.findall(r"\b[\w’'-]+\b", body))


def seo_keywords(article: dict[str, Any]) -> str:
    values = [
        str(article.get("area") or "Rochdale").replace("_", " ").title(),
        category_label(str(article.get("category") or "news")),
        "Rochdale",
        "local news",
    ]
    return ", ".join(dict.fromkeys(value for value in values if value))


def share_icons_markup(canonical_url: str, title: str) -> str:
    """Share buttons.

    The brand marks are the official paths from Simple Icons
    (https://simpleicons.org), released under CC0 1.0, so they are the real
    logos rather than approximations. The trademarks remain the property of
    their owners; using a brand mark on a share button to indicate where the
    link goes is the use those brands publish share endpoints for.

    Each is drawn at the brand's own 24x24 viewBox and inherits currentColor,
    so a button picks up its brand colour from CSS on hover and stays neutral
    otherwise. Copy-link has no brand and keeps a plain glyph.
    """
    copy_icon = (
        '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"'
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="9" y="9" width="12" height="12" rx="2"/>'
        '<path d="M6 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"/></svg>'
    )
    facebook_icon = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647Z"/></svg>'
    whatsapp_icon = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z"/></svg>'
    x_icon = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z"/></svg>'
    bluesky_icon = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M5.202 2.857C7.954 4.922 10.913 9.11 12 11.358c1.087-2.247 4.046-6.436 6.798-8.501C20.783 1.366 24 .213 24 3.883c0 .732-.42 6.156-.667 7.037-.856 3.061-3.978 3.842-6.755 3.37 4.854.826 6.089 3.562 3.422 6.299-5.065 5.196-7.28-1.304-7.847-2.97-.104-.305-.152-.448-.153-.327 0-.121-.05.022-.153.327-.568 1.666-2.782 8.166-7.847 2.97-2.667-2.737-1.432-5.473 3.422-6.3-2.777.473-5.899-.308-6.755-3.369C.42 10.04 0 4.615 0 3.883c0-3.67 3.217-2.517 5.202-1.026"/></svg>'
    email_icon = (
        '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"'
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m2 7 10 6 10-6"/></svg>'
    )

    url = esc(canonical_url)
    headline = esc(title)
    return (
        '<div class="article-share" aria-label="Share this article">'
        f'<button class="share-icon-button brand-copy" type="button" data-share="copy" data-url="{url}" aria-label="Copy article link">{copy_icon}<span class="visually-hidden">Copy link</span></button>'
        f'<button class="share-icon-button brand-facebook" type="button" data-share="facebook" data-url="{url}" aria-label="Share on Facebook">{facebook_icon}<span class="visually-hidden">Facebook</span></button>'
        f'<button class="share-icon-button brand-whatsapp" type="button" data-share="whatsapp" data-url="{url}" data-title="{headline}" aria-label="Share on WhatsApp">{whatsapp_icon}<span class="visually-hidden">WhatsApp</span></button>'
        f'<button class="share-icon-button brand-x" type="button" data-share="x" data-url="{url}" data-title="{headline}" aria-label="Share on X">{x_icon}<span class="visually-hidden">X</span></button>'
        f'<button class="share-icon-button brand-bluesky" type="button" data-share="bluesky" data-url="{url}" data-title="{headline}" aria-label="Share on Bluesky">{bluesky_icon}<span class="visually-hidden">Bluesky</span></button>'
        f'<button class="share-icon-button brand-email" type="button" data-share="email" data-url="{url}" data-title="{headline}" aria-label="Share by email">{email_icon}<span class="visually-hidden">Email</span></button>'
        '</div>'
    )


def json_ld(article: dict[str, Any], canonical_url: str, image_url: str) -> str:
    published = article.get("first_published_at") or article.get("published_at") or article.get("scraped_at") or ""
    modified = article.get("last_updated_at") or article.get("scraped_at") or published
    area = str(article.get("area") or "rochdale").replace("_", " ").title()
    category = str(article.get("category") or "news").lower()
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "NewsArticle",
                "@id": canonical_url + "#article",
                "headline": str(article.get("title") or "")[:110],
                "description": meta_description(article),
                "image": [image_url],
                "datePublished": published,
                "dateModified": modified,
                "inLanguage": "en-GB",
                "isAccessibleForFree": True,
                "articleSection": category_label(category),
                "wordCount": visible_word_count(article),
                "keywords": seo_keywords(article),
                "author": {
                    "@type": "Organization",
                    "name": "Rochdale Daily Newsdesk",
                    "url": f"{SITE_BASE_URL}/about.html",
                },
                "publisher": {
                    "@type": "NewsMediaOrganization",
                    "name": "Rochdale Daily",
                    "url": SITE_BASE_URL,
                    "logo": {
                        "@type": "ImageObject",
                        "url": f"{SITE_BASE_URL}/assets/img/logo.png",
                    },
                },
                "mainEntityOfPage": {"@type": "WebPage", "@id": canonical_url},
                "contentLocation": {"@type": "Place", "name": area},
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Rochdale Daily", "item": SITE_BASE_URL + "/"},
                    {"@type": "ListItem", "position": 2, "name": category_label(category), "item": SITE_BASE_URL + "/#" + category},
                    {"@type": "ListItem", "position": 3, "name": str(article.get("title") or "")[:110], "item": canonical_url},
                ],
            },
        ],
    }
    return json.dumps(graph, ensure_ascii=False)


def sources_markup(article: dict[str, Any]) -> str:
    return generic_sources_markup(article)

def hero_image_markup(article: dict[str, Any], image_url: str) -> str:
    credit = str(article.get("image_credit") or "").strip()
    credit_url = str(article.get("image_credit_url") or "").strip()

    if not image_url:
        return ""

    caption = ""
    if credit and credit != "Rochdale Daily category image":
        if credit_url:
            caption = (
                '<figcaption class="article-image-credit">'
                'Image: <a href="' + esc(credit_url) + '" target="_blank" '
                'rel="noopener noreferrer">' + esc(credit) + '</a>'
                '</figcaption>'
            )
        else:
            caption = (
                '<figcaption class="article-image-credit">'
                'Image: ' + esc(credit) +
                '</figcaption>'
            )

    return (
        '<figure class="article-hero-image">'
        '<img src="' + esc(image_url) + '" alt="" loading="eager" '
        'fetchpriority="high">'
        + caption +
        '</figure>'
    )


def render_article_page(article: dict[str, Any], all_articles: list[dict[str, Any]]) -> str:
    slug = article.get('slug')
    title = str(article.get('title') or 'Local news update')
    canonical_url = f'{SITE_BASE_URL}/articles/{slug}.html'
    image_url = absolute_url(article.get('image_url') or '')
    description = meta_description(article)
    category = str(article.get('category') or 'news').lower()
    published = first_published_at(article)
    byline = esc(article.get('byline') or 'Rochdale Daily Newsdesk')
    police_matter = bool(article.get('police_matter'))
    content = insert_incontent_ad(str(article.get('content_html') or ''))
    # A thin story (still under the 200-word development floor) is published
    # timely and thickened in place as more sources arrive. While it is still
    # short, tell the reader it is developing. Driven by the live word count at
    # render time, so the banner disappears automatically once a merge grows the
    # story past the floor - no stored flag to set or clear. Events are a
    # separate, deliberately short format and never carry the note.
    developing_note = ''
    if str(article.get('source_kind') or 'article') != 'event' and visible_word_count(article) < 200:
        developing_note = (
            '<p class="developing-note" style="margin:12px 0;padding:12px 16px;'
            'border-left:4px solid #b3001b;background:#fbeaec;font-weight:600">'
            "This is a developing story. We'll publish more details as they emerge."
            '</p>'
        )
    return f'''<!DOCTYPE html>\n<html lang="en-GB">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <meta name="robots" content="index,follow,max-image-preview:large">\n  <title>{esc(title)} | Rochdale Daily</title>\n  <meta name="description" content="{esc(description)}">\n  <link rel="canonical" href="{esc(canonical_url)}">\n  <link rel="preconnect" href="https://fonts.googleapis.com">\n  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n  <link href="https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@600;700;800&family=Roboto:wght@400;500;700;900&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700;8..60,900&display=swap" rel="stylesheet">\n  <style>{SITE_CSS}</style>\n\n  <meta property="og:type" content="article">\n  <meta property="og:site_name" content="Rochdale Daily">\n  <meta name="author" content="Rochdale Daily Newsdesk">\n  <meta name="keywords" content="{esc(seo_keywords(article))}">\n  <meta property="og:title" content="{esc(title)}">\n  <meta property="og:description" content="{esc(description)}">\n  <meta property="og:image" content="{esc(image_url)}">\n  <meta property="og:url" content="{esc(canonical_url)}">\n  <meta property="article:published_time" content="{esc(published)}">\n  <meta property="article:modified_time" content="{esc(article.get("last_updated_at") or article.get("scraped_at") or published)}">\n  <meta property="article:section" content="{esc(category_label(category))}">\n  <meta name="twitter:card" content="summary_large_image">\n  <meta name="twitter:title" content="{esc(title)}">\n  <meta name="twitter:description" content="{esc(description)}">\n  <meta name="twitter:image" content="{esc(image_url)}">\n\n  <script type="application/ld+json">{json_ld(article, canonical_url, image_url)}</script>\n</head>\n<body>\n  <header class="masthead">\n    <div class="wrap masthead-row">\n      <a class="brand" href="../index.html" aria-label="Rochdale Daily home">\n        <img class="brand-logo" src="/assets/img/logo.png" width="1292" height="706" alt="Rochdale Daily — independent local news" loading="eager" decoding="sync" onerror="this.hidden=true;document.getElementById('brand-text-fallback').hidden=false"><span id="brand-text-fallback" class="brand-text-fallback" hidden>ROCHDALE DAILY</span>\n      </a>\n      <div class="masthead-actions">\n        <a class="header-button" href="../index.html">All stories</a>\n      </div>\n    </div>\n  </header>\n\n  <div class="modal-card" style="margin:24px auto;box-shadow:none">\n    <div class="article-body">\n      <div class="ad-slot ad-slot-leaderboard" data-ad-slot="article-leaderboard" role="presentation" aria-hidden="true"></div>\n      <div class="article-layout">\n        <div class="article-main">\n          <nav class="article-breadcrumb" aria-label="Breadcrumb"><a href="../index.html">Home</a><span aria-hidden="true">›</span><a href="../index.html#{esc(category)}">{esc(category_label(category))}</a></nav>\n          <span class="story-kicker">{esc(category_label(category))}</span>\n          <h1>{esc(title)}</h1>\n          <p class="article-standfirst">{esc(article.get('excerpt') or article.get('summary') or '')}</p>\n          {developing_note}\n          <div class="article-byline">By {byline}</div>\n          {share_icons_markup(canonical_url, title)}\n          <div class="article-copy">{content}\n          {sources_markup(article)}</div>\n          <section class="editorial-legal-note" style="margin-top:24px;padding:18px;border:1px solid #c9c9c9;background:#f6f6f6">\n            <h3 style="margin:0 0 8px">Legal and editorial note</h3>\n            <p>{esc(article.get('legal_disclaimer') or ('No finding of guilt should be inferred from an arrest, allegation or charge. Anyone accused is presumed innocent unless and until convicted.' if article.get('sensitive_story') else 'This article was compiled from identified public sources and may be updated.'))}</p>\n            <p><strong>Right to reply:</strong> {esc(article.get('right_to_reply') or 'Anyone directly affected may request a correction or right of reply by emailing news@rochdaledaily.co.uk.')}</p>\n            <p style="margin:10px 0 0;font-size:13px"><a href="/privacy.html">Privacy</a> &middot; <a href="/terms.html">Terms</a> &middot; <a href="/accessibility.html">Accessibility</a> &middot; <a href="#" data-cookie-settings>Cookie settings</a></p>\n          </section>\n          {(report_box_markup() if police_matter else '')}\n          <section class="comments-section" id="comments-root" data-slug="{esc(slug)}" data-category="{esc(category)}"></section>\n        </div>\n        <aside class="article-sidebar">\n          <div class="ad-slot ad-slot-mrec" data-ad-slot="article-mrec" role="presentation" aria-hidden="true"></div>\n          {related_stories_markup(article, all_articles)}\n        </aside>\n      </div>\n    </div>\n  </div>\n\n  <script>\n    document.addEventListener("click", function(event) {{\n      var trigger = event.target.closest("[data-share]");\n      if (!trigger) return;\n      var action = trigger.dataset.share;\n      var url = trigger.dataset.url;\n      if (action === "copy") {{\n        navigator.clipboard.writeText(url).catch(function() {{}});\n      }}\n      if (action === "facebook") {{\n        window.open("https://www.facebook.com/sharer/sharer.php?u=" + encodeURIComponent(url), "_blank", "noopener,noreferrer");\n      }}\n      if (action === "whatsapp") {{\n        window.open("https://wa.me/?text=" + encodeURIComponent((trigger.dataset.title || "") + " " + url), "_blank", "noopener,noreferrer");\n      }}\n      if (action === "x") {{\n        window.open("https://twitter.com/intent/tweet?text=" + encodeURIComponent(trigger.dataset.title || "") + "&url=" + encodeURIComponent(url), "_blank", "noopener,noreferrer");\n      }}\n      if (action === "bluesky") {{\n        window.open("https://bsky.app/intent/compose?text=" + encodeURIComponent((trigger.dataset.title || "") + " " + url), "_blank", "noopener,noreferrer");\n      }}\n      if (action === "email") {{\n        window.location.href = "mailto:?subject=" + encodeURIComponent(trigger.dataset.title || "") + "&body=" + encodeURIComponent(url);\n      }}\n    }});\n      </script>\n  <script defer src="/assets/js/article-comments.js"></script>\n  <script defer src="/assets/js/cookie-consent.js"></script>\n  <script defer src="/assets/ads.js"></script>\n</body>\n</html>\n'''

def load_articles(blocklist: Any | None = None) -> list[dict[str, Any]]:
    if not ARTICLES_JSON.exists():
        raise SystemExit(f'Could not find {ARTICLES_JSON}')
    payload = json.loads(ARTICLES_JSON.read_text(encoding='utf-8'))
    articles = payload if isinstance(payload, list) else payload.get('articles', [])
    active_blocklist = blocklist if blocklist is not None else load_blocklist()
    published = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        status = article.get('status')
        if status and status != 'published':
            continue
        if source_is_denied(article.get('source_name', ''), article.get('source_url', '')):
            continue
        if not article.get('slug'):
            continue
        if is_blocked_article(article, active_blocklist):
            continue
        article = sanitise_article(article)
        published.append(article)
    return published

def write_sitemap(slugs_with_dates: list[tuple[str, str]]) -> None:
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    entries = [f'  <url><loc>{esc(SITE_BASE_URL)}/</loc><lastmod>{now}</lastmod><changefreq>hourly</changefreq></url>']
    for slug, lastmod in slugs_with_dates:
        loc = f'<loc>{esc(SITE_BASE_URL)}/articles/{esc(slug)}.html</loc>'
        if lastmod:
            entries.append(f'  <url>{loc}<lastmod>{esc(lastmod)}</lastmod><changefreq>daily</changefreq></url>')
        else:
            entries.append(f'  <url>{loc}<changefreq>daily</changefreq></url>')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + '\n'.join(entries) + '\n</urlset>\n'
    SITEMAP_PATH.write_text(xml, encoding='utf-8')

DATE_PUBLISHED_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')

def archive_page_lastmod(path: Path) -> str:
    """Read datePublished from an archived page's own JSON-LD.

    File mtimes are useless on CI (every checkout resets them), so the
    page's embedded NewsArticle schema is the stable record of when the
    story was published. Returns '' when unavailable; the sitemap entry is
    then written without a lastmod, which is valid.
    """
    try:
        match = DATE_PUBLISHED_RE.search(path.read_text(encoding='utf-8', errors='ignore'))
        return match.group(1) if match else ''
    except OSError:
        return ''

def main() -> None:
    from frontpage_pipeline import main as build_frontpage
    build_frontpage()
    blocklist = load_blocklist()
    articles = load_articles(blocklist)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    updated_existing = 0
    slugs_with_dates: list[tuple[str, str]] = []
    for article in articles:
        slug = str(article['slug'])
        out_path = OUTPUT_DIR / f'{slug}.html'
        lastmod = last_modified_at(article)
        slugs_with_dates.append((slug, lastmod))
        if out_path.exists():
            updated_existing += 1
        page_html = render_article_page(article, articles)
        out_path.write_text(page_html, encoding='utf-8')
        written += 1

    # Enforce explicit editorial takedowns against already-generated pages.
    # Ordinary archived pages remain available; only named slug/id removals
    # are deleted here. Feed records have already passed is_blocked_article().
    blocked_slugs = explicit_blocked_slugs()
    deleted_takedowns = 0
    for blocked_slug in sorted(blocked_slugs):
        blocked_path = OUTPUT_DIR / f"{blocked_slug}.html"
        if blocked_path.exists():
            blocked_path.unlink()
            deleted_takedowns += 1

    # Archive coverage: every non-blocklisted page on disk stays in the
    # sitemap, including legacy pages absent from the current JSON archive.
    # The archive keeps growing and published URLs remain discoverable.
    live_slugs = {slug for slug, _ in slugs_with_dates}
    scrubbed = scrub_legacy_comment_markup(OUTPUT_DIR, live_slugs)
    remastheaded = modernise_archived_masthead(OUTPUT_DIR, live_slugs)
    archived = 0
    for path in sorted(OUTPUT_DIR.glob('*.html')):
        if path.stem in live_slugs:
            continue
        slugs_with_dates.append((path.stem, archive_page_lastmod(path)))
        archived += 1
    write_sitemap(slugs_with_dates)
    print(
        f"Generated {written} live article page(s) "
        f"({updated_existing} existing pages refreshed), "
        f"{archived} archived page(s) retained in sitemap, "
        f"{deleted_takedowns} blocklisted page(s) deleted, "
        f"{scrubbed} archived page(s) scrubbed of legacy comment markup; "
        f"{remastheaded} archived page(s) updated to the current masthead; "
        f"sitemap has {len(slugs_with_dates) + 1} URL(s)."
    )
if __name__ == '__main__':
    main()
