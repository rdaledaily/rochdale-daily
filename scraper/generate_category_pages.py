#!/usr/bin/env python3
"""Generate one static, indexable page per news category at /news/<category>.html.

Why: category.html was a single client-rendered page for every section
(?type=crime, ?type=politics ...) with the title "Rochdale Daily • Category", so
search engines saw one thin URL for the whole paper's sections. Ward pages
already showed the right pattern (static file, unique title, description and
canonical); this mirrors it for categories and adds CollectionPage JSON-LD.

Output: /news/<category>.html for every category in CATEGORY_LABELS that has at
least one published story, plus /news/index.html listing them. Pages are
rebuilt on every run, so they are never stale. Sitemap entries are written by
generate_pages.write_sitemap via category_page_slugs().
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
CSS_PATH = ROOT / "assets" / "css" / "site.css"
OUTPUT_DIR = ROOT / "news"
SITE = "https://rochdaledaily.co.uk"
MAX_STORIES = 40

CATEGORY_LABELS = {
    "news": "News",
    "crime": "Crime",
    "politics": "Politics",
    "community": "Community",
    "business": "Business",
    "sport": "Sport",
    "health": "Health",
    "education": "Education",
    "environment": "Environment",
    "transport": "Transport",
    "traffic": "Traffic",
    "events": "Events",
    "showbiz": "Showbiz",
}

# One sentence per section, written for the search snippet and for the reader.
CATEGORY_DESCRIPTIONS = {
    "news": "The latest verified news from across the Rochdale borough: Rochdale, Heywood, Middleton, Littleborough, Milnrow and Wardle.",
    "crime": "Crime and court news for the Rochdale borough, sourced from Greater Manchester Police and the courts, with reporting routes on every story.",
    "politics": "Rochdale Borough Council, ward councillors, MPs and local decisions, reported plainly with documents linked.",
    "community": "Community news from the Rochdale borough: volunteers, charities, schools, faith groups and neighbourhood life.",
    "business": "Business news for Rochdale: openings, closures, planning, jobs and the local economy.",
    "sport": "Rochdale AFC, Rochdale Hornets, grassroots clubs and local athletes across the borough.",
    "health": "Health news for Rochdale: Rochdale Infirmary, GP services, public health and wellbeing.",
    "education": "Schools, colleges and education news across the Rochdale borough.",
    "environment": "Environment, planning, weather and green spaces across the Rochdale borough.",
    "transport": "Trains, trams, buses and transport changes affecting the Rochdale borough.",
    "traffic": "Road closures, roadworks and traffic disruption across the Rochdale borough.",
    "events": "What's on in the Rochdale borough: events, festivals, gigs and family days out.",
    "showbiz": "Entertainment and showbiz stories with a Rochdale connection.",
}


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


TOKEN_IMPORT_PATTERN = re.compile(
    r'@import\s+url\(\s*[\'"]?/?assets/css/rd-tokens\.css[\'"]?\s*\)\s*;\s*', re.I
)


def load_css() -> str:
    """site.css for inlining, with the token @import lifted out.

    The tokens are linked in the head instead. Inside an inline <style> an
    @import is only found once that block is parsed, so these section pages
    would block on a second round trip before they had a colour or a font.
    """
    try:
        css = CSS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""
    return TOKEN_IMPORT_PATTERN.sub("", css, count=1)


def parse_iso(value) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def published_at(article: dict) -> str:
    return str(article.get("first_published_at") or article.get("published_at") or article.get("scraped_at") or "")


def category_of(article: dict) -> str:
    return str(article.get("category") or "news").strip().lower()


def is_published(article: dict) -> bool:
    status = str(article.get("status") or "published").lower()
    return status == "published" and bool(article.get("slug")) and bool(article.get("title"))


def category_page_slugs(articles: list[dict] | None = None) -> list[str]:
    """Categories that will get a page: every label with at least one story."""
    rows = articles if articles is not None else read_json(ARTICLES_PATH, [])
    present = {category_of(a) for a in rows if isinstance(a, dict) and is_published(a)}
    return [slug for slug in CATEGORY_LABELS if slug in present]


MASTHEAD = '<header class="masthead"><div class="wrap masthead-row"><a class="brand" href="/index.html" aria-label="Rochdale Daily home"><img class="brand-logo" src="/assets/img/logo.png" width="1292" height="706" alt="Rochdale Daily — independent local news" loading="eager" decoding="sync" onerror="this.hidden=true;document.getElementById(\'brand-text-fallback\').hidden=false"><span id="brand-text-fallback" class="brand-text-fallback" hidden>ROCHDALE DAILY</span></a><div class="masthead-actions">{actions}</div></div></header>'
EDITORIAL_LINK = '<link rel="stylesheet" href="/assets/css/editorial-theme.css" data-rd-asset="/assets/css/editorial-theme.css">'
SHARED_CSS = '.rd-page{max-width:1080px;margin:0 auto;padding:28px 20px 64px}.rd-kicker{display:inline-block;margin:0 0 6px;font-family:var(--font-ui);font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}.rd-page h1{margin:0 0 10px;font-family:var(--font-display);font-size:clamp(32px,5vw,50px);line-height:1.02;letter-spacing:-.02em;color:var(--ink)}.rd-lede{margin:0 0 26px;max-width:720px;color:var(--muted);font-size:17px;line-height:1.5}.rd-h2{margin:34px 0 14px;padding-top:10px;border-top:3px solid var(--ink);font-family:var(--font-display);font-size:24px;letter-spacing:-.01em}.rd-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px}.rd-card{display:flex;flex-direction:column;gap:6px;padding:16px;background:var(--card,#fff);border:1px solid var(--line);border-top:3px solid var(--ink)}.rd-card h3{margin:0;font-family:var(--font-display);font-size:19px;line-height:1.2}.rd-card h3 a{color:var(--ink);text-decoration:none}.rd-card h3 a:hover{text-decoration:underline;text-underline-offset:3px}.rd-card p{margin:0;color:var(--muted);font-size:14px;line-height:1.5}.rd-card img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;background:var(--surface-2,#eceff1);margin:-16px -16px 8px;width:calc(100% + 32px)}.rd-meta{font-family:var(--font-ui);font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}.rd-links{margin:0 0 8px;color:var(--muted);font-size:15px}.rd-links a{color:var(--accent);font-weight:600}.site-footer{margin-top:40px;background:var(--brand-navy,#0b1f3a);color:#dfe6ee;padding:28px 0}.site-footer .footer-brand{margin:0 0 6px;font-family:var(--font-display);font-size:22px;font-weight:800;color:#fff;text-transform:none}.site-footer .footer-note{margin:0;font-size:14px;line-height:1.6}.site-footer a{color:#fff}@media(max-width:600px){.rd-page{padding:20px 16px 48px}}'
FOOTER = '<footer class="site-footer"><div class="wrap"><p class="footer-brand">Rochdale Daily</p><p class="footer-note">Independent local news for the Rochdale borough. <a href="/editorial-standards.html">Editorial standards</a> · <a href="/corrections-and-complaints.html">Corrections</a> · <a href="/privacy.html">Privacy</a> · <a href="/contact.html">Contact</a></p></div></footer><script defer src="/assets/js/cookie-consent.js"></script>'


def chrome_head(title: str, description: str, canonical: str, css: str, json_ld: str) -> str:
    """Same masthead, editorial layer and footer as the article pages."""
    actions = ('<a class="header-button" href="/index.html">All stories</a>'
               '<a class="header-button" href="/news/">All sections</a>')
    return (
        '<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="index,follow,max-image-preview:large">'
        f'<title>{esc(title)} | Rochdale Daily</title>'
        f'<meta name="description" content="{esc(description)}">'
        f'<link rel="canonical" href="{esc(canonical)}">'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700'
        '&family=Libre+Franklin:wght@600;700;800&display=swap" rel="stylesheet">'
        '<link rel="stylesheet" href="/assets/css/rd-tokens.css">'
        '<meta property="og:type" content="website"><meta property="og:site_name" content="Rochdale Daily">'
        f'<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}">'
        f'<meta property="og:url" content="{esc(canonical)}">'
        f'<meta property="og:image" content="{SITE}/assets/img/logo.png">'
        '<meta name="twitter:card" content="summary">'
        f'<script type="application/ld+json">{json_ld}</script>'
        f"<style>{css}\n" + SHARED_CSS +
        ".cat-nav{display:flex;flex-wrap:wrap;gap:6px 4px;margin:0 0 22px}"
        ".cat-nav a{display:inline-block;min-height:40px;line-height:40px;padding:0 12px;font-family:var(--font-ui);font-size:13px;font-weight:700;letter-spacing:.025em;text-transform:uppercase;text-decoration:none;color:var(--ink)}"
        ".cat-nav a:first-child{padding-left:0}"
        ".cat-nav a:hover,.cat-nav a[aria-current]{color:var(--accent);box-shadow:inset 0 -3px 0 var(--accent)}"
        "</style>" + EDITORIAL_LINK + "</head><body>"
        + MASTHEAD.replace("{actions}", actions)
        + '<main class="rd-page">'
    )


FOOT = "</main>" + FOOTER + "</body></html>"



def section_nav(active: str, slugs: list[str]) -> str:
    links = []
    for slug in slugs:
        current = ' aria-current="page"' if slug == active else ""
        links.append(f'<a href="/news/{esc(slug)}.html"{current}>{esc(CATEGORY_LABELS[slug])}</a>')
    return '<nav class="cat-nav" aria-label="Sections">' + "".join(links) + "</nav>"


def story_card(article: dict) -> str:
    slug = esc(article.get("slug"))
    title = esc(article.get("title"))
    image = str(article.get("image_url") or "").strip().lstrip("/")
    image_markup = ""
    if image:
        alt = esc(article.get("image_alt") or article.get("title"))
        image_markup = f'<a href="/articles/{slug}.html" tabindex="-1" aria-hidden="true"><img src="/{esc(image)}" alt="{alt}" loading="lazy"></a>'
    area = esc(str(article.get("area") or "Rochdale").replace("_", " ").title())
    when = parse_iso(published_at(article))
    date_label = when.strftime("%-d %B %Y") if when.year > 1 else ""
    excerpt = esc(str(article.get("excerpt") or "")[:160])
    return (
        f'<article class="rd-card">{image_markup}<div class="cat-body">'
        f'<div class="rd-meta">{area}{" · " + esc(date_label) if date_label else ""}</div>'
        f'<h3><a href="/articles/{slug}.html">{title}</a></h3>'
        f"<p>{excerpt}</p></div></article>"
    )


def collection_json_ld(slug: str, stories: list[dict], canonical: str) -> str:
    label = CATEGORY_LABELS[slug]
    items = [
        {
            "@type": "ListItem",
            "position": index + 1,
            "url": f"{SITE}/articles/{article.get('slug')}.html",
            "name": str(article.get("title") or "")[:110],
        }
        for index, article in enumerate(stories[:20])
    ]
    graph = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "@id": canonical,
        "name": f"{label} news for the Rochdale borough",
        "description": CATEGORY_DESCRIPTIONS.get(slug, ""),
        "url": canonical,
        "inLanguage": "en-GB",
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE},
        "publisher": {"@type": "NewsMediaOrganization", "name": "Rochdale Daily", "url": SITE},
        "mainEntity": {"@type": "ItemList", "itemListElement": items},
    }
    return json.dumps(graph, ensure_ascii=False)


def render_category(slug: str, stories: list[dict], slugs: list[str], css: str) -> str:
    label = CATEGORY_LABELS[slug]
    title = f"{label} news for the Rochdale borough"
    description = CATEGORY_DESCRIPTIONS.get(slug, f"{label} news from Rochdale Daily.")
    canonical = f"{SITE}/news/{slug}.html"
    head = chrome_head(title, description, canonical, css, collection_json_ld(slug, stories, canonical))
    body = (
        f"<h1>{esc(label)}</h1>"
        f'<p class="rd-lede">{esc(description)}</p>'
        + section_nav(slug, slugs)
        + '<div class="rd-grid">'
        + "".join(story_card(article) for article in stories)
        + "</div>"
    )
    return head + body + FOOT


def render_index(counts: dict[str, int], slugs: list[str], css: str) -> str:
    title = "All sections"
    description = "Every section of Rochdale Daily: crime, politics, community, business, sport, health, education, environment, transport and what's on."
    canonical = f"{SITE}/news/"
    graph = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Rochdale Daily sections",
        "url": canonical,
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE},
    }
    head = chrome_head(title, description, canonical, css, json.dumps(graph))
    cards = "".join(
        f'<article class="rd-card"><div class="cat-body"><h3><a href="/news/{esc(slug)}.html">{esc(CATEGORY_LABELS[slug])}</a></h3>'
        f"<p>{esc(CATEGORY_DESCRIPTIONS.get(slug, ''))}</p>"
        f'<div class="rd-meta">{counts[slug]} {"story" if counts[slug] == 1 else "stories"}</div></div></article>'
        for slug in slugs
    )
    return head + "<h1>All sections</h1>" + f'<p class="rd-lede">{esc(description)}</p>' + f'<div class="rd-grid">{cards}</div>' + FOOT


def main() -> int:
    rows = read_json(ARTICLES_PATH, [])
    if not isinstance(rows, list):
        raise SystemExit("articles.json must contain a JSON array")
    articles = [row for row in rows if isinstance(row, dict) and is_published(row)]
    articles.sort(key=lambda a: parse_iso(published_at(a)), reverse=True)

    by_category: dict[str, list[dict]] = {}
    for article in articles:
        by_category.setdefault(category_of(article), []).append(article)

    slugs = category_page_slugs(articles)
    css = load_css()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for slug in slugs:
        stories = by_category.get(slug, [])[:MAX_STORIES]
        (OUTPUT_DIR / f"{slug}.html").write_text(render_category(slug, stories, slugs, css), encoding="utf-8")
        written += 1
    counts = {slug: len(by_category.get(slug, [])) for slug in slugs}
    (OUTPUT_DIR / "index.html").write_text(render_index(counts, slugs, css), encoding="utf-8")
    print(f"Generated {written} category page(s) plus /news/index.html: {', '.join(slugs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
