"""Generate a static, crawlable HTML page for every published article.

This runs after scraper.py on each scheduled run. It reads articles.json and
writes one real HTML file per article to articles/<slug>.html, plus a
sitemap.xml listing every generated page. Existing article pages are never
deleted here -- a story dropping out of the live articles.json (pruned by
retention/freshness) should not 404 an already-indexed URL. Only new slugs
get a new file written; an existing file for a slug is left untouched so a
page's original publish content stays stable even if the story is later
merged/updated under a different id upstream.
"""
from __future__ import annotations
from source_presentation import generic_sources_markup, sanitise_article
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

def load_site_css() -> str:
    if CSS_SOURCE_PATH.exists():
        return CSS_SOURCE_PATH.read_text(encoding='utf-8')
    print(f'WARNING: {CSS_SOURCE_PATH} not found; generated pages will be unstyled.')
    return ''
SITE_CSS = load_site_css()
SOURCE_DENY_DOMAINS = {'rochdaletimes.co.uk', 'rochdaleonline.co.uk'}
SOURCE_DENY_NAMES = {'rochdale times', 'rochdale times paper', 'rochdale online'}
CATEGORY_LABELS = {'crime': 'Crime', 'traffic': 'Traffic', 'transport': 'Transport', 'politics': 'Politics', 'education': 'Education', 'sport': 'Sport', 'events': 'Events', 'business': 'Business', 'community': 'Community', 'health': 'Health', 'environment': 'Environment', 'news': 'News'}

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
    ad_slot = '<div class="ad-slot ad-slot-incontent" role="presentation" aria-hidden="true"></div>'
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

def comments_section_markup(canonical_url: str) -> str:
    return f'<section class="comments-section">\n        <h3>Join the discussion</h3>\n        <div class="fb-comments" data-href="{esc(canonical_url)}" data-width="100%" data-numposts="10"></div>\n        <noscript><p class="comments-fallback">Enable JavaScript and Facebook to view and post comments, or discuss this story on our <a href="https://www.facebook.com/rochdaledaily" target="_blank" rel="noopener">Facebook page</a>.</p></noscript>\n      </section>'

def json_ld(article: dict[str, Any], canonical_url: str, image_url: str) -> str:
    published = article.get('published_at') or article.get('scraped_at') or ''
    data = {'@context': 'https://schema.org', '@type': 'NewsArticle', 'headline': str(article.get('title') or '')[:110], 'image': [image_url], 'datePublished': published, 'dateModified': article.get('scraped_at') or published, 'author': {'@type': 'Organization', 'name': 'Rochdale Daily'}, 'publisher': {'@type': 'Organization', 'name': 'Rochdale Daily', 'logo': {'@type': 'ImageObject', 'url': f'{SITE_BASE_URL}/assets/img/logo.png'}}, 'mainEntityOfPage': {'@type': 'WebPage', '@id': canonical_url}, 'description': meta_description(article)}
    return json.dumps(data, ensure_ascii=False)

def sources_markup(article: dict[str, Any]) -> str:
    return generic_sources_markup(article)

