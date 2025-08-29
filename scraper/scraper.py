import os
import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright
import openai

# Load OpenAI API key from environment (set in GitHub Actions)
openai.api_key = os.getenv("OPENAI_API_KEY")

ARTICLES_FILE = "articles.json"

GROUPS = {
    "Heywood": "https://www.facebook.com/groups/2609224899302465",
    # 👉 add more groups here (Littleborough, Milnrow, Rochdale, etc.)
}

def load_cookies():
    with open("scraper/fb_cookies.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_articles():
    if os.path.exists(ARTICLES_FILE):
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_articles(articles):
    with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

def rewrite_with_gpt(content, area):
    """Send raw FB post to GPT to create a structured news article"""
    prompt = f"""
    Rewrite this Facebook post into a short local news article.
    - Area: {area}
    - Write in clear, neutral, professional newspaper tone.
    - Include a title, short excerpt, full HTML body, and if possible pull out 1–2 short quotes.
    - Suggest categories (crime, politics, education, announcements, appeals).
    Post:
    {content}
    """

    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600
    )

    return response.choices[0].message.content

def scrape_group(area, url):
    cookies = load_cookies()
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto(url)

        page.wait_for_selector("div[role='feed']", timeout=15000)
        page.mouse.wheel(0, 6000)
        page.wait_for_timeout(6000)

        posts = page.query_selector_all("div[role='feed'] > div")

        for post in posts[:5]:  # limit to top 5 for now
            try:
                text = post.inner_text().strip()
                if text:
                    results.append(text)
            except:
                continue

        browser.close()

    return results

def main():
    print("🚀 Starting scraper...")

    articles = load_articles()

    for area, url in GROUPS.items():
        print(f"Scraping {area}...")
        posts = scrape_group(area, url)

        for post in posts:
            # Rewrite with GPT
            rewritten = rewrite_with_gpt(post, area)

            # Minimal parse (GPT gives us structured text we can regex parse)
            title_match = re.search(r'Title:\s*(.*)', rewritten)
            excerpt_match = re.search(r_

