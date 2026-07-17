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
        return f'{SITE_BASE_URL}/assets/img/stock_news.jpg'
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

def newsletter_box_markup() -> str:
    return '<div class="sidebar-box newsletter-box">\n        <h3>Get the morning briefing</h3>\n        <p>One free email a day with Rochdale\'s top stories. No spam.</p>\n        <form class="newsletter-form" data-newsletter-form onsubmit="return false;">\n          <input type="email" name="email" placeholder="you@example.com" required autocomplete="email">\n          <button type="submit">Sign up free</button>\n        </form>\n        <div class="newsletter-status" data-newsletter-status></div>\n        <p class="newsletter-note">Unsubscribe anytime. See our <a href="../privacy.html" style="color:#cfcfcf">privacy policy</a>.</p>\n      </div>'

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
    copy_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 8h11v11H8z"/><path d="M5 16H3V3h13v2"/></svg>'
    facebook_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 8h3V4h-3c-3 0-5 2-5 5v3H6v4h3v7h4v-7h3l1-4h-4V9c0-.7.3-1 1-1z"/></svg>'
    whatsapp_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.8a8 8 0 0 1-11.8 7L4 20l1.2-4A8 8 0 1 1 20 11.8z"/><path d="M9 8.5c.3 2.8 2 4.5 4.8 5l1-1.2 2 .9c-.5 1.7-1.6 2.4-3.2 2.1-3.7-.7-6-3-6.7-6.7-.3-1.6.4-2.7 2.1-3.2l.9 2-.9 1.1z"/></svg>'
    return (
        '<div class="article-share" aria-label="Share this article">'
        f'<button class="share-icon-button" type="button" data-share="copy" data-url="{esc(canonical_url)}" aria-label="Copy article link">{copy_icon}<span class="visually-hidden">Copy link</span></button>'
        f'<button class="share-icon-button" type="button" data-share="facebook" data-url="{esc(canonical_url)}" aria-label="Share on Facebook">{facebook_icon}<span class="visually-hidden">Facebook</span></button>'
        f'<button class="share-icon-button" type="button" data-share="whatsapp" data-url="{esc(canonical_url)}" data-title="{esc(title)}" aria-label="Share on WhatsApp">{whatsapp_icon}<span class="visually-hidden">WhatsApp</span></button>'
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
    return f'''<!DOCTYPE html>\n<html lang="en-GB">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <meta name="robots" content="index,follow,max-image-preview:large">\n  <title>{esc(title)} | Rochdale Daily</title>\n  <meta name="description" content="{esc(description)}">\n  <link rel="canonical" href="{esc(canonical_url)}">\n  <link rel="preconnect" href="https://fonts.googleapis.com">\n  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n  <link href="https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@600;700;800&family=Roboto:wght@400;500;700;900&display=swap" rel="stylesheet">\n  <style>{SITE_CSS}</style>\n\n  <meta property="og:type" content="article">\n  <meta property="og:site_name" content="Rochdale Daily">\n  <meta name="author" content="Rochdale Daily Newsdesk">\n  <meta name="keywords" content="{esc(seo_keywords(article))}">\n  <meta property="og:title" content="{esc(title)}">\n  <meta property="og:description" content="{esc(description)}">\n  <meta property="og:image" content="{esc(image_url)}">\n  <meta property="og:url" content="{esc(canonical_url)}">\n  <meta property="article:published_time" content="{esc(published)}">\n  <meta property="article:modified_time" content="{esc(article.get("last_updated_at") or article.get("scraped_at") or published)}">\n  <meta property="article:section" content="{esc(category_label(category))}">\n  <meta name="twitter:card" content="summary_large_image">\n  <meta name="twitter:title" content="{esc(title)}">\n  <meta name="twitter:description" content="{esc(description)}">\n  <meta name="twitter:image" content="{esc(image_url)}">\n\n  <script type="application/ld+json">{json_ld(article, canonical_url, image_url)}</script>\n</head>\n<body>\n  <header class="masthead">\n    <div class="wrap masthead-row">\n      <a class="brand" href="../index.html" aria-label="Rochdale Daily home">\n        <span class="brand-text-fallback">ROCHDALE DAILY</span>\n      </a>\n      <div class="masthead-actions">\n        <a class="header-button" href="../index.html">All stories</a>\n        <a class="header-button solid" href="mailto:news@rochdaledaily.co.uk?subject=Story%20for%20Rochdale%20Daily">Send us a story</a>\n      </div>\n    </div>\n  </header>\n\n  <div class="modal-card" style="margin:24px auto;box-shadow:none">\n    <div class="article-body">\n      <div class="ad-slot ad-slot-leaderboard" data-ad-slot="article-leaderboard" role="presentation" aria-hidden="true"></div>\n      <div class="article-layout">\n        <div class="article-main">\n          <nav class="article-breadcrumb" aria-label="Breadcrumb"><a href="../index.html">Home</a><span aria-hidden="true">›</span><a href="../index.html#{esc(category)}">{esc(category_label(category))}</a></nav>\n          <span class="story-kicker">{esc(category_label(category))}</span>\n          <h1>{esc(title)}</h1>\n          <p class="article-standfirst">{esc(article.get('excerpt') or article.get('summary') or '')}</p>\n          <div class="article-byline">By {byline}</div>\n          {share_icons_markup(canonical_url, title)}\n          <div class="article-copy">{content}\n          {sources_markup(article)}</div>\n          <section class="editorial-legal-note" style="margin-top:24px;padding:18px;border:1px solid #c9c9c9;background:#f6f6f6">\n            <h3 style="margin:0 0 8px">Legal and editorial note</h3>\n            <p>{esc(article.get('legal_disclaimer') or ('No finding of guilt should be inferred from an arrest, allegation or charge. Anyone accused is presumed innocent unless and until convicted.' if article.get('sensitive_story') else 'This article was compiled from identified public sources and may be updated.'))}</p>\n            <p><strong>Right to reply:</strong> {esc(article.get('right_to_reply') or 'Anyone directly affected may request a correction or right of reply by emailing news@rochdaledaily.co.uk.')}</p>\n          </section>\n          {(report_box_markup() if police_matter else '')}\n        </div>\n        <aside class="article-sidebar">\n          <div class="ad-slot ad-slot-mrec" data-ad-slot="article-mrec" role="presentation" aria-hidden="true"></div>\n          {related_stories_markup(article, all_articles)}\n          {newsletter_box_markup()}\n        </aside>\n      </div>\n    </div>\n  </div>\n\n  <script>\n    document.addEventListener("click", function(event) {{\n      var trigger = event.target.closest("[data-share]");\n      if (!trigger) return;\n      var action = trigger.dataset.share;\n      var url = trigger.dataset.url;\n      if (action === "copy") {{\n        navigator.clipboard.writeText(url).catch(function() {{}});\n      }}\n      if (action === "facebook") {{\n        window.open("https://www.facebook.com/sharer/sharer.php?u=" + encodeURIComponent(url), "_blank", "noopener,noreferrer");\n      }}\n      if (action === "whatsapp") {{\n        window.open("https://wa.me/?text=" + encodeURIComponent((trigger.dataset.title || "") + " " + url), "_blank", "noopener,noreferrer");\n      }}\n    }});\n    var newsletterForm = document.querySelector("[data-newsletter-form]");\n    if (newsletterForm) {{\n      newsletterForm.addEventListener("submit", function(event) {{\n        event.preventDefault();\n        var status = document.querySelector("[data-newsletter-status]");\n        var email = newsletterForm.email.value.trim();\n        if (!email) return;\n        status.textContent = "Signing up…";\n        fetch("/api/newsletter-signup", {{\n          method: "POST",\n          headers: {{ "Content-Type": "application/json" }},\n          body: JSON.stringify({{ email: email }})\n        }}).then(function(response) {{\n          if (!response.ok) throw new Error("failed");\n          status.textContent = "You're signed up. Check your inbox to confirm.";\n          newsletterForm.reset();\n        }}).catch(function() {{\n          status.textContent = "Something went wrong. Please try again shortly.";\n        }});\n      }});\n    }}\n  </script>\n  <script defer src="/assets/ads.js"></script>\n</body>\n</html>\n'''

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
        f"sitemap has {len(slugs_with_dates) + 1} URL(s)."
    )
if __name__ == '__main__':
    main()
