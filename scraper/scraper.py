import os
import json
import re
import asyncio
import subprocess
from datetime import datetime
import logging
from playwright.async_api import async_playwright
from openai import OpenAI
import time

# ==============================
# CONFIG (same as yours)
# ==============================

OUTPUT_FILE = "articles.json"
SESSION_FILE = "scraper/session.json"
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
    "politics": ["council", "MP", "election", "vote", "government", "parliament", "politician", "policy", "minister"],
    "education": ["school", "college", "university", "teacher", "student", "exam", "lesson", "classroom", "headteacher"],
    "sport": ["football", "match", "league", "team", "tournament", "goal", "player", "cup", "rugby", "cricket"],
    "announcements": ["death", "funeral", "obituary", "wedding", "birthday", "celebration", "anniversary", "congratulations", "passed away", "tribute"]
}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==============================
# LOGGING SETUP
# ==============================

os.makedirs("scraper", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()  # Also log to console
    ]
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

def push_to_github():
    """Commit and push articles.json to GitHub"""
    try:
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "add", OUTPUT_FILE], check=True)
        
        # Check if there are changes to commit
        result = subprocess.run(["git", "diff", "--staged", "--quiet"], capture_output=True)
        if result.returncode == 0:
            logging.info("No changes to commit")
            return True
            
        subprocess.run(["git", "commit", "-m", f"Update articles - {datetime.now().strftime('%Y-%m-%d %H:%M')}"], check=True)
        subprocess.run(["git", "push"], check=True)
        
        logging.info("Pushed to GitHub successfully")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Git push failed: {e}")
        return False

async def validate_session(page):
    """Check if Facebook session is still valid"""
    try:
        await page.goto("https://facebook.com", wait_until='domcontentloaded', timeout=15000)
        await page.wait_for_timeout(2000)
        
        # Check for login indicators
        login_selectors = [
            "input[name='email']",
            "input[data-testid='royal_email']", 
            "#email"
        ]
        
        for selector in login_selectors:
            if await page.locator(selector).count() > 0:
                return False
                
        return True
    except Exception as e:
        logging.error(f"Session validation failed: {e}")
        return False

async def fetch_posts(playwright, group_url, area):
    """Scrape posts from a Facebook group with better error handling"""
    browser = None
    results = []
    
    try:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-web-security'
            ]
        )
        
        context = await browser.new_context(
            storage_state=SESSION_FILE,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        
        page = await context.new_page()
        
        # Validate session first
        if not await validate_session(page):
            logging.error(f"Session expired for {area}")
            return []
        
        logging.info(f"Navigating to {group_url}")
        await page.goto(group_url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(5000)
        
        # Multiple selector strategies for Facebook posts
        post_selectors = [
            "[data-pagelet='FeedUnit']",
            "div[role='article']",
            "[data-testid='fbfeed_story']",
            "div[data-testid='story-subtitle']"
        ]
        
        posts = []
        for selector in post_selectors:
            try:
                await page.wait_for_selector(selector, timeout=10000)
                posts = await page.locator(selector).all()
                if len(posts) > 0:
                    logging.info(f"Found {len(posts)} posts using selector: {selector}")
                    break
            except:
                continue
        
        if not posts:
            logging.warning(f"No posts found for {area}")
            return []
        
        # Process first 5 posts to avoid rate limiting
        for idx, post in enumerate(posts[:5]):
            try:
                content = await post.inner_text(timeout=5000)
                
                # Skip very short posts
                if len(content.strip()) < 50:
                    continue
                
                # Try to get post link
                link = None
                try:
                    link_element = post.locator("a").first
                    if await link_element.count() > 0:
                        link = await link_element.get_attribute("href")
                        if link and not link.startswith("http"):
                            link = "https://facebook.com" + link
                except:
                    pass
                
                category = categorise(content)
                
                # Improved GPT prompt
                prompt = f"""Rewrite this local community Facebook post into a professional UK news article.

Requirements:
- Write as a neutral journalist
- Use UK English spelling
- Include relevant context for Rochdale area residents
- Make it factual and concise
- Create an engaging headline
- Keep it under 300 words

Original post:
{content[:1500]}"""  # Limit content to avoid token limits

                # Call OpenAI with better error handling
                try:
                    completion = client.chat.completions.create(
                        model="gpt-4o-mini",  # Make sure this model exists
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
                
                # Extract title from rewritten content
                lines = rewritten.split('\n')
                title = lines[0] if lines else rewritten[:100]
                title = re.sub(r'^#+\s*', '', title)  # Remove markdown headers
                
                # Create article object
                article = {
                    "id": f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{area}-{idx}",
                    "title": title[:150],  # Limit title length
                    "slug": re.sub(r'[^a-z0-9]+', '-', title[:50].lower()).strip("-"),
                    "excerpt": rewritten[:200] + "..." if len(rewritten) > 200 else rewritten,
                    "content_html": f"<p>{rewritten.replace(chr(10), '</p><p>')}</p>",
                    "area": area,
                    "types": [category],
                    "published_at": datetime.utcnow().isoformat() + "Z",
                    "image_url": f"assets/img/placeholder_{category}.jpg",
                    "source_url": link or group_url
                }
                
                results.append(article)
                logging.info(f"Scraped article from {area}: {title[:50]}...")
                
                # Rate limiting between posts
                await asyncio.sleep(2)
                
            except Exception as e:
                logging.error(f"Error processing post {idx} in {area}: {e}")
                continue
    
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
        logging.error(f"Session file {SESSION_FILE} not found")
        return

    if not os.getenv("OPENAI_API_KEY"):
        logging.error("OPENAI_API_KEY environment variable not set")
        return

    logging.info("Starting scrape...")
    all_articles = []

    async with async_playwright() as p:
        for area, url in GROUPS.items():
            logging.info(f"Scraping {area}...")
            posts = await fetch_posts(p, url, area)
            all_articles.extend(posts)
            
            # Delay between groups to avoid detection
            await asyncio.sleep(5)

    if not all_articles:
        logging.warning("No articles scraped")
        return

    # Load existing articles
    existing = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            existing = []

    # Merge new articles
    existing_ids = {a["id"] for a in existing}
    new_articles = [a for a in all_articles if a["id"] not in existing_ids]
    
    if new_articles:
        combined = new_articles + existing
        # Keep only last 100 articles to avoid file getting too large
        combined = combined[:100]
        
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(combined, f, indent=2, ensure_ascii=False)
        
        logging.info(f"Added {len(new_articles)} new articles. Total: {len(combined)}")
        
        # Push to GitHub
        push_to_github()
    else:
        logging.info("No new articles to add")

if __name__ == "__main__":
    asyncio.run(main())
