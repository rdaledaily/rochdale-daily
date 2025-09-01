import os, json, re
from datetime import datetime
from playwright.sync_api import sync_playwright
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")

ARTICLES_FILE = "articles.json"

GROUPS = {
    "Heywood": "https://www.facebook.com/groups/2609224899302465",
    "Littleborough": "https://www.facebook.com/groups/779196125547484",
    "Kirkholt": "https://www.facebook.com/groups/230300881463167",
    "Norden": "https://www.facebook.com/groups/419623505980244",
    "Whitworth": "https://www.facebook.com/groups/76137500365",
    "Rochdale": "https://www.facebook.com/groups/2321259874849245"
}

CATEGORIES = ["Crime", "Politics", "Education", "Sport", "Announcements"]

BREAKING_KEYWORDS = [
    "murder", "stabbing", "shooting", "fire", "explosion",
    "crash", "collision", "road closed", "police incident",
    "arrested", "missing", "evacuated", "lockdown"
]

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

        for _ in range(3):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(2500)

        posts = page.query_selector_all("div[role='feed'] > div")

        for post in posts[:5]:
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
        print(f"📍 Scraping {area}...")
        posts = scrape_group(area, url)

        for post in posts:
            rewritten = rewrite_with_gpt(post, area)

            # ✅ Regex extractions (now fixed)
            title_match = re.search(r'Title:\s*(.*)', rewritten)
            excerpt_match = re.search(r'Excerpt:\s*(.*)', rewritten)
            body_match = re.search(r'(?:Content|Body):\s*(.*)', rewritten, re.S)
            category_match = re.findall(r'(Crime|Politics|Education|Sport|Announcements)', rewritten, re.I)
            breaking_match = re.search(r'Breaking:\s*(Yes|No)', rewritten, re.I)
            quotes = re.findall(r'“([^”]+)”', rewritten)

            title = title_match.group(1).strip() if title_match else post[:60]
            excerpt = excerpt_match.group(1).strip() if excerpt_match else post[:140]
            content_html = f"<p>{body_match.group(1).strip()}</p>" if body_match else f"<p>{post}</p>"
            categories = [c.capitalize() for c in category_match if c.capitalize() in CATEGORIES] or ["Announcements"]

            gpt_breaking = breaking_match and breaking_match.group(1).lower() == "yes"
            is_breaking = breaking_detect(post, gpt_breaking)

            slug = slugify(title)

            article = {
                "id": datetime.utcnow().strftime("%Y%m%d%H%M%S") + "-" + slug[:30],
                "title": title,
                "slug": slug,
                "excerpt": excerpt,
                "content_html": content_html,
                "area": area,
                "types": categories,
                "published_at": datetime.utcnow().isoformat() + "Z",
                "image_url": "assets/img/breaking.jpg" if is_breaking else None,
                "image_alt": "Breaking news" if is_breaking else None,
                "source_url": url,
                "quotes": quotes[:2],
                "breaking": is_breaking
            }

            if not any(a["title"] == article["title"] for a in articles):
                articles.append(article)
                print(f"✅ Added: {title} → {categories} → {area} → Breaking={is_breaking}")

    save_articles(articles)
    print("🎉 Scraping complete!")

if __name__ == "__main__":
    main()