def render_article_page(article: dict[str, Any], all_articles: list[dict[str, Any]]) -> str:
    slug = article.get('slug')
    title = str(article.get('title') or 'Local news update')
    canonical_url = f'{SITE_BASE_URL}/articles/{slug}.html'
    image_url = absolute_url(article.get('image_url') or '')
    description = meta_description(article)
    category = str(article.get('category') or 'news').lower()
    published = article.get('published_at') or article.get('scraped_at') or ''
    byline = esc(article.get('byline') or 'Rochdale Daily Newsdesk')
    police_matter = bool(article.get('police_matter'))
    content = insert_incontent_ad(str(article.get('content_html') or ''))
    return f'''<!DOCTYPE html>\n<html lang="en-GB">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <meta name="robots" content="index,follow,max-image-preview:large">\n  <title>{esc(title)} | Rochdale Daily</title>\n  <meta name="description" content="{esc(description)}">\n  <link rel="canonical" href="{esc(canonical_url)}">\n  <link rel="preconnect" href="https://fonts.googleapis.com">\n  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n  <link href="https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@600;700;800&family=Roboto:wght@400;500;700;900&display=swap" rel="stylesheet">\n  <style>{SITE_CSS}</style>\n\n  <meta property="og:type" content="article">\n  <meta property="og:title" content="{esc(title)}">\n  <meta property="og:description" content="{esc(description)}">\n  <meta property="og:image" content="{esc(image_url)}">\n  <meta property="og:url" content="{esc(canonical_url)}">\n  <meta property="article:published_time" content="{esc(published)}">\n  <meta property="article:section" content="{esc(category_label(category))}">\n  <meta name="twitter:card" content="summary_large_image">\n  <meta name="twitter:title" content="{esc(title)}">\n  <meta name="twitter:description" content="{esc(description)}">\n  <meta name="twitter:image" content="{esc(image_url)}">\n\n  <script type="application/ld+json">{json_ld(article, canonical_url, image_url)}</script>\n</head>\n<body>\n  <div id="fb-root"></div>\n  <script async defer crossorigin="anonymous"\n    src="https://connect.facebook.net/en_GB/sdk.js#xfbml=1&version=v19.0&appId=REPLACE_WITH_YOUR_FACEBOOK_APP_ID">\n  </script>\n\n  <header class="masthead">\n    <div class="wrap masthead-row">\n      <a class="brand" href="../index.html" aria-label="Rochdale Daily home">\n        <span class="brand-text-fallback">ROCHDALE DAILY</span>\n      </a>\n      <div class="masthead-actions">\n        <a class="header-button" href="../index.html">All stories</a>\n        <a class="header-button solid" href="mailto:news@rochdaledaily.co.uk?subject=Story%20for%20Rochdale%20Daily">Send us a story</a>\n      </div>\n    </div>\n  </header>\n\n  <div class="modal-card" style="margin:24px auto;box-shadow:none">\n    <div class="article-body">\n      <div class="ad-slot ad-slot-leaderboard" role="presentation" aria-hidden="true"></div>\n      <div class="article-layout">\n        <div class="article-main">\n          <span class="story-kicker">{esc(category_label(category))}</span>\n          <h1>{esc(title)}</h1>\n          <p class="article-standfirst">{esc(article.get('excerpt') or article.get('summary') or '')}</p>\n          <div class="article-byline">By {byline}</div>\n          <div class="article-share">\n            <button type="button" data-share="copy" data-url="{esc(canonical_url)}">Copy link</button>\n            <button type="button" data-share="facebook" data-url="{esc(canonical_url)}">Facebook</button>\n            <button type="button" data-share="whatsapp" data-url="{esc(canonical_url)}" data-title="{esc(title)}">WhatsApp</button>\n          </div>\n          <div class="article-copy">{content}\n          {sources_markup(article)}</div>\n          <section class="editorial-legal-note" style="margin-top:24px;padding:18px;border:1px solid #c9c9c9;background:#f6f6f6">\n            <h3 style="margin:0 0 8px">Legal and editorial note</h3>\n            <p>{esc(article.get('legal_disclaimer') or ('No finding of guilt should be inferred from an arrest, allegation or charge. Anyone accused is presumed innocent unless and until convicted.' if article.get('sensitive_story') else 'This article was compiled from identified public sources and may be updated.'))}</p>\n            <p><strong>Right to reply:</strong> {esc(article.get('right_to_reply') or 'Anyone directly affected may request a correction or right of reply by emailing news@rochdaledaily.co.uk.')}</p>\n          </section>\n          {(report_box_markup() if police_matter else '')}\n          {comments_section_markup(canonical_url)}\n        </div>\n        <aside class="article-sidebar">\n          <div class="ad-slot ad-slot-mrec" role="presentation" aria-hidden="true"></div>\n          {related_stories_markup(article, all_articles)}\n          {newsletter_box_markup()}\n        </aside>\n      </div>\n    </div>\n  </div>\n\n  <script>\n    document.addEventListener("click", function(event) {{\n      var trigger = event.target.closest("[data-share]");\n      if (!trigger) return;\n      var action = trigger.dataset.share;\n      var url = trigger.dataset.url;\n      if (action === "copy") {{\n        navigator.clipboard.writeText(url).catch(function() {{}});\n      }}\n      if (action === "facebook") {{\n        window.open("https://www.facebook.com/sharer/sharer.php?u=" + encodeURIComponent(url), "_blank", "noopener,noreferrer");\n      }}\n      if (action === "whatsapp") {{\n        window.open("https://wa.me/?text=" + encodeURIComponent((trigger.dataset.title || "") + " " + url), "_blank", "noopener,noreferrer");\n      }}\n    }});\n    var newsletterForm = document.querySelector("[data-newsletter-form]");\n    if (newsletterForm) {{\n      newsletterForm.addEventListener("submit", function(event) {{\n        event.preventDefault();\n        var status = document.querySelector("[data-newsletter-status]");\n        var email = newsletterForm.email.value.trim();\n        if (!email) return;\n        status.textContent = "Signing up…";\n        fetch("/api/newsletter-signup", {{\n          method: "POST",\n          headers: {{ "Content-Type": "application/json" }},\n          body: JSON.stringify({{ email: email }})\n        }}).then(function(response) {{\n          if (!response.ok) throw new Error("failed");\n          status.textContent = "You're signed up. Check your inbox to confirm.";\n          newsletterForm.reset();\n        }}).catch(function() {{\n          status.textContent = "Something went wrong. Please try again shortly.";\n        }});\n      }});\n    }}\n  </script>\n</body>\n</html>\n'''

