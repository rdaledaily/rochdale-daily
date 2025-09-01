import os
import json
import re
import asyncio
from datetime import datetime
import logging
from playwright.async_api import async_playwright
from openai import OpenAI

# ==============================
# CONFIG
# ==============================

OUTPUT_FILE = "articles.json"
SESSION_FILE = "scraper/session.json"
LOG_FILE = "scraper/scraper.log"

# Facebook groups to scrape
GROUPS = {
    "heywood": "https://www.facebook.com/groups/heywoodcommunity",
    "milnrow": "https://www.facebook.com/groups/143236424374791",
    "rochdale": "https://www.facebook.com/groups/2321259874849245",
    "littleborough": "https://www.facebook.com/groups/779196125547484",
    "kirkholt": "https://www.facebook.com/groups/230300881463167",
    "norden": "https://www.facebook.com/groups/419623505980244",
    "whitworth": "https://www.facebook.com/groups/76137500365",
}

# Category keywords
CATEGORY_KEYWORDS = {
    "crime": [
        "arrest", "police", "stabbing", "theft", "burglary",
        "assault", "violence", "court", "knife", "gun", "drugs"
    ],
    "politics": [
        "council", "MP", "election", "vote", "government",
        "parliament", "politician", "policy", "minister"
    ],
    "education": [
        "school", "college", "university", "teacher",
        "student", "exam", "lesson", "classroom", "headteacher"
    ],
    "sport": [
        "football", "match", "league", "team",
        "tournament", "goal", "player", "cup", "rugby", "cricket"
    ],
    "announcements": [
        "death", "funeral", "obituary", "wedding",
        "birthday", "celebration", "anniversary",
        "congratulations", "passed away", "tribute"
    ]
}

# OpenAI setup
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==============================
# LOGGING SETUP
# ==============================

os.makedirs("scraper", exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ==============================
# HELPERS
# ==============================

def categorise(text):
    """Categorise article text based on keywords."""
    text_lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return category
    return "announcements"  # fallback

async def fetch_posts(playwright, group_url, area):
    """Scrape posts from a Facebook group."""
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(storage_state=SESSION_FILE)
    page = await context.new_page()

    await page.goto(group_url)
    await page.wait_for_timeout(5000)

    posts = await page.locator("div[role='article']").all()
    results = []

    for idx, post in enumerate(posts[:3]):  # limit for testing
        try:
            content = await post.inner_text()
            link = await post.locator("a").first.get_attribute("href")
            category = categorise(content)

            # Rewrite with GPT
            prompt = f"""Rewrite this Facebook post into a short, professional, UK journalistic article.
Make it neutral, factual, and SEO-friendly.
Content: {content}"""

            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a UK journalist rewriting local news."},
                    {"role": "user", "content": prompt}
                ]
            )
            rewritten = completion.choices[0].message.content

            article = {
                "id": f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{area}-{idx}",
                "title": rewritten.split(".")[0],
                "slug": re.sub(r'[^a-z0-9]+', '-', rewritten[:50].lower()).strip("-"),
                "excerpt": rewritten[:200] + "...",
                "content_html": f"<p>{rewritten}</p>",
                "area": area,
                "types": [category],
                "published_at": datetime.utcnow().isoformat() + "Z",
                "image_url": f"assets/img/placeholder_{category}.jpg",
                "source_url": link or group_url
            }
            results.append(article)

            logging.info(f"✅ Scraped article from {area}: {article['title']}")

        except Exception as e:
            logging.error(f"⚠️ Error scraping post in {area}: {e}")
            continue

    await browser.close()
    return results

# ==============================
# MAIN
# ==============================

async def main():
    logging.info("🚀 Starting scrape...")
    all_articles = []

    async with async_playwright() as p:
        for area, url in GROUPS.items():
            logging.info(f"📌 Scraping {area}...")
            posts = await fetch_posts(p, url, area)
            all_articles.extend(posts)

    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []
    else:
        existing = []

    ids = {a["id"] for a in existing}
    new_articles = [a for a in all_articles if a["id"] not in ids]
    combined = new_articles + existing

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    logging.info(f"✅ Added {len(new_articles)} new articles. Saved to {OUTPUT_FILE}.")

if __name__ == "__main__":
    asyncio.run(main())
