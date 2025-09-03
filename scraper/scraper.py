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

FB_PROFILE_DIR = "scraper/fb_profile"
SESSION_FILE = "scraper/session.json"

# Facebook sources
FACEBOOK_SOURCES: Dict[str, Dict[str, str]] = {
    "heywood": {"type": "facebook_group","area": "heywood","url": "https://www.facebook.com/groups/heywoodtown"},
    "littleborough": {"type": "facebook_group","area": "littleborough","url": "https://www.facebook.com/groups/779196125547484"},
    "milnrow_newhey": {"type": "facebook_group","area": "milnrow","url": "https://www.facebook.com/groups/446308878886609"},
    "whitworth": {"type": "facebook_group","area": "whitworth","url": "https://www.facebook.com/groups/76137500365"},
    "shawclough_healey": {"type": "facebook_group","area": "shawclough_healey","url": "https://www.facebook.com/groups/shawcloughandhealey"},
    "norden": {"type": "facebook_group","area": "norden","url": "https://www.facebook.com/groups/419623505980244"},
    "kirkholt": {"type": "facebook_group","area": "kirkholt","url": "https://www.facebook.com/groups/230300881463167"},
    "rochdale_group": {"type": "facebook_group","area": "rochdale","url": "https://www.facebook.com/groups/2321259874849245"},
    "rochdaleonline_page": {"type": "facebook_page","area": "rochdale","url": "https://m.facebook.com/rochdaleonline/"},
    "beenetwork_page": {"type": "facebook_page","area": "rochdale","url": "https://m.facebook.com/beenetworkgm/"},
}

# Web sources
WEB_SOURCES: Dict[str, Dict[str, str]] = {
    "men_rochdale": {"type": "website","area": "rochdale","url": "https://www.manchestereveningnews.co.uk/all-about/rochdale"},
    "bing_rochdale": {"type": "website","area": "rochdale","url": "https://www.bing.com/news/search?q=Rochdale&qpvt=rochdale+news&FORM=EWRE"},
}

# RSS sources
RSS_SOURCES: Dict[str, str] = {
    "rochdale_council": "https://www.rochdale.gov.uk/news/rss.xml",
    "gmp_news": "https://www.gmp.police.uk/news/rss.xml",
    "bbc_manchester": "http://feeds.bbci.co.uk/news/england/manchester/rss.xml",
}

# Categories
CATEGORY_KEYWORDS = {
    "crime": ["arrest","police","stabbing","theft","burglary","assault","violence","court","knife","gun","drugs","wanted","jailed"],
    "transport": ["bus","tram","train","traffic","roadworks","closure","accident","transport","highway","m62","m60","bee network","parking","car park"],
    "politics": ["council","mp","election","vote","government","parliament","politician","policy","minister","mayor"],
    "education": ["school","college","university","teacher","student","exam","lesson","classroom","headteacher","ofsted","pupil"],
    "sport": ["football","match","league","team","tournament","goal","player","cup","rugby","cricket"],
    "events": ["festival","concert","match","tournament","fair","market","fundraiser","party","gala","celebration","open day","parade","show","act","live music","gig","performance","game","event"],
    "announcements": ["death","funeral","obituary","wedding","birthday","celebration","anniversary","congratulations","passed away","tribute","memorial"],
}

# Exclusion filters
EXCLUSION_KEYWORDS = [
    "work experience","contributor","free","getting rid of","for let","house to rent","houses to rent","room to let",
    "our company","our business","our colleagues","we visited","we repaired","wanted wednesday","what time","job vacancy","vacancies"
]

# Contempt of Court filter
CONTEMPT_FILTERS = [
    "murderer","killer","rapist","guilty","did it","responsible for",
    "jury heard","ongoing trial","court hearing today","youth court","family court"
]

# Ward detection
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

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

def exclude_post(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in EXCLUSION_KEYWORDS)

def safe_for_publication(text: str) -> bool:
    lower = text.lower()
    return not any(kw in lower for kw in CONTEMPT_FILTERS)

async def rewrite_with_gpt(content: str, area: str, category: str) -> str:
    disclaimer = "\n\n---\n\n"
    disclaimer += "⚠️ Legal Notice: All defendants are presumed innocent unless proven guilty. Rochdale Daily avoids speculation on active cases and reports facts only.\n" if category == "crime" else ""
    disclaimer += "📌 Disclaimer: This article is based on publicly available information at the time of writing and may be updated as more details emerge."
    content = content or ""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a professional UK local news journalist for Rochdale Daily."},
            {"role": "user", "content": (
                f"Rewrite this into a concise UK local news article for {area.title()}.\n"
                f"- Neutral tone, UK spelling.\n"
                f"- 150–250 words.\n"
                f"- Headline on the first line.\n\n"
                f"{content[:4000]}"
            )},
        ],
        max_tokens=800,
        temperature=0.5,
    )
    return resp.choices[0].message.content.strip() + disclaimer

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
