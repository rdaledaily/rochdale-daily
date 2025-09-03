import os
import re
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Tuple

import feedparser
from playwright.async_api import async_playwright, BrowserContext, Page
from openai import OpenAI

# ==============================
# CONFIG
# ==============================

OUTPUT_FILE = "articles.json"
LOG_FILE = "scraper/scraper.log"

FB_PROFILE_DIR = "scraper/fb_profile"
SESSION_FILE = "scraper/session.json"

FACEBOOK_SOURCES: Dict[str, Dict[str, str]] = {
    "heywood": {"type": "facebook_group", "area": "heywood", "url": "https://www.facebook.com/groups/heywoodtown"},
    "littleborough": {"type": "facebook_group", "area": "littleborough", "url": "https://www.facebook.com/groups/779196125547484"},
    "milnrow_newhey": {"type": "facebook_group", "area": "milnrow", "url": "https://www.facebook.com/groups/446308878886609"},
    "whitworth": {"type": "facebook_group", "area": "whitworth", "url": "https://www.facebook.com/groups/76137500365"},
    "shawclough_healey": {"type": "facebook_group", "area": "shawclough_healey", "url": "https://www.facebook.com/groups/shawcloughandhealey"},
    "norden": {"type": "facebook_group", "area": "norden", "url": "https://www.facebook.com/groups/419623505980244"},
    "kirkholt": {"type": "facebook_group", "area": "kirkholt", "url": "https://www.facebook.com/groups/230300881463167"},
    "rochdale_group": {"type": "facebook_group", "area": "rochdale", "url": "https://www.facebook.com/groups/2321259874849245"},
    "rochdaleonline_page": {"type": "facebook_page", "area": "rochdale", "url": "https://m.facebook.com/rochdaleonline/"},
    "beenetwork_page": {"type": "facebook_page", "area": "rochdale", "url": "https://m.facebook.com/beenetworkgm/"},
}

WEB_SOURCES: Dict[str, Dict[str, str]] = {
    "men_rochdale": {"type": "website", "area": "rochdale", "url": "https://www.manchestereveningnews.co.uk/all-about/rochdale"},
    "bing_rochdale": {"type": "website", "area": "rochdale", "url": "https://www.bing.com/news/search?q=Rochdale&qpvt=rochdale+news&FORM=EWRE"},
}

RSS_SOURCES: Dict[str, str] = {
    "rochdale_council": "https://www.rochdale.gov.uk/news/rss.xml",
    "gmp_news": "https://www.gmp.police.uk/news/rss.xml",
    "bbc_manchester": "http://feeds.bbci.co.uk/news/england/manchester/rss.xml",
}

CATEGORY_KEYWORDS = {
    "crime": ["arrest","police","stabbing","theft","burglary","assault","violence","court","knife","gun","drugs","wanted","jailed"],
    "transport": ["bus","tram","train","traffic","roadworks","closure","accident","transport","highway","m62","m60","bee network","parking","car park"],
    "politics": ["council","mp","election","vote","government","parliament","politician","policy","minister","mayor"],
    "education": ["school","college","university","teacher","student","exam","lesson","classroom","headteacher","ofsted","pupil"],
    "sport": ["football","match","league","team","tournament","goal","player","cup","rugby","cricket"],
    "events": ["festival","concert","match","tournament","fair","market","fundraiser","party","gala","celebration","open day","parade","show","act","live music","gig","performance","game","event"],
    "announcements": ["death","funeral","obituary","wedding","birthday","celebration","anniversary","congratulations","passed away","tribute","memorial"],
}

WARD_KEYWORDS = {
    "heywood": ["heywood"],
    "littleborough": ["littleborough"],
    "milnrow": ["milnrow","newhey"],
    "rochdale": ["rochdale","town centre","rochdale town"],
    "shawclough_healey": ["shawclough","healey"],
    "whitworth": ["whitworth"],
    "norden": ["norden","bamford","caldershaw","cutgate"],
    "kirkholt": ["kirkholt"],
}

EXCLUDE_KEYWORDS = [
    "job","jobs","work experience","free","getting rid of","for let","to rent","houses to rent","flat to rent",
    "our company","our business","our colleagues","we visited","we repaired","wanted wednesday","ww","contributor","what time"
]

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==============================
# LOGGING
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)

# ==============================
# HELPERS
# ==============================
def normalise_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

def categorise(text: str) -> str:
    t = (text or "").lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return cat
    return "announcements"

def detect_area(text: str, fallback: str = "rochdale") -> str:
    t = (text or "").lower()
    for area, kws in WARD_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return area
    return fallback

def should_exclude(text: str) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in EXCLUDE_KEYWORDS)

async def rewrite_with_gpt(content: str, area: str) -> str:
    filter_prompt = (
        f"You are a professional UK local news journalist for Rochdale Daily.\n"
        f"Rewrite the following into a concise, factual UK local news article for {area.title()}.\n\n"
        "⚠️ IMPORTANT: Do not rewrite if the content is about:\n"
        "- Jobs or people looking for work\n"
        "- Houses/flats to rent or for let\n"
        "- Individuals asking for donations\n"
        "- Contributors, businesses promoting themselves, or irrelevant chatter\n\n"
        "If irrelevant, reply with ONLY: 'SKIP'.\n\n"
        f"{content[:4000]}"
    )
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You write clear, neutral UK local news."},
                    {"role": "user", "content": filter_prompt},
                ],
                max_tokens=800,
                temperature=0.5,
            )
            rewritten = resp.choices[0].message.content.strip()
            if rewritten.upper().startswith("SKIP"):
                return ""
            return rewritten
        except Exception as e:
            logging.warning(f"OpenAI retry {attempt+1}/3 failed: {e}")
            await asyncio.sleep(1.5 * (attempt + 1))
    return ""