def load_articles() -> list[dict[str, Any]]:
    if not ARTICLES_JSON.exists():
        raise SystemExit(f'Could not find {ARTICLES_JSON}')
    payload = json.loads(ARTICLES_JSON.read_text(encoding='utf-8'))
    articles = payload if isinstance(payload, list) else payload.get('articles', [])
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
        article = sanitise_article(article)
        published.append(article)
    return published

def write_sitemap(slugs_with_dates: list[tuple[str, str]]) -> None:
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    entries = [f'  <url><loc>{esc(SITE_BASE_URL)}/</loc><lastmod>{now}</lastmod><changefreq>hourly</changefreq></url>']
    for slug, lastmod in slugs_with_dates:
        clean_lastmod = lastmod or now
        entries.append(f'  <url><loc>{esc(SITE_BASE_URL)}/articles/{esc(slug)}.html</loc><lastmod>{esc(clean_lastmod)}</lastmod><changefreq>daily</changefreq></url>')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + '\n'.join(entries) + '\n</urlset>\n'
    SITEMAP_PATH.write_text(xml, encoding='utf-8')

def main() -> None:
    from frontpage_pipeline import main as build_frontpage
    build_frontpage()
    articles = load_articles()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped_existing = 0
    slugs_with_dates: list[tuple[str, str]] = []
    for article in articles:
        slug = str(article['slug'])
        out_path = OUTPUT_DIR / f'{slug}.html'
        lastmod = str(article.get('published_at') or article.get('scraped_at') or '')
        slugs_with_dates.append((slug, lastmod))
        if out_path.exists():
            skipped_existing += 1
        page_html = render_article_page(article, articles)
        out_path.write_text(page_html, encoding='utf-8')
        written += 1
    write_sitemap(slugs_with_dates)
    print(f'Generated {written} new article page(s), left {skipped_existing} existing page(s) untouched, sitemap has {len(slugs_with_dates) + 1} URL(s).')
if __name__ == '__main__':
    main()
