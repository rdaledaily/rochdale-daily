import os
import json
import re
import asyncio
import hashlib
import logging
from datetime import datetime
from playwright.async_api import async_playwright
from openai import OpenAI

# ==============================
# CONFIG
# ==============================

OUTPUT_FILE = "articles.json"              # articles.json in repo root
SESSION_FILE = "scraper/session.json"      # Facebook session cookies
LOG_FILE = "scraper/scraper.log"

GROUPS = {
    "heywood": "https://www.facebook.com/groups/heywoodcommunity",
    "milnrow": "https://www.facebook.com/groups/143236424374791", 
    "rochdale": "https://www.facebook.com/groups/2321259874849245",
    "littleborough": "https://www.facebook.com/groups/779196125547484",
    "kirkholt": "https://www.facebook.com/groups/230300881463167",
    "norden": "https://www.facebook.com/groups/419623505980244",
    "whitworth": "https://www.facebook.com/groups/76137500365",
}

CATEGORY_KEYWORDS = {
    "crime": ["arrest", "police", "stabbing", "theft", "burglary", "assault", "violence", "court", "knife", "gun", "drugs"],
    "politics": ["council", "mp", "election", "vote", "government", "parliament", "politician", "policy", "minister"], 
    "education": ["school", "college", "university", "teacher", "student", "exam", "lesson", "classroom", "headteacher"],
    "sport": ["football", "match", "league", "team", "tournament", "goal", "player", "cup", "rugby", "cricket"],
    "announcements": ["death", "funeral", "obituary", "wedding", "birthday", "celebration", "anniversary", "congratulations", "passed away", "tribute"]
}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# ==============================
# HELPERS
# ==============================

def make_id(text, area):
    """Generate stable ID from post text + area."""
    return f"{area}-{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}"

def categorise(text):
    text_lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return category
    return "announcements"

async def validate_session(page):
    """Check if Facebook session is still valid."""
    try:
        await page.goto("https://facebook.com", wait_until='domcontentloaded', timeout=15000)
        await page.wait_for_timeout(2000)

        if await page.locator("input[name='email']").count() > 0:
            return False
        return True
    except Exception as e:
        logging.error(f"Session validation failed: {e}")
        return False

async def fetch_posts(playwright, group_url, area):
    """Scrape posts from a Facebook group."""
    results = []
    browser = None

    try:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            storage_state=SESSION_FILE,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        if not await validate_session(page):
            logging.error(f"❌ Session expired for {area}")
            return []

        logging.info(f"🌍 Navigating to {group_url}")
        await page.goto(group_url, wait_until='domcontentloaded', timeout=40000)
        await page.wait_for_timeout(5000)

        # Try multiple selectors for posts
        post_selectors = ["div[role='article']", "[data-pagelet^='FeedUnit']"]
        posts = []
        for sel in post_selectors:
            try:
                await page.wait_for_selector(sel, timeout=10000)
                posts = await page.locator(sel).all()
                if posts:
                    break
            except:
                continue

        if not posts:
            logging.warning(f"⚠️ No posts found in {area}")
            return []

        for idx, post in enumerate(posts[:5]):  # limit per group
            try:
                content = await post.inner_text(timeout=5000)
                if len(content.strip()) < 50:
                    continue

                link = None
                try:
                    link_el = post.locator("a").first
                    if await link_el.count() > 0:
                        link = await link_el.get_attribute("href")
                        if link and not link.startswith("http"):
                            link = "https://facebook.com" + link
                except:
                    pass

                # Categorise
                category = categorise(content)

                # Rewrite with OpenAI
                prompt = f"""Rewrite this community Facebook post into a short professional UK news article.
Keep it factual, concise, neutral. Use UK English.

Post:
{content[:1500]}"""

                try:
                    completion = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "You are a professional UK local news journalist writing for Rochdale Daily."},
                            {"role": "user", "content": prompt}
                        ],
                        max_tokens=500,
                        temperature=0.7
                    )
                    rewritten = completion.choices[0].message.content.strip()
                except Exception as e:
                    logging.error(f"OpenAI API error: {e}")
                    continue

                title = re.sub(r'^#+\s*', '', rewritten.split("\n")[0])[:150]

                article = {
                    "id": make_id(content, area),
                    "title": title,
                    "slug": re.sub(r'[^a-z0-9]+', '-', title.lower())[:50].strip("-"),
                    "excerpt": rewritten[:200] + "..." if len(rewritten) > 200 else rewritten,
                    "content_html": f"<p>{rewritten.replace(chr(10), '</p><p>')}</p>",
                    "area": area,
                    "types": [category],
                    "published_at": datetime.utcnow().isoformat() + "Z",
                    "image_url": f"assets/img/placeholder_{category}.jpg",
                    "source_url": link or group_url
                }

                results.append(article)
                logging.info(f"✅ Article scraped: {title[:60]}...")

            except Exception as e:
                logging.error(f"Error with post {idx} in {area}: {e}")

    except Exception as e:
        logging.error(f"Browser error for {area}: {e}")
    finally:
        if browser:
            await browser.close()

    return results

# ==============================
# MAIN
# ==============================

async def main():
    if not os.path.exists(SESSION_FILE):
        logging.error("❌ No session.json found. Please export cookies first.")
        return

    if not os.getenv("OPENAI_API_KEY"):
        logging.error("❌ No OPENAI_API_KEY found in environment.")
        return

    logging.info("🚀 Starting scrape...")
    all_articles = []

    async with async_playwright() as p:
        for area, url in GROUPS.items():
            posts = await fetch_posts(p, url, area)
            all_articles.extend(posts)
            await asyncio.sleep(3)

    if not all_articles:
        logging.warning("⚠️ No new articles found.")
        return

    existing = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except:
            existing = []

    existing_ids = {a["id"] for a in existing}
    new_articles = [a for a in all_articles if a["id"] not in existing_ids]

    if new_articles:
        combined = new_articles + existing
        combined = combined[:100]  # keep last 100
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(combined, f, indent=2, ensure_ascii=False)
        logging.info(f"🆕 Added {len(new_articles)} articles. Total now {len(combined)}")
    else:
        logging.info("ℹ️ No new articles to add")

if __name__ == "__main__":
    asyncio.run(main())
