import os
import re
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Tuple

import feedparser
from playwright.async_api import async_playwright, BrowserContext, Page
from openai import OpenAI

# ==============================
# CONFIG
# ==============================

OUTPUT_FILE = "articles.json"
LOG_FILE = "scraper/scraper.log"

# Prefer persistent FB profile; fall back to storage_state cookies if needed
FB_PROFILE_DIR = "scraper/fb_profile"
SESSION_FILE = "scraper/session.json"

# ---------------- Facebook sources ----------------
# name -> {type, area, url}
FACEBOOK_SOURCES: Dict[str, Dict[str, str]] = {
    # Groups (wards)
    "heywood": {
        "type": "facebook_group",
        "area": "heywood",
        "url": "https://www.facebook.com/groups/heywoodtown",
    },
    "littleborough": {
        "type": "facebook_group",
        "area": "littleborough",
        "url": "https://www.facebook.com/groups/779196125547484",
    },
    "milnrow_newhey": {
        "type": "facebook_group",
        "area": "milnrow",
        "url": "https://www.facebook.com/groups/446308878886609",
    },
    "whitworth": {
        "type": "facebook_group",
        "area": "whitworth",
        "url": "https://www.facebook.com/groups/76137500365",
    },
    "shawclough_healey": {
        "type": "facebook_group",
        "area": "shawclough_healey",
        "url": "https://www.facebook.com/groups/shawcloughandhealey",
    },
    "norden": {
        "type": "facebook_group",
        "area": "norden",
        "url": "https://www.facebook.com/groups/419623505980244",
    },
    "kirkholt": {
        "type": "facebook_group",
        "area": "kirkholt",
        "url": "https://www.facebook.com/groups/230300881463167",
    },
    "rochdale_group": {
        "type": "facebook_group",
        "area": "rochdale",
        "url": "https://www.facebook.com/groups/2321259874849245",
    },

    # Pages
    "rochdaleonline_page": {
        "type": "facebook_page",
        "area": "rochdale",
        "url": "https://m.facebook.com/rochdaleonline/",
    },
    "beenetwork_page": {
        "type": "facebook_page",
        "area": "rochdale",
        "url": "https://m.facebook.com/beenetworkgm/",
    },
}

# ---------------- Website sources (MEN/Bing) ----------------
WEB_SOURCES: Dict[str, Dict[str, str]] = {
    "men_rochdale": {
        "type": "website",
        "area": "rochdale",
        "url": "https://www.manchestereveningnews.co.uk/all-about/rochdale",
    },
    "bing_rochdale": {
        "type": "website",
        "area": "rochdale",
        "url": "https://www.bing.com/news/search?q=Rochdale&qpvt=rochdale+news&FORM=EWRE",
    },
}

# ---------------- RSS sources ----------------
RSS_SOURCES: Dict[str, str] = {
    "rochdale_council": "https://www.rochdale.gov.uk/news/rss.xml",
    "gmp_news": "https://www.gmp.police.uk/news/rss.xml",
    "bbc_manchester": "http://feeds.bbci.co.uk/news/england/manchester/rss.xml",
}

# ---------------- Categories & ward detection ----------------
CATEGORY_KEYWORDS = {
    "crime": [
        "arrest","police","stabbing","theft","burglary","assault",
        "violence","court","knife","gun","drugs","wanted","jailed"
    ],
    "transport": [
        "bus","tram","train","traffic","roadworks","closure","accident",
        "transport","highway","m62","m60","bee network","parking","car park"
    ],
    "politics": [
        "council","mp","election","vote","government","parliament",
        "politician","policy","minister","mayor"
    ],
    "education": [
        "school","college","university","teacher","student","exam",
        "lesson","classroom","headteacher","ofsted","pupil"
    ],
    "sport": [
        "football","match","league","team","tournament","goal","player","cup","rugby","cricket"
    ],
    "events": [
        "festival","concert","match","tournament","fair","market",
        "fundraiser","party","gala","celebration","open day","parade",
        "show","act","live music","gig","performance","game","event"
    ],
    "announcements": [
        "death","funeral","obituary","wedding","birthday","celebration",
        "anniversary","congratulations","passed away","tribute","memorial"
    ],
}

