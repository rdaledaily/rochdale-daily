#!/usr/bin/env python3
"""Generate static, indexable Rochdale Daily category pages.

Category pages deliberately use the same shared newspaper shell as the front
page and article pages. Page-specific CSS below is limited to the category
listing itself; masthead, navigation, brand palette and footer belong to the
shared site/editorial stylesheets.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
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
    return str(
        article.get("first_published_at")
        or article.get("published_at")
        or article.get("scraped_at")
        or ""
    )


def category_of(article: dict) -> str:
    return str(article.get("category") or "news").strip().lower()


def is_published(article: dict) -> bool:
    status = str(article.get("status") or "published").lower()
    return status == "published" and bool(article.get("slug")) and bool(article.get("title"))


def category_page_slugs(articles: list[dict] | None = None) -> list[str]:
    rows = articles if articles is not None else read_json(ARTICLES_PATH, [])
    present = {category_of(a) for a in rows if isinstance(a, dict) and is_published(a)}
    return [slug for slug in CATEGORY_LABELS if slug in present]


def shared_header() -> str:
    return (
        '<header class="masthead">'
        '<div class="wrap masthead-row">'
        '<a class="brand" href="/" aria-label="Rochdale Daily home">'
        '<img class="brand-logo" src="/assets/img/logo.png" width="1292" height="706" '
        'alt="Rochdale Daily — independent local news" loading="eager" decoding="sync">'
        '</a>'
        '<div class="masthead-actions">'
        '<a class="header-button" href="/">Front page</a>'
        '<a class="header-button" href="/wards/">News by ward</a>'
        '</div>'
        '</div>'
        '</header>'
        '<nav class="primary-nav" aria-label="Main navigation">'
        '<div class="wrap nav-row"><ul class="nav-list">'
        '<li><a href="/">Home</a></li>'
        '<li><a href="/news/news.html">Latest</a></li>'
        '<li><a href="/news/crime.html">Crime</a></li>'
        '<li><a href="/news/politics.html">Politics</a></li>'
        '<li><a href="/news/community.html">Community</a></li>'
        '<li><a href="/news/business.html">Business</a></li>'
        '<li><a href="/news/sport.html">Sport</a></li>'
        '<li><a href="/news/events.html">What’s on</a></li>'
        '</ul></div></nav>'
    )


def shared_footer() -> str:
    return (
        '<footer class="site-footer">'
        '<div class="wrap">'
        '<div class="footer-brand">Rochdale Daily</div>'
        '<p class="footer-copy">Independent local news for the Rochdale borough.</p>'
        '<div class="footer-col"><h3>About the paper</h3>'
        '<a href="/about.html">About</a> · '
        '<a href="/editorial-standards.html">Editorial standards</a> · '
        '<a href="/corrections-and-complaints.html">Corrections &amp; complaints</a> · '
        '<a href="/contact.html">Contact</a> · '
        '<a href="/privacy.html">Privacy</a> · '
        '<a href="/terms.html">Terms</a> · '
        '<a href="/accessibility.html">Accessibility</a>'
        '</div></div></footer>'
    )


def chrome_head(title: str, description: str, canonical: str, json_ld: str) -> str:
    category_css = """
