import os
import json
import re
import asyncio
import subprocess
from datetime import datetime
import logging
from playwright.async_api import async_playwright
from openai import OpenAI

# ... (keep your existing config) ...

async def main():
    # Check if session exists, create if not
    if not os.path.exists(SESSION_FILE):
        print("No session found. Please create one first.")
        async with async_playwright() as p:
            await create_session(p)
        return

    logging.info("🚀 Starting scrape...")
    all_articles = []

    async with async_playwright() as p:
        for area, url in GROUPS.items():
            logging.info(f"📌 Scraping {area}...")
            posts = await fetch_posts(p, url, area)
            all_articles.extend(posts)
            
            # Add delay between groups to avoid rate limiting
            await asyncio.sleep(2)

    if all_articles:
        # Save articles
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

        logging.info(f"✅ Added {len(new_articles)} new articles")
        
        # Push to GitHub
        if new_articles:
            push_to_github()
    else:
        logging.warning("⚠️ No articles scraped")

if __name__ == "__main__":
    asyncio.run(main())
