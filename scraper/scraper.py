import os
import json
import re
import asyncio
import logging
from datetime import datetime
import feedparser
from playwright.async_api import async_playwright
from openai import OpenAI

# ==============================
# CONFIG
# ==============================

OUTPUT_FILE = "articles.json"
SESSION_FILE = "scraper/session.json"
LOG_FILE = "scraper/scraper.log"

FACEBOOK_SOURCES = {
    "heywood_group": ("Heywood", "https://www.facebook.com/groups/heywoodcommunity"),
    "milnrow_group": ("Milnrow", "https://www.facebook.com/groups/446308878886609"),
    "littleborough_group": ("Littleborough", "https://www.facebook.com/groups/779196125547484"),
    "whitworth_group": ("Whitworth", "https://www.facebook.com/groups/76137500365"),
    "shawclough_healey": ("Shawclough / Healey", "https://www.facebook.com/groups/shawcloughandhealey"),
    "rochdale_online_page": ("Rochdale", "https://m.facebook.com/rochdaleonline/"),
    "bee_network_page": ("Transport", "https://m.facebook.com/beenetworkgm/"),
}

WEB_SOURCES = {
    "men_rochdale": ("Rochdale", "https://www.manchestereveningnews.co.uk/all-about/rochdale"),
    "bing_rochdale": ("Rochdale", "https://www.bing.com/news/search?q=Rochdale&FORM=EWRE"),
}

RSS_SOURCES = {
    "rochdale_council": "https://www.rochdale.gov.uk/news/rss.xml",
    "gmp_news": "https://www.gmp.police.uk/news/rss.xml",
    "bbc_manchester": "http://feeds.bbci.co.uk/news/england/manchester/rss.xml"
}

CATEGORY_KEYWORDS = {
    "crime": ["arrest", "police", "stabbing", "theft", "burglary", "assault", "violence", "court", "knife", "gun", "drugs"],
    "politics": ["council", "mp", "election", "vote", "government", "parliament", "politician", "policy", "minister"],
    "education": ["school", "college", "university", "teacher", "student", "exam", "lesson", "classroom", "headteacher", "pupil"],
    "sport": ["football", "match", "league", "team", "tournament", "goal", "player", "cup", "rugby", "cricket"],
    "transport": ["bus", "tram", "train", "road", "traffic", "accident", "highway", "travel", "parking"],
    "events": ["event", "festival", "concert", "fair", "market", "party", "celebration", "show", "act", "live music", "game"],
    "announcements": ["death", "funeral", "obituary", "wedding", "birthday", "celebration", "anniversary", "congratulations", "passed away", "tribute"]
}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)

# ==============================
# HELPERS
# ==============================

def categorise(text):
    text_lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return category
    return "announcements"

async def rewrite_with_gpt(content, area):
    """Send raw content to OpenAI for rewriting."""
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional UK local news journalist writing for Rochdale Daily."},
                {"role": "user", "content": f"Rewrite this into a factual, concise, UK local news article for {area}:\n\n{content[:2000]}"}
            ],
            max_tokens=500,
            temperature=0.7
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"❌ OpenAI error: {e}")
        return content[:300]

# ==============================
# FACEBOOK SCRAPING
# ==============================

async def validate_session(page):
    try:
        await page.goto("https://facebook.com", wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)
        if await page.locator("input[name='email']").count() > 0:
            logging.error(
                "❌ Facebook session expired.\n"
                "Please regenerate scraper/session.json with:\n"
                "   python -m playwright codegen https://facebook.com --save-storage=scraper/session.json"
            )
            return False
        return True
    except Exception as e:
        logging.error(f"⚠️ Session validation failed: {e}")
        return False

