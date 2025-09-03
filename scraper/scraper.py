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

async def rewrite_with_gpt(content: str, area: str) -> str:
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a professional UK local news journalist for Rochdale Daily."},
                    {"role": "user", "content": f"Rewrite the following into a concise, factual UK local news article for {area.title()}.\n- Neutral tone, UK spelling, 150–250 words.\n- Start with an informative headline.\n\n{content[:4000]}"},
                ],
                max_tokens=800,
                temperature=0.5,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logging.warning(f"OpenAI retry {attempt+1}/3 failed: {e}")
            await asyncio.sleep(1.5 * (attempt + 1))
    return content[:600]

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
# FACEBOOK (persistent login)
# ==============================

async def open_fb_context(pw) -> Tuple[BrowserContext, Page]:
    if os.path.isdir(FB_PROFILE_DIR) and any(os.scandir(FB_PROFILE_DIR)):
        ctx = await pw.chromium.launch_persistent_context(
            FB_PROFILE_DIR,
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            viewport={"width": 1280, "height": 900},
        )
        return ctx, await ctx.new_page()

    if not os.path.exists(SESSION_FILE):
        raise FileNotFoundError("Facebook login missing. Use persistent profile or run:\npython -m playwright codegen https://facebook.com --save-storage=scraper/session.json")

    browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = await browser.new_context(storage_state=SESSION_FILE, viewport={"width": 1280, "height": 900})
    return ctx, await ctx.new_page()

async def fb_session_valid(page: Page) -> bool:
    try:
        await page.goto("https://m.facebook.com/", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(1000)
        if await page.locator("input[name='email']").count() > 0:
            return False
        if "checkpoint" in page.url or "/login" in page.url:
            return False
        return True
    except Exception as e:
        logging.warning(f"FB session validation error: {e}")
        return True  # lenient

async def scrape_facebook_source(pw, name: str, meta: Dict) -> List[Dict]:
    results: List[Dict] = []
    area_default = meta["area"]
    url = meta["url"]

    ctx, page = await open_fb_context(pw)
    try:
        if not await fb_session_valid(page):
            logging.error("❌ FB session expired. Refresh cookies.")
            return results

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        for _ in range(2):
            await page.mouse.wheel(0, 1800)
            await page.wait_for_timeout(1000)

        cards = await page.locator("div[role='article']").all()
        for idx, card in enumerate(cards[:5]):
            try:
                content = normalise_ws(await card.inner_text(timeout=4000))
                if len(content) < 60:
                    continue
                area_detected = detect_area(content, fallback=area_default)
                cat = categorise(content)
                rewritten = await rewrite_with_gpt(content, area_detected)
                article = build_article(area_detected, cat, rewritten, url, id_suffix=f"fb-{name}-{idx}")
                results.append(article)
            except Exception as e:
                logging.warning(f"FB post parse error ({name} #{idx}): {e}")
    finally:
        await ctx.close()
    return results

# ==============================
# WEBSITE + RSS (same as before)
# ==============================

# (keep your existing extract_article_from_link, scrape_web_source, scrape_rss_sources here unchanged)

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
            try:
                logging.info(f"📘 FB: {name}")
                all_articles.extend(await scrape_facebook_source(pw, name, meta))
            except Exception as e:
                logging.error(f"FB scrape error {name}: {e}")

        for name, meta in WEB_SOURCES.items():
            try:
                logging.info(f"🌐 Web: {name}")
                all_articles.extend(await scrape_web_source(pw, name, meta))
            except Exception as e:
                logging.error(f"Web scrape error {name}: {e}")

    try:
        logging.info("📰 RSS feeds…")
        all_articles.extend(await scrape_rss_sources())
    except Exception as e:
        logging.error(f"RSS error: {e}")

    if not all_articles:
        logging.warning("⚠️ No new articles scraped.")
        return

    existing = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    def dedup_key(a: Dict) -> Tuple[str, str]:
        return (a.get("slug") or a.get("source_url") or "", a.get("area") or "")

    seen = {dedup_key(a) for a in existing}
    fresh = [a for a in all_articles if dedup_key(a) not in seen]

    combined = fresh + existing
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(combined[:100], f, indent=2, ensure_ascii=False)
    os.replace(tmp, OUTPUT_FILE)

    logging.info(f"✅ Added {len(fresh)} new articles. Total stored: {min(len(combined),100)}")

if __name__ == "__main__":
    asyncio.run(main())
