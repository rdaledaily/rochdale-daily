import os, json, re
from datetime import datetime
from playwright.sync_api import sync_playwright
import openai

# Load OpenAI API key from GitHub Secrets
openai.api_key = os.getenv("OPENAI_API_KEY")

ARTICLES_FILE = "articles.json"

# Facebook groups to scrape
GROUPS = {
    "Heywood": "https://www.facebook.com/groups/2609224899302465",
    "Littleborough": "https://www.facebook.com/groups/779196125547484",
    "Kirkholt": "https://www.facebook.com/groups/230300881463167",
    "Norden": "https://www.facebook.com/groups/419623505980244",
    "Whitworth": "https://www.facebook.com/groups/76137500365",
    "Rochdale": "https://www.facebook.com/groups/2321259874849245"
}

# Allowed categories
CATEGORIES = ["Crime", "Politics", "Education", "Sport", "Announcements"]

# Keywords that force "Breaking News"
BREAKING_KEYWORDS = [
    "murder", "stabbing", "shooting", "fire", "explosion",
    "crash", "collision", "road closed", "police incident",
    "arrested", "missing", "evacuated", "lockdown"
]

# -----------------------------
# Helpers
# -----------------------------

def load_cookies():
    with open("scraper/fb_cookies.json", "r", encoding="utf-8") as f:
        return json.load(f)

def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

def load_articles():
    if os.path.exists(ARTICLES_FILE):
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print("⚠️ articles.json corrupted, starting fresh")
                return []
    return []

def save_articles(new_articles):
    articles = load_articles()
    articles.extend(new_articles)

    # Deduplicate by ID
    seen = set()
    unique_articles = []
    for a in articles:
        if a["id"] not in seen:
            unique_articles.append(a)
            seen.add(a["id"])

    with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(unique_articles, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved {len(new_articles)} new articles, {len(unique_articles)} total in articles.json")

def rewrite_with_gpt(content, area):
    prompt = f"""
    Rewrite this Facebook post into a short **local news article**.

    Requirements:
    - Location: {area}
    - Title: ≤70 chars, include area keyword
    - Excerpt: 140–160 chars (SEO meta description)
    - Content: structured HTML (<h2>, <p>, <ul>)
    - Quotes: 1–2 short direct quotes if possible
    - Classify into ONE OR MORE of these categories ONLY: {", ".join(CATEGORIES)}
    - If unsure, default to Announcements
    - Indicate clearly: Breaking: Yes or Breaking: No
    
    Post:
    {content}
    """

    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=900
    )
    return response.choices[0].message.content

def breaking_detect(text, gpt_flag):
    """Decide breaking news status from GPT + keyword triggers"""
    if gpt_flag:
        return True
    text_lower = text.lower()
    if any(word in text_lower for word in BREAKING_KEYWORDS):
        return True
    return False

# -----------------------------
# Scraping
# -----------------------------

def scrape_group(area, url):
    cookies = load_cookies()
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto(url)
        page.wait_for_selector("div[role='feed']", timeout=20000)

        # Scroll a bit to load posts
        for _ in range(3):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(2500)

        posts = page.query_selector_all("div[role='feed'] > div")

        for post in posts[:5]:  # limit for efficiency
            try:
                text = post.inner_text().strip()
                if text:
                    results.append(text)