async def fetch_facebook_posts(playwright, area, url):
    browser = None
    results = []
    try:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(storage_state=SESSION_FILE)
        page = await context.new_page()

        if not await validate_session(page):
            return []

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        posts = await page.locator("div[role='article']").all()
        for idx, post in enumerate(posts[:3]):
            try:
                content = await post.inner_text(timeout=5000)
                if len(content.strip()) < 50:
                    continue
                category = categorise(content)
                rewritten = await rewrite_with_gpt(content, area)
                title = rewritten.split("\n")[0][:150]
                article = {
                    "id": f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{area.lower()}-fb-{idx}",
                    "title": title,
                    "slug": re.sub(r"[^a-z0-9]+", "-", title[:50].lower()).strip("-"),
                    "excerpt": rewritten[:200],
                    "content_html": f"<p>{rewritten.replace(chr(10), '</p><p>')}</p>",
                    "area": area,
                    "types": [category],
                    "published_at": datetime.utcnow().isoformat() + "Z",
                    "source_url": url
                }
                results.append(article)
            except:
                continue
    finally:
        if browser:
            await browser.close()
    return results

# ==============================
# WEB SCRAPING (MEN / Bing)
# ==============================

async def fetch_web_articles(playwright, area, url):
    results = []
    try:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        link_elements = await page.locator("a").all()
        texts = [await el.text_content() for el in link_elements]
        links = [await el.get_attribute("href") for el in link_elements]

        for idx, (text, link) in enumerate(zip(texts, links)):
            if text and link and "rochdale" in text.lower():
                content = f"{text}\nFull link: {link}"
                category = categorise(text)
                rewritten = await rewrite_with_gpt(content, area)
                title = rewritten.split("\n")[0][:150]
                article = {
                    "id": f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{area.lower()}-web-{idx}",
                    "title": title,
                    "slug": re.sub(r"[^a-z0-9]+", "-", title[:50].lower()).strip("-"),
                    "excerpt": rewritten[:200],
                    "content_html": f"<p>{rewritten.replace(chr(10), '</p><p>')}</p>",
                    "area": area,
                    "types": [category],
                    "published_at": datetime.utcnow().isoformat() + "Z",
                    "source_url": link
                }
                results.append(article)
        await browser.close()
    except Exception as e:
        logging.error(f"❌ Error scraping {url}: {e}")
    return results

# ==============================
# RSS FEEDS
# ==============================

def fetch_rss_articles():
    results = []
    for name, url in RSS_SOURCES.items():
        feed = feedparser.parse(url)
        for idx, entry in enumerate(feed.entries[:3]):
            content = entry.get("title", "") + " " + entry.get("summary", "")
            category = categorise(content)
            article = {
                "id": f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{name}-rss-{idx}",
                "title": entry.get("title", "Untitled"),
                "slug": re.sub(r"[^a-z0-9]+", "-", entry.get("title", "")[:50].lower()).strip("-"),
                "excerpt": entry.get("summary", "")[:200],
                "content_html": f"<p>{entry.get('summary', '')}</p>",
                "area": "Rochdale",
                "types": [category],
                "published_at": datetime.utcnow().isoformat() + "Z",
                "source_url": entry.get("link", "")
            }
            results.append(article)
    return results

# ==============================
# MAIN
# ==============================

async def main():
    if not os.path.exists(SESSION_FILE):
        logging.error("❌ scraper/session.json not found. Please login with Playwright.")
        return
    if not os.getenv("OPENAI_API_KEY"):
        logging.error("❌ OPENAI_API_KEY not set.")
        return

    logging.info("🚀 Starting scrape...")
    all_articles = []

    async with async_playwright() as p:
        # Facebook
        for area, url in FACEBOOK_SOURCES.values():
            all_articles.extend(await fetch_facebook_posts(p, area, url))
            await asyncio.sleep(5)
        # Websites
        for area, url in WEB_SOURCES.values():
            all_articles.extend(await fetch_web_articles(p, area, url))

    # RSS
    all_articles.extend(fetch_rss_articles())

    if not all_articles:
        logging.warning("⚠️ No new articles scraped.")
        return

    existing = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    existing_ids = {a["id"] for a in existing}
    new_articles = [a for a in all_articles if a["id"] not in existing_ids]

    if new_articles:
        combined = new_articles + existing
        combined = combined[:100]
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(combined, f, indent=2, ensure_ascii=False)
        logging.info(f"✅ Added {len(new_articles)} new articles. Total: {len(combined)}")
    else:
        logging.info("ℹ️ No new unique articles.")

if __name__ == "__main__":
    asyncio.run(main())