WARD_KEYWORDS = {
    "heywood": ["heywood"],
    "littleborough": ["littleborough"],
    "milnrow": ["milnrow","newhey"],
    "rochdale": ["rochdale","town centre","rochdale town"],
    "shawclough_healey": ["shawclough","healey"],
    "whitworth": ["whitworth"],
    "norden": ["norden","bamford","caldershaw","cutgate"],
    "kirkholt": ["kirkholt"],
}

# --- OpenAI client ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)

# ==============================
# HELPERS
# ==============================

def normalise_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

def categorise(text: str) -> str:
    t = (text or "").lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return cat
    return "announcements"

def detect_area(text: str, fallback: str = "rochdale") -> str:
    t = (text or "").lower()
    for area, kws in WARD_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return area
    return fallback

async def rewrite_with_gpt(content: str, area: str) -> str:
    """Rewrite into a concise, neutral UK local news piece with retries."""
    content = content or ""
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a professional UK local news journalist for Rochdale Daily."},
                    {"role": "user", "content": (
                        f"Rewrite the following into a concise, factual UK local news article for {area.title()}.\n"
                        f"- Neutral tone, UK spelling, 150–250 words.\n"
                        f"- Start with an informative headline on the first line.\n\n"
                        f"{content[:4000]}"
                    )},
                ],
                max_tokens=800,
                temperature=0.5,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logging.warning(f"OpenAI retry {attempt+1}/3 failed: {e}")
            await asyncio.sleep(1.5 * (attempt + 1))
    return content[:600]  # fallback

def make_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower().strip())[:60].strip("-")

def build_article(area: str, category: str, rewritten: str, source_url: str, id_suffix: str) -> Dict:
    lines = [l for l in (rewritten or "").split("\n") if l.strip()]
    title = re.sub(r"^#+\s*", "", lines[0])[:150] if lines else "Update"
    body_lines = lines[1:] if len(lines) > 1 else lines
    html = "<p>" + "</p><p>".join([normalise_ws(l) for l in body_lines]) + "</p>"
    return {
        "id": f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{area}-{id_suffix}",
        "title": title,
        "slug": make_slug(title),
        "excerpt": normalise_ws(" ".join(body_lines))[:200],
        "content_html": html,
        "area": area,
        "types": [category],
        "published_at": datetime.utcnow().isoformat() + "Z",
        "image_url": f"assets/img/placeholder_{category}.jpg",
        "source_url": source_url,
    }

# ==============================
# FACEBOOK (persistent login or session.json)
# ==============================

async def open_fb_context(pw) -> Tuple[BrowserContext, Page]:
    """Prefer persistent profile; fall back to storage_state cookies."""
    if os.path.isdir(FB_PROFILE_DIR) and any(os.scandir(FB_PROFILE_DIR)):
        ctx = await pw.chromium.launch_persistent_context(
            FB_PROFILE_DIR,
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/123.0.0.0 Safari/537.36"),
        )
        return ctx, await ctx.new_page()

    if not os.path.exists(SESSION_FILE):
        raise FileNotFoundError(
            "Facebook auth missing. Either use a persistent profile at "
            f"'{FB_PROFILE_DIR}' (recommended) or create cookies JSON with:\n"
            f"python -m playwright codegen https://facebook.com --save-storage={SESSION_FILE}"
        )

    browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = await browser.new_context(
        storage_state=SESSION_FILE,
        viewport={"width": 1280, "height": 900},
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"),
    )
    return ctx, await ctx.new_page()