.cat-wrap{width:min(1100px,calc(100% - 40px));margin:0 auto;padding:42px 0 64px}
.cat-wrap>h1{margin:0 0 12px;padding-top:10px;border-top:4px solid var(--brand-navy);font-family:var(--font-display);font-size:clamp(36px,5vw,58px);line-height:1;letter-spacing:-.035em}
.cat-standfirst{max-width:65ch;margin:0 0 26px;color:var(--ink-soft);font-size:18px;line-height:1.55}
.cat-nav{display:flex;flex-wrap:wrap;gap:0;margin:0 0 28px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.cat-nav a{padding:10px 12px;color:var(--ink-soft);font-family:var(--font-ui);font-size:12px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;text-decoration:none}
.cat-nav a:first-child{padding-left:0}.cat-nav a:hover,.cat-nav a[aria-current]{color:var(--brand-accent);box-shadow:inset 0 -3px 0 var(--brand-accent)}
.cat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:28px 24px}
.cat-card{display:flex;flex-direction:column;border-bottom:1px solid var(--line)}
.cat-card img{width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:var(--surface)}
.cat-card .cat-body{padding:12px 0 20px}.cat-card h3{margin:5px 0 8px;font-family:var(--font-display);font-size:22px;line-height:1.1;letter-spacing:-.02em}
.cat-card h3 a{color:var(--ink);text-decoration:none}.cat-card p{color:var(--muted);line-height:1.5}.cat-meta{color:var(--muted);font-family:var(--font-ui);font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase}
@media(max-width:760px){.cat-wrap{width:calc(100% - 24px);padding-top:28px}.cat-grid{grid-template-columns:1fr}}
"""
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
        '<link rel="stylesheet" href="/assets/css/site.css">'
        f'<meta property="og:type" content="website"><meta property="og:site_name" content="Rochdale Daily">'
        f'<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}">'
        f'<meta property="og:url" content="{esc(canonical)}">'
        f'<meta property="og:image" content="{SITE}/assets/img/logo.png">'
        '<meta name="twitter:card" content="summary">'
        f'<script type="application/ld+json">{json_ld}</script>'
        f'<style>{category_css}</style>'
        '<link rel="stylesheet" href="/assets/css/editorial-theme.css" data-rd-asset="/assets/css/editorial-theme.css">'
        '</head><body>'
        + shared_header()
        + '<main class="cat-wrap">'
    )


def section_nav(active: str, slugs: list[str]) -> str:
    links = []
    for slug in slugs:
        current = ' aria-current="page"' if slug == active else ""
        links.append(
            f'<a href="/news/{esc(slug)}.html"{current}>{esc(CATEGORY_LABELS[slug])}</a>'
        )
    return '<nav class="cat-nav" aria-label="Sections">' + "".join(links) + "</nav>"


def story_card(article: dict) -> str:
    slug = esc(article.get("slug"))
    title = esc(article.get("title"))
    image = str(article.get("image_url") or "").strip().lstrip("/")
    image_markup = ""
    if image:
        alt = esc(article.get("image_alt") or article.get("title"))
        image_markup = (
            f'<a href="/articles/{slug}.html" tabindex="-1" aria-hidden="true">'
            f'<img src="/{esc(image)}" alt="{alt}" loading="lazy"></a>'
        )
    area = esc(str(article.get("area") or "Rochdale").replace("_", " ").title())
    when = parse_iso(published_at(article))
    date_label = when.strftime("%-d %B %Y") if when.year > 1 else ""
    excerpt = esc(str(article.get("excerpt") or "")[:160])
    return (
        f'<article class="cat-card">{image_markup}<div class="cat-body">'
        f'<div class="cat-meta">{area}{" · " + esc(date_label) if date_label else ""}</div>'
        f'<h3><a href="/articles/{slug}.html">{title}</a></h3>'
        f'<p>{excerpt}</p></div></article>'
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


def render_category(slug: str, stories: list[dict], slugs: list[str]) -> str:
    label = CATEGORY_LABELS[slug]
    title = f"{label} news for the Rochdale borough"
    description = CATEGORY_DESCRIPTIONS.get(slug, f"{label} news from Rochdale Daily.")
    canonical = f"{SITE}/news/{slug}.html"
    head = chrome_head(title, description, canonical, collection_json_ld(slug, stories, canonical))
    body = (
        f'<h1>{esc(label)}</h1>'
        f'<p class="cat-standfirst">{esc(description)}</p>'
        + section_nav(slug, slugs)
        + '<div class="cat-grid">'
        + "".join(story_card(article) for article in stories)
        + '</div>'
    )
    return head + body + '</main>' + shared_footer() + '</body></html>'


def render_index(counts: dict[str, int], slugs: list[str]) -> str:
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
    head = chrome_head(title, description, canonical, json.dumps(graph))
    cards = "".join(
        f'<article class="cat-card"><div class="cat-body"><h3><a href="/news/{esc(slug)}.html">{esc(CATEGORY_LABELS[slug])}</a></h3>'
        f'<p>{esc(CATEGORY_DESCRIPTIONS.get(slug, ""))}</p>'
        f'<div class="cat-meta">{counts[slug]} {"story" if counts[slug] == 1 else "stories"}</div></div></article>'
        for slug in slugs
    )
    body = (
        '<h1>All sections</h1>'
        f'<p class="cat-standfirst">{esc(description)}</p>'
        f'<div class="cat-grid">{cards}</div>'
    )
    return head + body + '</main>' + shared_footer() + '</body></html>'


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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for slug in slugs:
        stories = by_category.get(slug, [])[:MAX_STORIES]
        (OUTPUT_DIR / f"{slug}.html").write_text(
            render_category(slug, stories, slugs), encoding="utf-8"
        )
        written += 1
    counts = {slug: len(by_category.get(slug, [])) for slug in slugs}
    (OUTPUT_DIR / "index.html").write_text(render_index(counts, slugs), encoding="utf-8")
    print(f"Generated {written} category page(s) plus /news/index.html: {', '.join(slugs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