def make_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower().strip())[:60].strip("-")

def build_article(area: str, category: str, rewritten: str, source_url: str, id_suffix: str) -> Dict:
    lines = [l for l in (rewritten or "").split("\n") if l.strip()]
    title = re.sub(r"^#+\s*", "", lines[0])[:150] if lines else "Update"
    body_lines = lines[1:] if len(lines) > 1 else lines
    html = "<p>" + "</p><p>".join([normalise_ws(l) for l in body_lines]) + "</p>"
    return {
        "id": f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{area}-{id_suffix}",
        "title": title,
        "slug": make_slug(title),
        "excerpt": normalise_ws(" ".join(body_lines))[:200],
        "content_html": html,
        "area": area,
        "types": [category],
        "published_at": datetime.utcnow().isoformat() + "Z",
        "image_url": f"assets/img/placeholder_{category}.jpg",
        "source_url": source_url,
    }

# ==============================
# SCRAPERS
# ==============================

async def scrape_facebook_source(pw, name: str, meta: Dict) -> List[Dict]:
    results: List[Dict] = []
    area_default = meta["area"]
    url = meta["url"]

    browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = await browser.new_context(storage_state=SESSION_FILE)
    page = await ctx.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        posts = await page.locator("div[role='article']").all()

        for idx, post in enumerate(posts[:5]):
            try:
                content = await post.inner_text(timeout=4000)
                content = normalise_ws(content)
                if len(content) < 60 or should_exclude(content):
                    continue

                area_detected = detect_area(content, fallback=area_default)
                cat = categorise(content)
                rewritten = await rewrite_with_gpt(content, area_detected)
                if not rewritten:
                    continue

                article = build_article(area_detected, cat, rewritten, url, id_suffix=f"fb-{name}-{idx}")
                results.append(article)
            except Exception as e:
                logging.warning(f"FB post parse error ({name} #{idx}): {e}")
                continue
    finally:
        await ctx.close()
        await browser.close()
    return results

async def scrape_web_source(pw, name: str, meta: Dict) -> List[Dict]:
    results: List[Dict] = []
    area_default = meta.get("area", "rochdale")
    url = meta["url"]

    browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1200)

        link_elements = await page.locator("a").all()
        candidates = []
        for el in link_elements[:100]:
            t = normalise_ws(await el.text_content())
            h = await el.get_attribute("href")
            if t and h and h.startswith("http") and "facebook.com" not in h:
                candidates.append((t, h))

        seen = set()
        for idx, (t, h) in enumerate(candidates[:5]):
            if h in seen or should_exclude(t):
                continue
            seen.add(h)

            area_detected = detect_area(t, fallback=area_default)
            cat = categorise(t)
            rewritten = await rewrite_with_gpt(t, area_detected)
            if not rewritten:
                continue

            article = build_article(area_detected, cat, rewritten, h, id_suffix=f"web-{name}-{idx}")
            results.append(article)
    finally:
        await browser.close()
    return results

async def scrape_rss_sources() -> List[Dict]:
    results: List[Dict] = []
    for name, feed_url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(feed_url)
            for idx, entry in enumerate(feed.entries[:5]):
                title = entry.get("title", "").strip()
                summary = normalise_ws(entry.get("summary", "") or entry.get("description", ""))
                link = entry.get("link", feed_url)
                text = f"{title}\n\n{summary}".strip()

                if should_exclude(text):
                    continue

                area_detected = detect_area(text, fallback="rochdale")
                cat = categorise(text)
                rewritten = await rewrite_with_gpt(text, area_detected)
                if not rewritten:
                    continue

                article = build_article(area_detected, cat, rewritten, link, id_suffix=f"rss-{name}-{idx}")
                results.append(article)
        except Exception as e:
            logging.error(f"RSS parse error [{name}]: {e}")
    return results

# ==============================
# MAIN
# ==============================
async def main():
    if not os.getenv("OPENAI_API_KEY"):
        logging.error("❌ OPENAI_API_KEY not set.")
        return

    logging.info("🚀 Starting scrape...")
    all_articles: List[Dict] = []

    async with async_playwright() as pw:
        for name, meta in FACEBOOK_SOURCES.items():
            fb_articles = await scrape_facebook_source(pw, name, meta)
            all_articles.extend(fb_articles)
        for name, meta in WEB_SOURCES.items():
            web_articles = await scrape_web_source(pw, name, meta)
            all_articles.extend(web_articles)

    rss_articles = await scrape_rss_sources()
    all_articles.extend(rss_articles)

    if not all_articles:
        logging.warning("⚠️ No new articles scraped.")
        return

    existing: List[Dict] = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    seen = {(a.get("slug"), a.get("area")) for a in existing}
    fresh = []
    for a in all_articles:
        k = (a.get("slug"), a.get("area"))
        if k not in seen:
            seen.add(k)
            fresh.append(a)

    combined = fresh + existing
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(combined[:100], f, indent=2, ensure_ascii=False)

    logging.info(f"✅ Added {len(fresh)} new articles. Total stored: {min(len(combined), 100)}")

if __name__ == "__main__":
    asyncio.run(main())