async def fb_session_valid(page: Page) -> bool:
    """Check on m.facebook.com; detect login UI or checkpoint."""
    try:
        await page.goto("https://m.facebook.com/", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(1200)
        if await page.locator("input[name='email']").count() > 0:
            return False
        if await page.get_by_role("button", name=re.compile("log in", re.I)).count() > 0:
            return False
        if "checkpoint" in page.url or "/login" in page.url:
            return False
        return True
    except Exception as e:
        logging.warning(f"FB session validation error: {e}")
        return False  # be conservative

async def scrape_facebook_source(pw, name: str, meta: Dict) -> List[Dict]:
    results: List[Dict] = []
    area_default = meta["area"]
    url = meta["url"]

    ctx, page = await open_fb_context(pw)
    try:
        if not await fb_session_valid(page):
            logging.error(
                "❌ Facebook session expired.\n"
                "Use a persistent profile (recommended) or refresh cookies:\n"
                f"  1) Persistent: login once locally; Playwright will save to '{FB_PROFILE_DIR}'.\n"
                f"  2) Cookies: python -m playwright codegen https://facebook.com --save-storage={SESSION_FILE}\n"
            )
            return results

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        for _ in range(2):
            await page.mouse.wheel(0, 1800)
            await page.wait_for_timeout(1000)

        cards = await page.locator("div[role='article']").all()
        if not cards:
            logging.warning(f"⚠️ No posts found for {name} ({url})")
            return results

        for idx, card in enumerate(cards[:5]):
            try:
                content = await card.inner_text(timeout=4000)
                content = normalise_ws(content)
                if len(content) < 60:
                    continue

                # Refine area by ward mentions if present
                area_detected = detect_area(content, fallback=area_default)
                cat = categorise(content)

                rewritten = await rewrite_with_gpt(content, area_detected)
                await asyncio.sleep(0.25)

                article = build_article(
                    area_detected, cat, rewritten, url,
                    id_suffix=f"fb-{name}-{idx}"
                )
                results.append(article)
            except Exception as e:
                logging.warning(f"FB post parse error ({name} #{idx}): {e}")
                continue
    finally:
        await ctx.close()
    return results

# ==============================
# WEBSITE SCRAPING (MEN, Bing)
# ==============================

async def extract_article_from_link(pw, link: str) -> Tuple[str, str]:
    """Open a link and try to pull <h1> + first paragraphs."""
    browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
    page = await browser.new_page()
    title, body = "", ""
    try:
        await page.goto(link, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(800)

        # Headline candidates
        for sel in ["h1", "header h1", "article h1", "[itemprop='headline']"]:
            if await page.locator(sel).count() > 0:
                title = (await page.locator(sel).first.text_content()) or ""
                title = normalise_ws(title)
                if title:
                    break

        # Paragraph candidates
        paras = []
        for sel in ["article p", "main p", "div[itemprop='articleBody'] p", "p"]:
            nodes = await page.locator(sel).all()
            if nodes:
                for n in nodes[:18]:
                    txt = await n.text_content()
                    txt = normalise_ws(txt)
                    if txt and len(txt) > 30:
                        paras.append(txt)
                if paras:
                    break

        body = "\n".join(paras[:12])
    except Exception as e:
        logging.debug(f"Link extract failed ({link}): {e}")
    finally:
        await browser.close()
    return title, body

async def scrape_web_source(pw, name: str, meta: Dict) -> List[Dict]:
    results: List[Dict] = []
    area_default = meta.get("area", "rochdale")
    url = meta["url"]

    browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1200)

        # Gather anchors
        link_elements = await page.locator("a").all()
        link_elements = link_elements[:120]  # cap for performance

        texts: List[str] = []
        hrefs: List[str] = []
        for el in link_elements:
            texts.append(normalise_ws(await el.text_content()))
            hrefs.append(await el.get_attribute("href"))

        candidates = []
        for t, h in zip(texts, hrefs):
            if not t or not h:
                continue
            if not h.startswith("http"):
                continue
            if "facebook.com" in h:
                continue
            candidates.append((t, h))

        # Prefer anchor text mentioning Rochdale or wards
        def mentions_area(text: str) -> bool:
            tl = text.lower()
            if "rochdale" in tl:
                return True
            for kws in WARD_KEYWORDS.values():
                if any(kw in tl for kw in kws):
                    return True
            return False

        preferred = [(t, h) for (t, h) in candidates if mentions_area(t)]
        if not preferred:
            preferred = candidates

        # Dedupe by href and limit
        seen = set()
        unique = []
        for t, h in preferred:
            if h in seen:
                continue
            seen.add(h)
            unique.append((t, h))
        unique = unique[:8]

        # Visit each article to get real content
        for idx, (anchor_text, link) in enumerate(unique):
            try:
                title_page, body_page = await extract_article_from_link(pw, link)
                base_text = f"{title_page or anchor_text}\n\n{body_page}".strip()
                if len(base_text) < 80:
                    continue

                area_detected = detect_area(base_text, fallback=area_default)
                cat = categorise(base_text)
                rewritten = await rewrite_with_gpt(base_text, area_detected)
                await asyncio.sleep(0.2)

                article = build_article(
                    area_detected, cat, rewritten, link,
                    id_suffix=f"web-{name}-{idx}"
                )
                results.append(article)
            except Exception as e:
                logging.warning(f"Web article parse error ({name}): {e}")
                continue
    except Exception as e:
        logging.error(f"Website scrape error [{name} {url}]: {e}")
    finally:
        await browser.close()

    return results

# ==============================
# RSS (async wrapper)
# ==============================

async def scrape_rss_sources() -> List[Dict]:
    results: List[Dict] = []
    for name, feed_url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(feed_url)
            for idx, entry in enumerate(feed.entries[:8]):
                title = entry.get("title", "").strip()
                summary = normalise_ws(entry.get("summary", "") or entry.get("description", ""))
                link = entry.get("link", feed_url)
                text = f"{title}\n\n{summary}".strip()

                area_detected = detect_area(text, fallback="rochdale")
                cat = categorise(text)
                rewritten = await rewrite_with_gpt(text, area_detected)
                await asyncio.sleep(0.15)

                article = build_article(
                    area_detected, cat, rewritten, link,
                    id_suffix=f"rss-{name}-{idx}"
                )
                results.append(article)
        except Exception as e:
            logging.error(f"RSS parse error [{name}]: {e}")
    return results

# ==============================
# MAIN
# ==============================

async def main():
    if not os.getenv("OPENAI_API_KEY"):
        logging.error("❌ OPENAI_API_KEY not set.")
        return

    logging.info("🚀 Starting scrape...")
    all_articles: List[Dict] = []

    async with async_playwright() as pw:
        # FACEBOOK
        for name, meta in FACEBOOK_SOURCES.items():
            logging.info(f"📘 FB: {name} → {meta['url']}")
            fb_articles = await scrape_facebook_source(pw, name, meta)
            all_articles.extend(fb_articles)
            await asyncio.sleep(0.5)

        # WEBSITES (MEN + Bing)
        for name, meta in WEB_SOURCES.items():
            logging.info(f"🌐 Web: {name} → {meta['url']}")
            web_articles = await scrape_web_source(pw, name, meta)
            all_articles.extend(web_articles)
            await asyncio.sleep(0.4)

    # RSS
    logging.info("📰 RSS: fetching feeds…")
    rss_articles = await scrape_rss_sources()
    all_articles.extend(rss_articles)

    if not all_articles:
        logging.warning("⚠️ No new articles scraped.")
        return

    # Load existing
    existing: List[Dict] = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception as e:
            logging.warning(f"Could not read existing {OUTPUT_FILE}: {e}")

    # Dedup by (slug or source_url) + area
    def dedup_key(a: Dict) -> Tuple[str, str]:
        slug = a.get("slug") or ""
        src = a.get("source_url") or ""
        area = a.get("area") or ""
        return (slug or src, area)

    seen = {dedup_key(a) for a in existing}
    fresh: List[Dict] = []
    for a in all_articles:
        k = dedup_key(a)
        if k in seen:
            continue
        seen.add(k)
        fresh.append(a)

    combined = fresh + existing
    # Atomic write
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(combined[:100], f, indent=2, ensure_ascii=False)
    os.replace(tmp, OUTPUT_FILE)

    logging.info(f"✅ Added {len(fresh)} new articles. Total stored: {min(len(combined), 100)}")

if __name__ == "__main__":
    asyncio.run(main())
