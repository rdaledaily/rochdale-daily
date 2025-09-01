import os
import json
import re
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
from openai import OpenAI

# ==============================
# CONFIG
# ==============================

OUTPUT_FILE = "articles.json"
SESSION_FILE = "scraper/session.json"

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
    await page.wait_for_timeout(5000)  # wait for posts to load

    posts = await page.locator("div[role='article']").all()
    results = []

    for idx, post in enumerate(posts[:3]):  # limit per group for testing
        try:
            content = await post.inner_text()
            link = await post.locator("a").first.get_attribute("href")

            # Categorise
            category = categorise(content)

            # Rewrite with GPT
            prompt = f"""Rewrite this Facebook post into a sho
