"""Source recovery, 19 Oct 2026: navigation links, printed publication dates, source list.

Fixtures copy the real markup captured from each site by
configured_source_diagnostic.py. Run:
    PYTHONPATH=scraper python scraper/test_source_recovery_oct2026.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bs4 import BeautifulSoup  # noqa: E402

import scraper as core  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    if not condition:
        FAILURES.append(label)


# --- navigation links never take an article slot ------------------------------
NAV = [
    ("https://www.edgarwood.org/80/news-and-events/page3", "https://www.edgarwood.org/80/news-and-events"),
    ("https://www.edgarwood.org/80/news-and-events", "https://www.edgarwood.org/80/news-and-events"),
    ("https://www.hornetsrugbyleague.co.uk/news?search=&page=2", "https://www.hornetsrugbyleague.co.uk/news"),
    ("https://www.hopwood.ac.uk/news-and-events/", "https://www.hopwood.ac.uk/news-and-events/latest-news/"),
    ("https://www.hopwood.ac.uk/news-and-events/latest-news/page/2/", "https://www.hopwood.ac.uk/news-and-events/latest-news/"),
    ("https://www.oulderhillacademy.com/category/latest-news/", "https://www.oulderhillacademy.com/latest-news/"),
    ("https://www.actiontogether.org.uk/user", "https://www.actiontogether.org.uk/rochdale-news"),
    ("https://rochdaleafccommunity.org/cart/", "https://www.rochdaleafccommunity.org/news/"),
    ("https://www.rochdaleafccommunity.org/book-now/", "https://www.rochdaleafccommunity.org/news/"),
    ("https://www.northerncarealliance.nhs.uk/news/rochdale-news?ccm_paging_p_b134=2&ccm_order_by_b134=cv.cvDatePublic",
     "https://www.northerncarealliance.nhs.uk/news/rochdale-news"),
    ("https://www.rbh.org.uk/", "https://www.rbh.org.uk/news/"),
]
ARTICLES = [
    ("https://www.hornetsrugbyleague.co.uk/article/1918/young-forward-sam-littler-arrives-on-one-year-deal",
     "https://www.hornetsrugbyleague.co.uk/news"),
    ("https://www.penninecare.nhs.uk/about-us/latest-news/crisis-care-help-home",
     "https://www.penninecare.nhs.uk/about-us/latest-news"),
    ("https://investinrochdale.co.uk/news/post/finalists-revealed-for-rochdale-business-awards-2026",
     "https://investinrochdale.co.uk/news"),
    ("https://www.rbh.org.uk/news/rbh-news/our-october-2026-neighbourhood-walkabouts/", "https://www.rbh.org.uk/news/"),
    ("https://www.rochvalleyradio.com/news-features/139/news/1112/hopwood-hall-will-be-brought-back-into-community-use",
     "https://www.rochvalleyradio.com/"),
    ("https://www.rochdaletimes.co.uk/news/two-days-that-will-decide-the-future-of-hopwood-hall/",
     "https://www.rochdaletimes.co.uk/"),
    ("https://www.rochdale.gov.uk/news/article/1234/egerton-street-roadworks-in-heywood",
     "https://www.rochdale.gov.uk/news"),
]
for url, listing in NAV:
    check(core.discovery_link_is_navigation(url, listing), f"navigation link kept: {url}")
for url, listing in ARTICLES:
    check(not core.discovery_link_is_navigation(url, listing), f"article link dropped: {url}")


# --- printed publication dates -------------------------------------------------
def date_of(html: str) -> str:
    return core.visible_publication_date(BeautifulSoup(html, "lxml"))[:10]


check(date_of('<main><h1>Nine NCA nurses</h1><p class="main__date">14 October 2026</p>'
              '<p class="print-update">Page last updated: 15 October 2026</p></main>') == "2026-10-14",
      "Northern Care Alliance main__date not read (or 'last updated' preferred)")
check(date_of('<div class="publish-date">Published on: 13th October 2026</div><h1>Mud, sweat</h1>') == "2026-10-13",
      "Pennine Care publish-date not read")
check(date_of('<span class="m-news__published">Published : 24 September 2026</span>') == "2026-09-24",
      "RBH m-news__published not read")
check(date_of('<main><article><h1>Finalists revealed</h1><p>Posted by on 14 Oct 2026</p>'
              '<p>The awards were first held in 2019.</p></article></main>') == "2026-10-14",
      "Development Agency 'Posted by on' line not read")
check(date_of('<article><h1>Gala</h1><p>The gala is on 20 June 2026 at the Town Hall.</p></article>') == "",
      "an unlabelled date in body text must not become the publication date")
check(date_of('<article><h1>Open evening</h1><p class="event-date">Published 1 March 2026</p></article>') == "",
      "an event-date element must not become the publication date")
future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%d %B %Y")
check(date_of(f'<p class="post-date">{future}</p>') == "", "a future date must never be a publication date")
listing = "".join(f'<li><p class="main__date">{d} October 2026</p></li>' for d in (14, 13, 9, 1))
check(date_of(f"<main>{listing}</main>") == "", "a listing page (many dates) must not be dated")


# --- the source list itself ----------------------------------------------------
rss = {s["name"]: s for s in core.RSS_SOURCES}
pages = {s["name"]: s for s in core.DISCOVERY_PAGES}
check(rss["Roch Valley Radio"]["url"] == "https://www.rochvalleyradio.com/rss",
      "Roch Valley Radio still points at the feed frozen since 22 July")
for name, url in {
    "Falinge Park High School": "https://www.falingepark.com/feed/",
    "Rochdale Sixth Form College": "https://www.rochdalesfc.ac.uk/rss",
    "Action Together": "https://www.actiontogether.org.uk/rss.xml",
    "Edgar Wood Academy": "https://www.edgarwood.org/rss",
}.items():
    check(rss.get(name, {}).get("url") == url, f"{name} feed missing")
check(pages["Rochdale Hornets"]["link_pattern"] == "/article/", "Hornets pattern not /article/")
check(pages["BBC Manchester"]["link_pattern"] == "/news/articles/", "BBC page pattern still matches section fronts")
for gone in ("Roch Valley Radio Notices", "Action Together Rochdale News", "Your Trust Rochdale News Archive"):
    check(gone not in pages, f"{gone} discovery entry should be replaced by its feed")
check(all(s.get("link_pattern") != "/" or s["name"] == "Rochdale Times" for s in core.DISCOVERY_PAGES
          if s["name"] in {"Action Together Rochdale News", "Rochdale AFC Community Trust"}),
      "a catch-all '/' pattern survived on a feed-backed source")

if FAILURES:
    print("FAILED:")
    for item in FAILURES:
        print(" -", item)
    raise SystemExit(1)
print("source recovery: all checks passed")
