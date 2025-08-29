from playwright.sync_api import sync_playwright
import json, time, re, hashlib, os
from datetime import datetime
import openai

# Load secrets
openai.api_key = os.getenv("OPENAI_API_KEY")  # Add this in GitHub Secrets

# --- Utilities ---
def load_cookies():
    with open("scraper/fb_cookies.json", "r", encoding="utf-8") as f:
        return json.load(f)

def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

def gen_id(title):
    date = datetime.utcnow().strftime("%Y%m%d")
    h = hashlib.sha1(title.encode("utf-8")).hexdigest()[:6]
    return f"{date}-{h}"

# --- AI Processing ---
def rewrite_with_gpt(raw_text):
    prompt = f"""
    Rewrite the following Facebook post into a short local news article.
    Extract: title, excerpt, area (Heywood/Milnrow/Rochdale/Littleborough), category (crime, politics, education, announcements, appeals, community), main body (HTML safe), and 1–2 short quotes if present.

    Post:
    {raw_text}
    """

    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "You are a local news editor."},
                  {"role": "user", "content": prompt}],
        temperature=0.3
    )

    return resp["choices"][0]["message"]["content"]

# --- Scraper ---
def scrape_group(group_url, group_name="General"):
    cookies = load_cookies()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto(group_url, timeout=60000)

        page.wait_for_selector("div[role='feed']", timeout=20000)
        for _ in range(3):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(4000)

        posts = page.query_selector_all("div[role='feed'] > div")
        results = []

        for post in posts[:10]:  # limit to 10 per run
            try:
                raw_text = post.inner_text().strip()
                if not raw_text or len(raw_text) < 40:
                    continue

                gpt_output = rewrite_with_gpt(raw_text)

                # crude parsing from GPT structured output
                # assume JSON-like blocks
                try:
                    article = json.loads(gpt_output)
                except:
                    # fallback: wrap whole text
                    article = {
                        "title": raw_text[:60],
                        "excerpt": raw_text[:140],
                        "content_html": f"<p>{raw_text}</p>",
                        "area": group_name,
                        "types": ["community"],
                        "quotes": []
                    }

                # add required fields
                article["id"] = gen_id(article["title"])
                article["slug"] = slugify(article["title"])
                article["published_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                article["image_url"] = f"assets/img/{article['slug']}.jpg"  # placeholder
                article["source_url"] = group_url
                article["breaking"] = False if "breaking" not in article else article["breaking"]

                results.append(article)
            except Exception as e:
                print("Error:", e)
                continue

        browser.close()
        return results

# --- Save JSON ---
def save_to_json(all_posts, filename="articles.json"):
    # Load existing if present
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except:
                existing = []
    else:
        existing = []

    # merge new with existing (avoid duplicates by id)
    existing_ids = {p["id"] for p in existing}
    merged = existing + [p for p in all_posts if p["id"] not in existing_ids]

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

def main():
    group_urls = {
        "Heywood": "https://www.facebook.com/groups/2609224899302465",
        # add more here
    }

    all_posts = []
    for name, url in group_urls.items():
        print(f"Scraping {name}...")
        posts = scrape_group(url, group_name=name)
        all_posts.extend(posts)

    save_to_json(all_posts, filename="articles.json")

if __name__ == "__main__":
    main()
