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
# CONFIG - Updated paths for scraper/ directory
# ==============================

OUTPUT_FILE = "../articles.json"  # Put articles.json in root directory
SESSION_FILE = "session.json"     # Keep in scraper directory
LOG_FILE = "scraper.log"          # Keep in scraper directory

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
    """Commit and push articles.json to GitHub from scraper directory"""
    try:
        # Change to root directory for git operations
        os.chdir("..")
        
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "add", "articles.json"], check=True)
        
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
    finally:
        # Change back to scraper directory
        try:
            os.chdir("scraper")
        except:
            pass

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
        
        posts =
