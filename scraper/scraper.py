#!/usr/bin/env python3
"""
Rochdale Daily autonomous local-news pipeline.

The pipeline:
- checks public RSS feeds, public news pages and Google News RSS searches
  every scheduled run;
- searches the borough, townships, wards and named neighbourhoods;
- keeps the original source date and rejects stale or undated material;
- cross-references similar reports before asking OpenAI for an original article;
- automatically anonymises crime, court, safeguarding and allegation stories;
- removes names of suspects/defendants, exact residential addresses, postcodes,
  victim-identifying information and details that may prejudice proceedings;
- publishes suitable sensitive stories instead of placing them in a review queue;
- adds a legal/editorial note and a standing right-to-reply invitation;
- uses locally stored category artwork by default, avoiding unlicensed image reuse.

This is a technical risk-control system, not a substitute for qualified media-law
advice. A disclaimer cannot make unlawful content lawful, so items that remain
unsafe or too thin after redaction are skipped rather than published.
"""

from __future__ import annotations

import hashlib
import io
import html
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from PIL import Image, ImageOps, UnidentifiedImageError
from dateparser.search import search_dates
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "articles.json"
LOG_FILE = ROOT / "scraper" / "scraper.log"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_NEWS_AGE_HOURS = int(os.getenv("MAX_NEWS_AGE_HOURS", "168"))
RETENTION_DAYS = int(os.getenv("ARTICLE_RETENTION_DAYS", "14"))
MAX_PUBLISHED_ARTICLES = int(os.getenv("MAX_PUBLISHED_ARTICLES", "100"))
MAX_AI_ARTICLES_PER_RUN = int(os.getenv("MAX_AI_ARTICLES_PER_RUN", "30"))
MAX_AI_ARTICLES_INITIAL = int(os.getenv("MAX_AI_ARTICLES_INITIAL", "60"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12"))
DISCOVERY_LINKS_PER_SOURCE = int(os.getenv("DISCOVERY_LINKS_PER_SOURCE", "40"))
RSS_ITEMS_PER_SOURCE = int(os.getenv("RSS_ITEMS_PER_SOURCE", "100"))
DISCOVERY_PAGE_LIMIT = int(os.getenv("DISCOVERY_PAGE_LIMIT", "3"))
DISCOVERY_WORKERS = int(os.getenv("DISCOVERY_WORKERS", "16"))
AI_WORKERS = int(os.getenv("AI_WORKERS", "6"))
MIN_LIVE_STORIES = int(os.getenv("MIN_LIVE_STORIES", "30"))
STATUS_FILE = ROOT / "scraper_status.json"
GENERATED_IMAGE_DIR = ROOT / "assets" / "img" / "generated"
GENERATED_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
RESPECT_ROBOTS = os.getenv("RESPECT_ROBOTS", "true").lower() not in {"0", "false", "no"}
USE_SOURCE_IMAGES = os.getenv("USE_SOURCE_IMAGES", "false").lower() in {"1", "true", "yes"}
RIGHT_TO_REPLY_EMAIL = os.getenv("RIGHT_TO_REPLY_EMAIL", "news@rochdaledaily.co.uk")
UK_TZ = ZoneInfo("Europe/London")
SAME_DAY_ONLY = os.getenv("SAME_DAY_ONLY", "true").lower() not in {"0", "false", "no"}

SOURCE_DENY_DOMAINS = {"rochdaletimes.co.uk", "rochdaleonline.co.uk"}
SOURCE_DENY_NAMES = {"rochdale times", "rochdale times paper", "rochdale online"}

LIVE_SOURCE_NAMES = {
    "rochdale council service updates",
    "tfgm travel alerts",
    "northern service updates",
    "united utilities incidents",
    "environment agency flood-monitoring api",
}

FACEBOOK_EVENTS_DISCOVERY_URL = os.getenv(
    "FACEBOOK_EVENTS_DISCOVERY_URL",
    "https://www.facebook.com/events/?date_filter_option=ANY_DATE&discover_tab=CUSTOM&location_id=108023932551149",
).strip()
FACEBOOK_EVENTS_MAX = int(os.getenv("FACEBOOK_EVENTS_MAX", "18"))
FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS = int(
    os.getenv("FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS", "30000")
)
FACEBOOK_EVENT_IMAGE_REUSE = os.getenv(
    "FACEBOOK_EVENT_IMAGE_REUSE", "false"
).lower() in {"1", "true", "yes"}

IMAGE_REUSE_SOURCE_DOMAINS = {
    item.strip().lower()
    for item in os.getenv(
        "IMAGE_REUSE_SOURCE_DOMAINS",
        "rochdale.gov.uk,gmp.police.uk,manchesterfire.gov.uk,rochdaleafc.co.uk,"
        "rochdalehornets.co.uk,tfgm.com,gmca.gov.uk,nationalhighways.co.uk,"
        "hopwood.ac.uk,northerncarealliance.nhs.uk,penninecare.nhs.uk,"
        "rochvalleyradio.com,actiontogether.org.uk,yourtrustrochdale.co.uk,"
        "facebook.com",
    ).split(",")
    if item.strip()
}

RSS_SOURCES = [
    {"name": "Rochdale Borough Council", "url": "https://www.rochdale.gov.uk/news/rss.xml", "default_area": "rochdale"},
    {"name": "Greater Manchester Police", "url": "https://www.gmp.police.uk/news/rss.xml", "default_area": "rochdale"},
    {"name": "BBC Manchester", "url": "https://feeds.bbci.co.uk/news/england/manchester/rss.xml", "default_area": "rochdale"},
    {"name": "Greater Manchester Fire and Rescue Service", "url": "https://www.manchesterfire.gov.uk/news-events/news/feed/", "default_area": "rochdale"},
    {"name": "Rochdale AFC", "url": "https://www.rochdaleafc.co.uk/news/feed", "default_area": "rochdale"},
]

DISCOVERY_PAGES = [
    # Rochdale Borough Council, democracy, planning, consultations and events
    {"name": "Rochdale Borough Council News", "url": "https://www.rochdale.gov.uk/news", "default_area": "rochdale", "link_pattern": r"/news/article/"},
    {"name": "Rochdale Council Your News", "url": "https://www.rochdale.gov.uk/yournews", "default_area": "rochdale", "link_pattern": r"/news/|/directory-record/|/events/"},
    {"name": "Rochdale Council Service Updates", "url": "https://www.rochdale.gov.uk/serviceupdates", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Rochdale Council Events", "url": "https://www.rochdale.gov.uk/events", "default_area": "rochdale", "link_pattern": r"/events/event/"},
    {"name": "Rochdale Council Your Events", "url": "https://www.rochdale.gov.uk/yourevents", "default_area": "rochdale", "link_pattern": r"/events/|/directory-record/"},
    {"name": "Rochdale Council Consultations", "url": "https://consultations.rochdale.gov.uk/consultation_finder/?advanced=1", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Rochdale Council Committees", "url": "https://democracy.rochdale.gov.uk/mgCalendarMonthView.aspx?GL=1&bcr=1", "default_area": "rochdale", "link_pattern": r"mgMeetingAttendance|ieListDocuments|mgCommitteeDetails"},
    {"name": "Rochdale Planning Applications", "url": "https://www.rochdale.gov.uk/planningapplications", "default_area": "rochdale", "link_pattern": r"planning|application|publicaccess"},
    {"name": "Rochdale Development Agency", "url": "https://investinrochdale.co.uk/news", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Visit Rochdale", "url": "https://www.visitrochdale.com/whats-on", "default_area": "rochdale", "link_pattern": r"/whats-on/"},
    {"name": "Rochdale Town Hall Events", "url": "https://www.rochdaletownhall.co.uk/events?page=1", "default_area": "rochdale", "link_pattern": r"/events/event/"},

    # Community, culture and voluntary-sector sources
    {"name": "Action Together Rochdale News", "url": "https://www.actiontogether.org.uk/rochdale-news", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Action Together Latest News", "url": "https://www.actiontogether.org.uk/whats-happening", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Your Trust Rochdale News", "url": "https://www.yourtrustrochdale.co.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/|/category/news/"},
    {"name": "Your Trust Rochdale News Archive", "url": "https://www.yourtrustrochdale.co.uk/category/news/", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Roch Valley Radio Local News", "url": "https://www.rochvalleyradio.com/news/local-news/", "default_area": "rochdale", "link_pattern": r"/news/local-news/"},
    {"name": "Roch Valley Radio Notices", "url": "https://www.rochvalleyradio.com/news/notices/", "default_area": "rochdale", "link_pattern": r"/news/notices/|/news/local-news/"},

    # Emergency, transport, utility and public-service sources
    {"name": "Greater Manchester Police", "url": "https://www.gmp.police.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Greater Manchester Fire and Rescue Service", "url": "https://www.manchesterfire.gov.uk/news-events/news/", "default_area": "rochdale", "link_pattern": r"/news"},
    {"name": "TfGM Newsroom", "url": "https://news.tfgm.com/", "default_area": "rochdale", "link_pattern": r"/press-releases/"},
    {"name": "TfGM Travel Alerts", "url": "https://tfgm.com/travel-updates/travel-alerts", "default_area": "rochdale", "link_pattern": r"/travel-updates/"},
    {"name": "Northern News", "url": "https://media.northernrailway.co.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Northern Service Updates", "url": "https://www.northernrailway.co.uk/service-updates", "default_area": "rochdale", "link_pattern": r"/service-updates|/news/"},
    {"name": "National Highways North West", "url": "https://nationalhighways.co.uk/our-roads/north-west/north-west-maintenance-schemes/", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "United Utilities Incidents", "url": "https://www.unitedutilities.com/emergencies/up-my-street/", "default_area": "rochdale", "link_pattern": r"/emergencies/|/incident/"},
    {"name": "GMCA News", "url": "https://www.greatermanchester-ca.gov.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},

    # Local and regional publishers
    {"name": "Manchester Evening News", "url": "https://www.manchestereveningnews.co.uk/all-about/rochdale", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "BBC Manchester", "url": "https://www.bbc.co.uk/news/england/manchester", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "About Manchester", "url": "https://aboutmanchester.co.uk/?s=Rochdale", "default_area": "rochdale", "link_pattern": r"/"},

    # Health and education
    {"name": "Northern Care Alliance Rochdale", "url": "https://www.northerncarealliance.nhs.uk/news/rochdale-news", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Pennine Care NHS", "url": "https://www.penninecare.nhs.uk/about-us/latest-news", "default_area": "rochdale", "link_pattern": r"/latest-news/|/news/"},
    {"name": "Hopwood Hall College", "url": "https://www.hopwood.ac.uk/news-and-events/latest-news/", "default_area": "rochdale", "link_pattern": r"/news-and-events/"},
    {"name": "Rochdale Sixth Form College", "url": "https://www.rochdalesfc.ac.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},

    # Sport
    {"name": "Rochdale AFC", "url": "https://rochdaleafc.co.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Rochdale Hornets", "url": "https://www.rochdalehornets.co.uk/news", "default_area": "rochdale", "link_pattern": r"/news"},
]

GMP_ROCHDALE_AREA_PAGES = [
    {
        "name": "GMP Rochdale Town Centre",
        "url": "https://www.gmp.police.uk/area/your-area/greater-manchester/rochdale/rochdale-town-centre/news/our-priorities",
        "default_area": "rochdale",
        "link_pattern": r"/news/greater-manchester/news/news/",
    },
    {
        "name": "GMP Rochdale Central",
        "url": "https://www.gmp.police.uk/area/your-area/greater-manchester/rochdale/rochdale-central/news/our-priorities",
        "default_area": "rochdale",
        "link_pattern": r"/news/greater-manchester/news/news/",
    },
    {
        "name": "GMP Bamford",
        "url": "https://www.gmp.police.uk/area/your-area/greater-manchester/rochdale/bamford/news/our-priorities",
        "default_area": "bamford",
        "link_pattern": r"/news/greater-manchester/news/news/",
    },
    {
        "name": "GMP Healey",
        "url": "https://www.gmp.police.uk/area/your-area/greater-manchester/rochdale/healey/news/our-priorities",
        "default_area": "healey",
        "link_pattern": r"/news/greater-manchester/news/news/",
    },
    {
        "name": "GMP East Middleton",
        "url": "https://www.gmp.police.uk/area/your-area/greater-manchester/rochdale/east-middleton/news/our-priorities",
        "default_area": "middleton",
        "link_pattern": r"/news/greater-manchester/news/news/",
    },
    {
        "name": "GMP West Middleton",
        "url": "https://www.gmp.police.uk/area/your-area/greater-manchester/rochdale/west-middleton/news/our-priorities",
        "default_area": "middleton",
        "link_pattern": r"/news/greater-manchester/news/news/",
    },
]

LIVE_PAGE_SOURCES = [
    {
        "name": "Bee Network live travel alerts",
        "url": "https://tfgm.com/travel-updates/travel-alerts?ContensisTextOnly=true",
        "category": "transport",
        "default_area": "rochdale",
    },
    {
        "name": "Rochdale Council service updates",
        "url": "https://www.rochdale.gov.uk/serviceupdates",
        "category": "community",
        "default_area": "rochdale",
    },
    {
        "name": "Northern live service updates",
        "url": "https://www.northernrailway.co.uk/service-updates",
        "category": "transport",
        "default_area": "rochdale",
    },
]

DISCOVERY_LISTING_OVERRIDES = {
    "Rochdale Borough Council News": [
        "https://www.rochdale.gov.uk/news",
        "https://www.rochdale.gov.uk/news?page=2",
        "https://www.rochdale.gov.uk/news?page=3",
    ],
    "Rochdale Council Events": [
        "https://www.rochdale.gov.uk/events?page=1",
        "https://www.rochdale.gov.uk/events?page=2",
        "https://www.rochdale.gov.uk/events?page=3",
    ],
    "Rochdale Town Hall Events": [
        "https://www.rochdaletownhall.co.uk/events?page=1",
        "https://www.rochdaletownhall.co.uk/events?page=2",
        "https://www.rochdaletownhall.co.uk/events?page=3",
    ],
    "Greater Manchester Police": [
        "https://www.gmp.police.uk/news/news-search/?ct=Updates&fdte=&page=1&tdte=",
        "https://www.gmp.police.uk/news/news-search/?ct=Updates&fdte=&page=2&tdte=",
        "https://www.gmp.police.uk/news/news-search/?ct=Updates&fdte=&page=3&tdte=",
    ],
    "Roch Valley Radio Local News": [
        "https://www.rochvalleyradio.com/news/local-news/",
        "https://www.rochvalleyradio.com/news/local-news/?page=2",
        "https://www.rochvalleyradio.com/news/local-news/?page=3",
    ],
    "Manchester Evening News": [
        "https://www.manchestereveningnews.co.uk/all-about/rochdale",
        "https://www.manchestereveningnews.co.uk/all-about/rochdale?page=2",
        "https://www.manchestereveningnews.co.uk/all-about/rochdale?page=3",
    ],
}

SEARCH_GROUPS = [
    '"Rochdale" OR "Heywood" OR "Middleton"',
    '"Littleborough" OR "Milnrow" OR "Newhey" OR "Wardle"',
    '"Norden" OR "Bamford" OR "Castleton" OR "Kirkholt"',
    '"Spotland" OR "Falinge" OR "Deeplish" OR "Balderstone"',
    '"Shawclough" OR "Healey" OR "Smallbridge" OR "Smithy Bridge"',
    '"Darnhill" OR "Hopwood" OR "Alkrington" OR "Boarshaw"',
    'Rochdale police OR court OR crime OR fire',
    'Rochdale traffic OR M62 OR roadworks OR Bee Network OR Northern',
    'Rochdale council OR planning OR consultation OR ward',
    'Rochdale sport OR Rochdale AFC OR Rochdale Hornets',
    'Rochdale community OR events OR school OR NHS',
    '"Roch Valley Radio" Rochdale',
    '"Action Together" Rochdale',
    '"Your Trust" Rochdale',
    'site:facebook.com/rochvalleyradio Rochdale',
    'site:facebook.com/rochdalecouncil Rochdale',
    'site:facebook.com/beenetworkgm Rochdale',
]

FACEBOOK_GRAPH_VERSION = os.getenv("FACEBOOK_GRAPH_VERSION", "v22.0")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
FACEBOOK_COMMENTS_ENABLED = os.getenv(
    "FACEBOOK_COMMENTS_ENABLED", "true"
).lower() not in {"0", "false", "no"}

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "").strip()
X_API_BASE = os.getenv("X_API_BASE", "https://api.x.com/2").rstrip("/")
X_RECENT_SEARCH_MAX = max(10, min(100, int(os.getenv("X_RECENT_SEARCH_MAX", "100"))))

SOCIAL_CONTEXT_ENABLED = os.getenv(
    "SOCIAL_CONTEXT_ENABLED", "true"
).lower() not in {"0", "false", "no"}
SOCIAL_MIN_PUBLIC_REACTIONS = max(
    3, int(os.getenv("SOCIAL_MIN_PUBLIC_REACTIONS", "3"))
)
SOCIAL_MAX_PUBLIC_REACTIONS = max(
    SOCIAL_MIN_PUBLIC_REACTIONS,
    int(os.getenv("SOCIAL_MAX_PUBLIC_REACTIONS", "12")),
)
SOCIAL_MAX_OFFICIAL_UPDATES = max(
    1, int(os.getenv("SOCIAL_MAX_OFFICIAL_UPDATES", "4"))
)

OFFICIAL_X_HANDLES = {
    "gmprochdale": "Rochdale Police (GMP)",
    "gmpolice": "Greater Manchester Police",
}
try:
    extra_x_handles = json.loads(os.getenv("OFFICIAL_X_HANDLES_JSON", "{}"))
    if isinstance(extra_x_handles, dict):
        OFFICIAL_X_HANDLES.update({
            str(handle).lstrip("@").lower(): str(name)
            for handle, name in extra_x_handles.items()
            if str(handle).strip() and str(name).strip()
        })
except json.JSONDecodeError:
    pass

X_SEARCH_QUERIES = [
    (
        '(Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow OR '
        'Newhey OR Wardle OR Norden OR Castleton OR Kirkholt OR Spotland OR '
        'Falinge OR Deeplish) lang:en -is:retweet'
    ),
    '(from:GMPRochdale OR from:gmpolice) lang:en -is:retweet',
    '(to:GMPRochdale OR @GMPRochdale) lang:en -is:retweet',
]
try:
    extra_x_queries = json.loads(os.getenv("X_SEARCH_QUERIES_JSON", "[]"))
    if isinstance(extra_x_queries, list):
        X_SEARCH_QUERIES.extend(
            str(query) for query in extra_x_queries if str(query).strip()
        )
except json.JSONDecodeError:
    pass

# Third-party public Page reading requires the appropriate Meta app review/access.
# Additional pages can be supplied without code changes through FACEBOOK_PAGES_JSON.
PUBLIC_FACEBOOK_PAGES = [
    {"name": "Rochdale Police - GMP Facebook", "handle": "GMPRochdale", "url": "https://www.facebook.com/GMPRochdale", "default_area": "rochdale", "official": True},
    {"name": "Roch Valley Radio Facebook", "handle": "rochvalleyradio", "url": "https://www.facebook.com/rochvalleyradio", "default_area": "rochdale"},
    {"name": "Rochdale Borough Council Facebook", "handle": "rochdalecouncil", "url": "https://www.facebook.com/rochdalecouncil", "default_area": "rochdale"},
    {"name": "Bee Network Facebook", "handle": "beenetworkgm", "url": "https://www.facebook.com/beenetworkgm", "default_area": "rochdale"},
    {"name": "Rochdale Sixth Form College Facebook", "handle": "rochdalesfc", "url": "https://www.facebook.com/rochdalesfc", "default_area": "rochdale"},
]

try:
    extra_facebook_pages = json.loads(os.getenv("FACEBOOK_PAGES_JSON", "[]"))
    if isinstance(extra_facebook_pages, list):
        PUBLIC_FACEBOOK_PAGES.extend(
            page for page in extra_facebook_pages
            if isinstance(page, dict) and page.get("handle") and page.get("name")
        )
except json.JSONDecodeError:
    pass

LOCAL_TERMS = {
    "rochdale", "rochdale town centre", "heywood", "middleton",
    "littleborough", "milnrow", "newhey", "norden", "bamford",
    "kirkholt", "shawclough", "healey", "whitworth", "wardle",
    "smithy bridge", "castleton", "spotland", "falinge", "balderstone",
    "deeplish", "smallbridge", "firgrove", "syke", "cutgate",
    "darnhill", "hopwood", "alkrington", "boarshaw",
    "belfield", "wardleworth", "sudden", "buersil", "cloverhall",
    "lowerplace", "meanwood", "mandale park", "summit",
    "hollingworth lake", "slattocks", "birch", "caldershaw",
}

AREA_KEYWORDS = {
    "darnhill": {"darnhill"}, "hopwood": {"hopwood"},
    "alkrington": {"alkrington"}, "boarshaw": {"boarshaw"},
    "newhey": {"newhey"}, "smithy_bridge": {"smithy bridge"}, "wardle": {"wardle"},
    "smallbridge": {"smallbridge"}, "norden": {"norden"}, "bamford": {"bamford"},
    "cutgate": {"cutgate", "caldershaw"}, "kirkholt": {"kirkholt"},
    "castleton": {"castleton"}, "spotland": {"spotland"}, "falinge": {"falinge"},
    "deeplish": {"deeplish"}, "balderstone": {"balderstone"}, "firgrove": {"firgrove"},
    "shawclough": {"shawclough"}, "healey": {"healey"}, "syke": {"syke"},
    "wardleworth": {"wardleworth"}, "sudden": {"sudden"},
    "lowerplace": {"lowerplace"}, "meanwood": {"meanwood"},
    "littleborough": {"littleborough", "hollingworth lake", "summit"},
    "milnrow": {"milnrow", "slattocks"}, "heywood": {"heywood"},
    "middleton": {"middleton"}, "whitworth": {"whitworth"},
    "rochdale": {"rochdale", "rochdale town centre", "town centre"},
}

AMBIGUOUS_LOCAL_TERMS = {
    "middleton", "healey", "wardle", "bamford", "norden",
    "hopwood", "birch", "summit", "syke",
}

UNAMBIGUOUS_LOCAL_TERMS = LOCAL_TERMS - AMBIGUOUS_LOCAL_TERMS

TRUSTED_LOCAL_SOURCE_PREFIXES = (
    "Rochdale Borough Council",
    "Rochdale Council",
    "Rochdale AFC",
    "Rochdale Hornets",
    "Rochdale Development Agency",
    "Rochdale Town Hall",
    "Rochdale Police",
    "Action Together Rochdale",
    "Your Trust Rochdale",
    "Visit Rochdale",
    "Northern Care Alliance Rochdale",
    "Hopwood Hall College",
    "Rochdale Sixth Form College",
    "Facebook Events — Rochdale",
)

PLACE_CONTEXT_SUFFIXES = (
    "town", "town centre", "area", "ward", "estate", "village",
    "residents", "community", "council", "borough", "school",
    "college", "library", "road", "street", "lane", "avenue",
    "park", "station", "market", "police", "fire station",
    "hospital", "clinic", "businesses", "shops", "pub", "events",
    "traffic", "services", "neighbourhood",
)

PLACE_CONTEXT_PREFIXES = (
    "in", "at", "near", "around", "across", "from", "within",
    "throughout", "towards", "toward", "outside", "serving",
    "based in", "located in", "residents of", "people in",
    "businesses in", "schools in", "school in", "police in",
    "firefighters in", "travelling to", "roads in",
)

CATEGORY_KEYWORDS = {
    "crime": {"arrest", "police", "charged", "court", "burglary", "robbery", "assault", "stabbing", "theft", "fraud", "wanted", "jailed", "murder"},
    "traffic": {"traffic", "roadworks", "road closure", "collision", "crash", "m62", "a627", "junction", "lane closure", "diversion", "congestion"},
    "transport": {"bus", "train", "tram", "metrolink", "bee network", "station", "timetable", "public transport"},
    "politics": {"council", "councillor", "election", "cabinet", "committee", "planning", "consultation", "mayor", "mp "},
    "education": {"school", "college", "university", "ofsted", "teacher", "pupil", "student", "education"},
    "sport": {"football", "rochdale afc", "hornets", "dale", "match", "fixture", "league", "rugby", "cricket", "boxing"},
    "events": {"festival", "concert", "event", "fair", "market", "open day", "exhibition", "gig", "performance", "parade"},
    "business": {"business", "shop", "restaurant", "pub", "company", "jobs", "investment", "opening", "closure"},
    "community": {"community", "charity", "fundraiser", "volunteer", "library", "support group", "appeal"},
    "health": {"nhs", "hospital", "health", "doctor", "gp", "clinic", "care service", "mental health"},
    "environment": {"flood", "weather", "environment", "recycling", "litter", "climate", "wildlife", "park"},
}

SENSITIVE_PATTERNS = [
    r"\b(alleged|allegedly|accused|suspect|suspected|charged|arrested|court|trial|jury|inquest|coroner)\b",
    r"\b(murder|manslaughter|rape|sexual|assault|abuse|grooming|stabbing|death|died|killed)\b",
    r"\b(child|children|minor|youth|under[- ]?18|schoolgirl|schoolboy)\b",
    r"\b(suicide|self-harm|domestic abuse|domestic violence)\b",
]

DROP_PATTERNS = [
    r"\b(opinion|comment|column|editorial)\b",
    r"\bfor sale\b|\bfor rent\b|\broom to let\b|\bjob vacancy\b",
    r"\brecommendations please\b|\bdoes anyone know\b|\bgetting rid of\b",
]

PLACEHOLDER_PATTERNS = [
    r"\[(?:insert|relevant|contact|date|number|details|link)[^\]]*\]",
    r"\babout this article\b.*$", r"\brelated topics\b.*$",
    r"#rochdalenews|#greatermanchester", r"\bfact-checked local journalism\b",
]

CATEGORY_STOCK_IMAGES = {
    category: f"assets/img/stock_{category}.jpg"
    for category in [
        "news", "crime", "traffic", "transport", "politics", "education",
        "sport", "events", "business", "community", "health", "environment",
    ]
}

ARTICLE_SCHEMA = {
    "name": "rochdale_daily_article",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "publishable": {"type": "boolean"},
            "title": {"type": "string"},
            "excerpt": {"type": "string"},
            "paragraphs": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 8},
            "category": {"type": "string", "enum": list(CATEGORY_STOCK_IMAGES)},
            "area": {"type": "string", "enum": list(AREA_KEYWORDS)},
            "legal_disclaimer": {"type": "string"},
            "right_to_reply": {"type": "string"},
            "community_reaction": {"type": "string"},
            "social_context_used": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": [
            "publishable", "title", "excerpt", "paragraphs", "category",
            "area", "legal_disclaimer", "right_to_reply",
            "community_reaction", "social_context_used", "reason",
        ],
    },
}

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("rochdale_daily")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "RochdaleDaily/3.0 (+https://rochdaledaily.co.uk; contact: news@rochdaledaily.co.uk)",
    "Accept-Language": "en-GB,en;q=0.9",
})

ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser] = {}

@dataclass
class Candidate:
    source_name: str
    source_url: str
    source_title: str
    source_summary: str
    source_published_at: str
    area: str
    category: str
    image_candidate_url: str = ""
    source_body_excerpt: str = ""
    event_start_at: str = ""
    event_end_at: str = ""
    event_location: str = ""
    source_kind: str = "article"
    related_sources: list[dict[str, str]] = field(default_factory=list)
    social_context: list[dict[str, Any]] = field(default_factory=list)
    story_key: str = ""

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def source_is_denied(source_name: str = "", source_url: str = "") -> bool:
    name = normalise_ws(source_name).lower()
    domain = domain_of(source_url)
    return (
        domain in SOURCE_DENY_DOMAINS
        or any(blocked in name for blocked in SOURCE_DENY_NAMES)
    )

def is_current_uk_day(value: datetime | None) -> bool:
    return bool(value) and value.astimezone(UK_TZ).date() == utc_now().astimezone(UK_TZ).date()

def event_is_current_or_future(value: datetime | None) -> bool:
    if value is None:
        return False
    return utc_now() - timedelta(hours=12) <= value <= utc_now() + timedelta(days=550)

def canonicalise_url(url: str) -> str:
    parsed = urlparse(url)
    query_parts = []
    for part in parsed.query.split("&"):
        low = part.lower()
        if part and not low.startswith(("utm_", "at_medium=", "at_campaign=", "fbclid=", "gclid=")):
            query_parts.append(part)
    return urlunparse((parsed.scheme or "https", parsed.netloc.lower(), parsed.path, "", "&".join(query_parts), ""))

def stable_id(url: str) -> str:
    return hashlib.sha256(canonicalise_url(url).encode("utf-8")).hexdigest()[:18]

def normalise_ws(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

def strip_markdown(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", text)
    text = re.sub(r"`{1,3}([^`]+)`{1,3}", r"\1", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    for pattern in PLACEHOLDER_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
    return normalise_ws(text).strip("*_#- ")

def make_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", strip_markdown(title).lower()).strip("-")[:80] or "local-news-update"

def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(str(value).strip())
        except (TypeError, ValueError, OverflowError):
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)

def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def is_fresh(value: datetime | None) -> bool:
    if value is None:
        return False
    age = utc_now() - value
    if not (timedelta(minutes=-30) <= age <= timedelta(hours=MAX_NEWS_AGE_HOURS)):
        return False
    if SAME_DAY_ONLY:
        return is_current_uk_day(value)
    return True

def _plain_text(value: Any) -> str:
    raw = str(value or "")
    if "<" in raw and ">" in raw:
        raw = BeautifulSoup(raw, "lxml").get_text(" ", strip=True)
    return normalise_ws(raw)


def _term_pattern(term: str) -> str:
    return rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"


def _contains_term(text: str, term: str) -> bool:
    return bool(re.search(_term_pattern(term), text, flags=re.IGNORECASE))


def _has_geographical_context(text: str, term: str) -> bool:
    term_pattern = _term_pattern(term)
    prefix_pattern = "|".join(re.escape(prefix) for prefix in PLACE_CONTEXT_PREFIXES)
    suffix_pattern = "|".join(re.escape(suffix) for suffix in PLACE_CONTEXT_SUFFIXES)

    before = rf"\b(?:{prefix_pattern})\s+(?:the\s+)?{term_pattern}"
    after = rf"{term_pattern}(?:'s)?\s+(?:{suffix_pattern})\b"
    qualified = rf"{term_pattern}\s*,\s*(?:Rochdale|Greater Manchester)\b"
    postcode_context = rf"{term_pattern}.{{0,80}}\b(?:OL|M)\d{{1,2}}\s*\d[A-Z]{{2}}\b"

    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in (before, after, qualified, postcode_context)
    )


def locality_evidence(text: str, source_name: str = "", source_url: str = "") -> dict[str, Any]:
    plain = _plain_text(text)
    evidence: list[str] = []
    score = 0

    if source_is_denied(source_name, source_url):
        return {"local": False, "score": 0, "evidence": ["denied-source"]}

    if source_name.startswith(TRUSTED_LOCAL_SOURCE_PREFIXES):
        score += 5
        evidence.append(f"trusted-source:{source_name}")

    if _contains_term(plain, "rochdale"):
        score += 5
        evidence.append("place:rochdale")

    for term in sorted(UNAMBIGUOUS_LOCAL_TERMS - {"rochdale"}, key=len, reverse=True):
        if _contains_term(plain, term):
            score += 2
            evidence.append(f"place:{term}")

    for term in sorted(AMBIGUOUS_LOCAL_TERMS, key=len, reverse=True):
        if _has_geographical_context(plain, term):
            score += 2
            evidence.append(f"contextual-place:{term}")

    return {"local": score >= 2, "score": score, "evidence": evidence}


def detect_area(text: str, fallback: str = "rochdale") -> str:
    plain = _plain_text(text)

    for area, terms in AREA_KEYWORDS.items():
        if area == "rochdale":
            continue
        for term in sorted(terms, key=len, reverse=True):
            if term in AMBIGUOUS_LOCAL_TERMS:
                if _has_geographical_context(plain, term):
                    return area
            elif _contains_term(plain, term):
                return area

    if _contains_term(plain, "rochdale"):
        return "rochdale"
    return fallback


def categorise(text: str) -> str:
    low = text.lower()
    scores = {
        category: sum(1 for keyword in keywords if keyword in low)
        for category, keywords in CATEGORY_KEYWORDS.items()
    }
    category, score = max(scores.items(), key=lambda item: item[1])
    return category if score else "news"


def is_local(text: str, source_name: str, source_url: str = "") -> bool:
    return bool(locality_evidence(text, source_name, source_url)["local"])


def article_is_local(article: dict[str, Any]) -> bool:
    combined = " ".join([
        str(article.get("title") or ""),
        str(article.get("excerpt") or ""),
        str(article.get("content_html") or ""),
        str(article.get("event_location") or ""),
    ])
    return is_local(
        combined,
        str(article.get("source_name") or ""),
        str(article.get("source_url") or ""),
    )


# Locality rules are isolated in a dependency-free module and regression-tested
# before each scraper run.
from story_identity import (
    authority_score,
    build_story_key,
    dedupe_article_records,
    merge_article_records,
    same_story,
)

from locality_rules import (
    AREA_KEYWORDS,
    LOCAL_TERMS,
    article_is_local,
    detect_area,
    is_local,
    locality_evidence,
    source_is_denied,
)

def should_drop(text: str) -> bool:
    low = text.lower()
    return any(re.search(pattern, low) for pattern in DROP_PATTERNS)

def is_sensitive(text: str, category: str) -> bool:
    return category == "crime" or any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)

def robots_allows(url: str) -> bool:
    if not RESPECT_ROBOTS:
        return True
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    robot = ROBOTS_CACHE.get(base)
    if robot is None:
        robot = urllib.robotparser.RobotFileParser()
        robot.set_url(urljoin(base, "/robots.txt"))
        try:
            robot.read()
        except Exception:
            log.warning("Could not read robots.txt for %s; allowing a standard public-page request.", base)
            return True
        ROBOTS_CACHE[base] = robot
    try:
        return robot.can_fetch(SESSION.headers["User-Agent"], url)
    except Exception:
        return True

def fetch_html(url: str) -> tuple[str, str]:
    if not robots_allows(url):
        raise PermissionError(f"robots.txt does not permit fetching {url}")
    response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "<html" not in response.text[:500].lower():
        raise ValueError(f"Not an HTML page: {content_type}")
    return response.url, response.text

def first_meta(soup: BeautifulSoup, selectors: Iterable[tuple[str, dict[str, str]]]) -> str:
    for tag, attrs in selectors:
        node = soup.find(tag, attrs=attrs)
        if node and node.get("content"):
            return normalise_ws(node.get("content"))
    return ""

def extract_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        queue = payload if isinstance(payload, list) else [payload]
        for item in queue:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                queue.extend(item["@graph"])
            elif isinstance(item, dict):
                objects.append(item)
    return objects

def image_from_jsonld(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return image_from_jsonld(value[0])
    if isinstance(value, dict):
        return str(value.get("url") or value.get("contentUrl") or "")
    return ""

def page_metadata(url: str) -> dict[str, str]:
    final_url, raw_html = fetch_html(url)
    soup = BeautifulSoup(raw_html, "lxml")
    jsonld = extract_jsonld(soup)

    title = first_meta(soup, [
        ("meta", {"property": "og:title"}),
        ("meta", {"name": "twitter:title"}),
    ])
    if not title:
        h1 = soup.find("h1")
        title = normalise_ws(h1.get_text(" ", strip=True) if h1 else "")
    if not title and soup.title:
        title = normalise_ws(soup.title.get_text(" ", strip=True))

    description = first_meta(soup, [
        ("meta", {"property": "og:description"}),
        ("meta", {"name": "description"}),
        ("meta", {"name": "twitter:description"}),
    ])
    image_url = first_meta(soup, [
        ("meta", {"property": "og:image:secure_url"}),
        ("meta", {"property": "og:image"}),
        ("meta", {"name": "twitter:image"}),
    ])
    published = first_meta(soup, [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "article:published_time"}),
        ("meta", {"name": "date"}),
        ("meta", {"name": "pubdate"}),
        ("meta", {"itemprop": "datePublished"}),
    ])
    modified = first_meta(soup, [
        ("meta", {"property": "article:modified_time"}),
        ("meta", {"itemprop": "dateModified"}),
    ])

    event_start = ""
    event_end = ""
    event_location = ""
    content_type = "article"
    body_parts: list[str] = []

    for item in jsonld:
        kind = item.get("@type")
        kinds = set(kind if isinstance(kind, list) else [kind])

        if "Event" in kinds:
            content_type = "event"
            title = title or normalise_ws(item.get("name"))
            description = description or normalise_ws(item.get("description"))
            event_start = event_start or normalise_ws(item.get("startDate"))
            event_end = event_end or normalise_ws(item.get("endDate"))
            location = item.get("location")
            if isinstance(location, dict):
                address = location.get("address")
                if isinstance(address, dict):
                    event_location = normalise_ws(" ".join(
                        str(address.get(key) or "")
                        for key in ("streetAddress", "addressLocality", "postalCode")
                    ))
                event_location = event_location or normalise_ws(location.get("name"))
            image_url = image_url or image_from_jsonld(item.get("image"))

        if kinds.intersection({"NewsArticle", "Article", "ReportageNewsArticle"}):
            title = title or normalise_ws(item.get("headline") or item.get("name"))
            description = description or normalise_ws(item.get("description"))
            published = published or normalise_ws(item.get("datePublished"))
            modified = modified or normalise_ws(item.get("dateModified"))
            image_url = image_url or image_from_jsonld(item.get("image"))
            article_body = normalise_ws(item.get("articleBody"))
            if article_body:
                body_parts.append(article_body[:3500])

    # A generic <time> is useful for articles, but on event pages it normally
    # represents the event date rather than the publication date.
    if not published and content_type != "event":
        for time_node in soup.find_all("time"):
            candidate_date = time_node.get("datetime") or time_node.get("content")
            if parse_datetime(candidate_date):
                published = str(candidate_date)
                break

    if not event_start and content_type == "event":
        visible = normalise_ws(soup.get_text(" ", strip=True))
        event_start = extract_future_event_date(visible)

    if not body_parts:
        paragraphs = [
            normalise_ws(p.get_text(" ", strip=True))
            for p in soup.select("article p, main p")
        ]
        body_parts.extend([p for p in paragraphs if len(p) >= 40][:8])

    return {
        "url": canonicalise_url(final_url),
        "title": strip_markdown(title),
        "description": strip_markdown(description),
        "published": published or modified,
        "modified": modified,
        "image": urljoin(final_url, image_url) if image_url else "",
        "body_excerpt": normalise_ws(" ".join(body_parts))[:5000],
        "content_type": content_type,
        "event_start": event_start,
        "event_end": event_end,
        "event_location": event_location,
    }

def entry_datetime(entry: Any) -> datetime | None:
    for key in ("published", "updated", "created"):
        parsed = parse_datetime(getattr(entry, key, None))
        if parsed:
            return parsed
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, key, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None

def rss_image(entry: Any) -> str:
    for attr in ("media_content", "media_thumbnail"):
        for item in getattr(entry, attr, None) or []:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    for item in getattr(entry, "enclosures", None) or []:
        if isinstance(item, dict) and str(item.get("type") or "").startswith("image/") and item.get("href"):
            return str(item["href"])
    return ""

def google_news_sources() -> list[dict[str, str]]:
    return [
        {
            "name": f"Google News search {index + 1}",
            "url": f"https://news.google.com/rss/search?q={quote_plus(query + ' when:1d -site:rochdaleonline.co.uk -site:rochdaletimes.co.uk')}&hl=en-GB&gl=GB&ceid=GB:en",
            "default_area": "rochdale",
            "aggregator": "google",
        }
        for index, query in enumerate(SEARCH_GROUPS)
    ]

def collect_rss_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    for source in RSS_SOURCES + google_news_sources():
        log.info("Reading RSS: %s", source["name"])
        feed = feedparser.parse(source["url"])
        if getattr(feed, "bozo", False):
            log.warning("RSS warning for %s: %s", source["name"], getattr(feed, "bozo_exception", "unknown"))
        for entry in list(feed.entries)[:RSS_ITEMS_PER_SOURCE]:
            source_url = canonicalise_url(str(getattr(entry, "link", "") or ""))
            source_title = strip_markdown(getattr(entry, "title", ""))
            summary_html = str(getattr(entry, "summary", "") or getattr(entry, "description", "") or "")
            summary = strip_markdown(BeautifulSoup(summary_html, "lxml").get_text(" ", strip=True))
            published = entry_datetime(entry)
            source_name = source["name"]
            entry_source = getattr(entry, "source", None)
            if isinstance(entry_source, dict):
                source_name = strip_markdown(entry_source.get("title")) or source_name
                entry_source_url = str(entry_source.get("href") or "")
            else:
                entry_source_url = ""

            if source_is_denied(source_name, entry_source_url or source_url):
                log.info("Blocked prohibited source: %s", source_name or source_url)
                continue

            text = f"{source_title} {summary}"
            if not source_url or not source_title or not is_fresh(published):
                continue
            if should_drop(text) or not is_local(text, source_name, source_url):
                continue
            image_url = rss_image(entry)
            body_excerpt = summary
            if source.get("aggregator") != "google" and (not image_url or len(summary) < 100):
                try:
                    meta = page_metadata(source_url)
                    source_title = meta["title"] or source_title
                    summary = meta["description"] or summary
                    image_url = image_url or meta["image"]
                    body_excerpt = meta["body_excerpt"] or body_excerpt
                    page_date = parse_datetime(meta["published"])
                    if page_date:
                        published = page_date
                except Exception as exc:
                    log.debug("Metadata fallback failed for %s: %s", source_url, exc)
            if not is_fresh(published):
                continue
            combined = f"{source_title} {summary} {body_excerpt}"
            candidates.append(Candidate(
                source_name=source_name,
                source_url=source_url,
                source_title=source_title,
                source_summary=summary,
                source_published_at=iso_utc(published),
                area=detect_area(
                    combined,
                    source["default_area"],
                    source_name,
                    source_url,
                ),
                category=categorise(combined),
                image_candidate_url=image_url,
                source_body_excerpt=body_excerpt,
            ))
    return candidates

def discovery_listing_urls(source: dict[str, str]) -> list[str]:
    configured = DISCOVERY_LISTING_OVERRIDES.get(source["name"], [])
    if configured:
        return configured[:DISCOVERY_PAGE_LIMIT]
    return [source["url"]]


def discovery_links(source: dict[str, str]) -> list[str]:
    pattern = re.compile(source["link_pattern"], re.IGNORECASE)
    links: list[str] = []
    seen: set[str] = set()

    for listing_url in discovery_listing_urls(source):
        try:
            final_url, raw_html = fetch_html(listing_url)
        except Exception as exc:
            log.warning(
                "Discovery page failed for %s (%s): %s",
                source["name"],
                listing_url,
                exc,
            )
            continue

        soup = BeautifulSoup(raw_html, "lxml")
        for anchor in soup.find_all("a", href=True):
            url = canonicalise_url(urljoin(final_url, anchor["href"]))
            if url in seen or domain_of(url) != domain_of(final_url):
                continue
            if source_is_denied(source.get("name", ""), url):
                continue
            if not pattern.search(
                urlparse(url).path + "?" + urlparse(url).query
            ):
                continue
            seen.add(url)
            links.append(url)
            if len(links) >= DISCOVERY_LINKS_PER_SOURCE:
                return links

    return links


def _discovery_candidate(source: dict[str, str], url: str) -> Candidate | None:
    if source_is_denied(source.get("name", ""), url):
        return None

    try:
        meta = page_metadata(url)
    except PermissionError as exc:
        log.info("%s", exc)
        return None
    except Exception as exc:
        log.debug("Page metadata failed for %s: %s", url, exc)
        return None

    text = f"{meta['title']} {meta['description']} {meta['body_excerpt']}"
    if not meta["title"] or should_drop(text) or not is_local(text, source["name"], meta["url"]):
        return None

    source_name_lower = source["name"].lower()
    event_start = parse_datetime(meta.get("event_start"))
    is_event = (
        meta.get("content_type") == "event"
        or "event" in source_name_lower
        or "what's on" in source_name_lower
        or "/events/" in urlparse(url).path.lower()
    )

    if is_event and event_is_current_or_future(event_start):
        published = utc_now()  # observed and verified during this run
        source_kind = "event"
        category = "events"
    else:
        published = parse_datetime(meta.get("published"))
        source_kind = "article"
        category = categorise(text)

        if not is_fresh(published):
            # Only a narrow allowlist of official live-status pages may use the
            # current observation time when no publication timestamp exists.
            if source_name_lower in LIVE_SOURCE_NAMES and len(text) >= 80:
                published = utc_now()
                source_kind = "live"
            else:
                return None

    return Candidate(
        source_name=source["name"],
        source_url=meta["url"],
        source_title=meta["title"],
        source_summary=meta["description"] or meta["body_excerpt"][:900],
        source_published_at=iso_utc(published),
        area=detect_area(
            text,
            source["default_area"],
            source["name"],
            meta["url"],
        ),
        category=category,
        image_candidate_url=meta["image"],
        source_body_excerpt=meta["body_excerpt"],
        event_start_at=iso_utc(event_start) if event_start else "",
        event_end_at=meta.get("event_end", ""),
        event_location=meta.get("event_location", ""),
        source_kind=source_kind,
    )


def collect_discovery_candidates() -> list[Candidate]:
    jobs: list[tuple[dict[str, str], str]] = []
    all_discovery_sources = DISCOVERY_PAGES + GMP_ROCHDALE_AREA_PAGES
    for source in all_discovery_sources:
        if source_is_denied(source.get("name", ""), source.get("url", "")):
            continue
        log.info("Discovering pages: %s", source["name"])
        jobs.extend((source, url) for url in discovery_links(source))

    candidates: list[Candidate] = []
    with ThreadPoolExecutor(max_workers=max(1, DISCOVERY_WORKERS)) as executor:
        future_map = {
            executor.submit(_discovery_candidate, source, url): (source["name"], url)
            for source, url in jobs
        }
        for future in as_completed(future_map):
            try:
                candidate = future.result()
            except Exception as exc:
                source_name, url = future_map[future]
                log.debug("Discovery worker failed for %s %s: %s", source_name, url, exc)
                continue
            if candidate:
                candidates.append(candidate)

    return candidates



def collect_live_page_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []

    for source in LIVE_PAGE_SOURCES:
        if source_is_denied(source["name"], source["url"]):
            continue
        try:
            final_url, raw_html = fetch_html(source["url"])
        except Exception as exc:
            log.warning("Live page failed for %s: %s", source["name"], exc)
            continue

        soup = BeautifulSoup(raw_html, "lxml")
        blocks: list[str] = []
        seen_blocks: set[str] = set()

        for node in soup.select(
            "article, li, section, .alert, .travel-alert, .service-update, main p"
        ):
            text = normalise_ws(node.get_text(" ", strip=True))
            if len(text) < 45:
                continue
            if not is_local(text, source["name"], final_url):
                continue
            key = text.lower()[:240]
            if key in seen_blocks:
                continue
            seen_blocks.add(key)
            blocks.append(text)
            if len(blocks) >= 12:
                break

        for index, block in enumerate(blocks):
            area = detect_area(
                block,
                source["default_area"],
                source["name"],
                final_url,
            )
            if not area:
                continue

            short = block[:145].rsplit(" ", 1)[0]
            candidates.append(Candidate(
                source_name=source["name"],
                source_url=f"{canonicalise_url(final_url)}#live-{stable_id(block)}",
                source_title=short,
                source_summary=block[:1000],
                source_published_at=iso_utc(utc_now()),
                area=area,
                category=source["category"],
                source_body_excerpt=block[:3500],
                source_kind="live",
            ))

    return candidates


def extract_future_event_date(text: str) -> str:
    """
    Extract a likely future event date from visible Facebook event-card text.

    Facebook's discovery UI changes frequently, so this is intentionally
    conservative. It returns an empty string if no plausible date is found.
    """
    cleaned = normalise_ws(text)
    if not cleaned:
        return ""
    try:
        matches = search_dates(
            cleaned,
            languages=["en"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": utc_now(),
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": "Europe/London",
                "TO_TIMEZONE": "UTC",
            },
        ) or []
    except Exception:
        return ""

    for matched_text, value in matches[:5]:
        if value is None:
            continue
        value_utc = value.astimezone(timezone.utc)
        if utc_now() - timedelta(hours=12) <= value_utc <= utc_now() + timedelta(days=550):
            return iso_utc(value_utc)
    return ""


def clean_facebook_event_title(value: str) -> str:
    title = strip_markdown(value)
    title = re.sub(
        r"^(?:Facebook|Events?|Interested|Going|Share)\s*[-:|]\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return title[:180]


def collect_facebook_event_discovery_candidates() -> list[Candidate]:
    """
    Read the exact Rochdale Facebook Events discovery page supplied by the
    publisher using a logged-out public browser session.

    The collector does not bypass a login wall, use private groups, inject
    cookies or defeat anti-bot controls. If Facebook does not expose the
    discovery page publicly during a run, it logs the limitation and returns
    no events.

    Event cover-image URLs are recorded as source-image candidates. They are
    not automatically republished unless FACEBOOK_EVENT_IMAGE_REUSE=true,
    because public visibility does not itself grant copyright permission.
    """
    if not FACEBOOK_EVENTS_DISCOVERY_URL:
        return []

    log.info("Reading Facebook Events discovery source: %s", FACEBOOK_EVENTS_DISCOVERY_URL)
    raw_cards: list[dict[str, str]] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = browser.new_context(
                locale="en-GB",
                timezone_id="Europe/London",
                viewport={"width": 1440, "height": 1100},
                user_agent=SESSION.headers["User-Agent"],
            )
            page = context.new_page()
            page.set_default_timeout(FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS)

            try:
                page.goto(
                    FACEBOOK_EVENTS_DISCOVERY_URL,
                    wait_until="domcontentloaded",
                    timeout=FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                log.warning("Facebook Events discovery page timed out during initial load.")

            # Best-effort dismissal of cookie banners that may obscure the page.
            for label in (
                "Allow all cookies",
                "Decline optional cookies",
                "Only allow essential cookies",
                "Close",
                "Not now",
            ):
                try:
                    button = page.get_by_role("button", name=re.compile(label, re.I))
                    if button.count():
                        button.first.click(timeout=1500)
                except Exception:
                    pass

            page.wait_for_timeout(3500)
            for _ in range(4):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(900)

            body_text = normalise_ws(page.locator("body").inner_text(timeout=5000))
            if re.search(r"\blog in\b|\bsign up\b", body_text, flags=re.IGNORECASE):
                # Do not fail immediately: Facebook sometimes displays login prompts
                # alongside public results. We still inspect any public event links.
                log.info("Facebook displayed a login prompt; checking for public event cards.")

            raw_cards = page.evaluate(
                """
                () => {
                  const results = [];
                  const seen = new Set();
                  const links = Array.from(document.querySelectorAll('a[href*="/events/"]'));

                  for (const link of links) {
                    const rawHref = link.href || link.getAttribute('href') || '';
                    const match = rawHref.match(/facebook\\.com\\/events\\/(\\d+)/i);
                    if (!match) continue;

                    const eventUrl = `https://www.facebook.com/events/${match[1]}/`;
                    if (seen.has(eventUrl)) continue;
                    seen.add(eventUrl);

                    let card = link.closest('[role="article"]');
                    if (!card) {
                      let current = link;
                      for (let depth = 0; depth < 7 && current; depth += 1) {
                        if (current.querySelector && current.querySelector('img')) {
                          card = current;
                        }
                        current = current.parentElement;
                      }
                    }
                    card = card || link.parentElement || link;

                    const text = (card.innerText || link.innerText || '').trim();
                    const aria = (link.getAttribute('aria-label') || '').trim();
                    const image = card.querySelector ? card.querySelector('img[src]') : null;
                    const title =
                      aria ||
                      (link.innerText || '').trim() ||
                      (text.split('\\n').find(line => line.trim().length > 3) || '');

                    results.push({
                      url: eventUrl,
                      title,
                      text,
                      image: image ? (image.currentSrc || image.src || '') : '',
                    });

                    if (results.length >= 40) break;
                  }
                  return results;
                }
                """
            )

            context.close()
            browser.close()
    except Exception as exc:
        log.warning("Facebook Events browser collector unavailable: %s", exc)
        return []

    if not raw_cards:
        log.warning(
            "No public event cards were exposed by the supplied Facebook Events page. "
            "The source remains configured and will be retried on the next run."
        )
        return []

    candidates: list[Candidate] = []
    seen_urls: set[str] = set()

    for card in raw_cards:
        event_url = canonicalise_url(card.get("url", ""))
        if not event_url or event_url in seen_urls:
            continue
        seen_urls.add(event_url)

        visible_text = strip_markdown(card.get("text", ""))
        title = clean_facebook_event_title(card.get("title", ""))
        if not title or len(title) < 4:
            lines = [normalise_ws(line) for line in str(card.get("text", "")).splitlines()]
            title = next((line for line in lines if len(line) >= 4), "")
            title = clean_facebook_event_title(title)
        if not title:
            continue

        combined = f"{title} {visible_text}"
        # The supplied location filter is Rochdale, but retaining local validation
        # prevents unrelated promoted events from being auto-published.
        if not is_local(combined, "Facebook Rochdale Events", event_url):
            continue

        event_start = extract_future_event_date(visible_text)
        image_url = str(card.get("image") or "").strip()

        summary_parts = [visible_text]
        if event_start:
            summary_parts.append(f"Structured event start: {event_start}")
        summary = normalise_ws(" ".join(summary_parts))[:1600]

        candidates.append(Candidate(
            source_name="Facebook Events — Rochdale discovery",
            source_url=event_url,
            source_title=title,
            source_summary=summary,
            source_published_at=iso_utc(utc_now()),
            area=detect_area(
                combined,
                "rochdale",
                "Facebook Events — Rochdale discovery",
                event_url,
            ),
            category="events",
            image_candidate_url=image_url,
            source_body_excerpt=visible_text[:4000],
            event_start_at=event_start,
            event_location="Rochdale area",
            source_kind="event",
        ))

        if len(candidates) >= FACEBOOK_EVENTS_MAX:
            break

    log.info("Facebook Events discovery collected %d public event listings.", len(candidates))
    return candidates



SOCIAL_STOPWORDS = {
    "about", "after", "again", "against", "been", "before", "being",
    "between", "could", "from", "have", "into", "local", "more", "news",
    "people", "rochdale", "said", "that", "their", "there", "these",
    "they", "this", "today", "under", "what", "when", "where", "which",
    "with", "would", "your", "heywood", "middleton", "littleborough",
}
SOCIAL_UNSAFE_PATTERNS = [
    r"\b(name and shame|paedophile|pedophile|rapist|murderer|terrorist)\b",
    r"\b(he did it|she did it|they did it|definitely guilty|must be guilty)\b",
    r"\bI know who\b|\bthe suspect is\b|\bthe offender is\b",
    r"\bkill (?:him|her|them)\b|\bdeserves to die\b",
]
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?44\s?|0)\d(?:[\s()-]*\d){8,12}(?!\d)")

_FACEBOOK_SOCIAL_CACHE: list[dict[str, Any]] | None = None
_X_SOCIAL_CACHE: list[dict[str, Any]] | None = None


def participant_digest(platform: str, identifier: str) -> str:
    raw = f"{platform}:{identifier}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def sanitise_social_text(value: Any) -> str:
    text = strip_markdown(value)
    text = URL_RE.sub("", text)
    text = EMAIL_RE.sub("", text)
    text = PHONE_RE.sub("", text)
    text = POSTCODE_RE.sub("the local area", text)
    text = ADDRESS_RE.sub("a local location", text)
    text = re.sub(r"(?<!\w)@[A-Za-z0-9_]{1,30}", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:700]


def public_reaction_is_usable(text: str) -> bool:
    if len(text) < 18:
        return False
    return not any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in SOCIAL_UNSAFE_PATTERNS
    )


def social_tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) >= 4 and token not in SOCIAL_STOPWORDS
    }


def social_record_score(candidate: Candidate, record: dict[str, Any]) -> float:
    candidate_text = (
        f"{candidate.source_title} {candidate.source_summary} "
        f"{candidate.source_body_excerpt[:1200]}"
    )
    record_text = (
        f"{record.get('parent_text', '')} {record.get('text', '')}"
    )
    candidate_tokens = social_tokens(candidate_text)
    record_tokens = social_tokens(record_text)
    if not candidate_tokens or not record_tokens:
        return 0.0

    overlap = candidate_tokens & record_tokens
    if len(overlap) < 2:
        return 0.0

    score = len(overlap) / max(4, min(len(candidate_tokens), len(record_tokens)))

    candidate_url = canonicalise_url(candidate.source_url)
    for related_url in record.get("related_urls", []) or []:
        if canonicalise_url(str(related_url)) == candidate_url:
            score += 2.0

    if record.get("official"):
        score += 0.12
    if record.get("parent_url") == candidate_url:
        score += 2.0
    return score


def today_start_utc() -> str:
    now_local = utc_now().astimezone(UK_TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return iso_utc(start_local.astimezone(timezone.utc))


def collect_x_social_records() -> list[dict[str, Any]]:
    global _X_SOCIAL_CACHE
    if _X_SOCIAL_CACHE is not None:
        return _X_SOCIAL_CACHE
    if not SOCIAL_CONTEXT_ENABLED or not X_BEARER_TOKEN:
        log.info(
            "X social correlation inactive: add the X_BEARER_TOKEN GitHub secret."
        )
        _X_SOCIAL_CACHE = []
        return _X_SOCIAL_CACHE

    records_by_id: dict[str, dict[str, Any]] = {}
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}

    for query in X_SEARCH_QUERIES:
        params = {
            "query": query,
            "start_time": today_start_utc(),
            "max_results": X_RECENT_SEARCH_MAX,
            "tweet.fields": (
                "created_at,author_id,conversation_id,in_reply_to_user_id,"
                "public_metrics,referenced_tweets,entities,lang"
            ),
            "expansions": "author_id",
            "user.fields": "username,name,verified,protected",
        }
        try:
            response = SESSION.get(
                f"{X_API_BASE}/tweets/search/recent",
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            log.warning("X recent-search query failed: %s", exc)
            continue

        users = {
            str(user.get("id")): user
            for user in payload.get("includes", {}).get("users", [])
        }

        for post in payload.get("data", []) or []:
            post_id = str(post.get("id") or "")
            text = sanitise_social_text(post.get("text", ""))
            created = parse_datetime(post.get("created_at"))
            if not post_id or not text or not is_fresh(created):
                continue
            if not is_local(text, "X public post"):
                continue

            user = users.get(str(post.get("author_id") or ""), {})
            username = str(user.get("username") or "").lstrip("@")
            username_lower = username.lower()
            official = username_lower in OFFICIAL_X_HANDLES

            referenced = post.get("referenced_tweets") or []
            is_reply = any(
                str(item.get("type")) == "replied_to" for item in referenced
                if isinstance(item, dict)
            )

            related_urls = []
            for url_item in (post.get("entities") or {}).get("urls", []) or []:
                expanded = (
                    url_item.get("expanded_url")
                    or url_item.get("unwound_url")
                    or url_item.get("url")
                )
                if expanded:
                    related_urls.append(str(expanded))

            metrics = post.get("public_metrics") or {}
            records_by_id[post_id] = {
                "record_id": f"x:{post_id}",
                "platform": "x",
                "kind": "reply" if is_reply else "post",
                "official": official,
                "source_name": (
                    OFFICIAL_X_HANDLES.get(username_lower)
                    if official else "Public X discussion"
                ),
                "text": text,
                "created_at": iso_utc(created),
                "url": (
                    f"https://x.com/{username}/status/{post_id}"
                    if username else f"https://x.com/i/web/status/{post_id}"
                ),
                "parent_url": "",
                "parent_text": "",
                "conversation_id": str(post.get("conversation_id") or ""),
                "participant_hash": participant_digest(
                    "x", str(post.get("author_id") or post_id)
                ),
                "related_urls": related_urls,
                "engagement": int(metrics.get("like_count") or 0)
                    + int(metrics.get("reply_count") or 0)
                    + int(metrics.get("retweet_count") or 0),
            }

    # Connect replies to conversation-root text when the root was also returned.
    for record in records_by_id.values():
        conversation_id = record.get("conversation_id")
        parent = records_by_id.get(str(conversation_id))
        if record.get("kind") == "reply" and parent:
            record["parent_text"] = parent.get("text", "")
            record["parent_url"] = parent.get("url", "")

    _X_SOCIAL_CACHE = list(records_by_id.values())
    log.info("X social records collected: %d", len(_X_SOCIAL_CACHE))
    return _X_SOCIAL_CACHE


def collect_facebook_social_records() -> list[dict[str, Any]]:
    global _FACEBOOK_SOCIAL_CACHE
    if _FACEBOOK_SOCIAL_CACHE is not None:
        return _FACEBOOK_SOCIAL_CACHE
    if not SOCIAL_CONTEXT_ENABLED or not FACEBOOK_PAGE_ACCESS_TOKEN:
        log.info(
            "Facebook comment correlation inactive: add the "
            "FACEBOOK_PAGE_ACCESS_TOKEN secret with the required Page access."
        )
        _FACEBOOK_SOCIAL_CACHE = []
        return _FACEBOOK_SOCIAL_CACHE

    records: list[dict[str, Any]] = []

    for page in PUBLIC_FACEBOOK_PAGES:
        handle = str(page["handle"]).strip("/")
        endpoint = f"https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/{handle}/posts"
        params = {
            "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
            "fields": "id,message,created_time,permalink_url,full_picture",
            "limit": "30",
        }
        try:
            response = SESSION.get(
                endpoint, params=params, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            log.warning(
                "Facebook Page source unavailable for %s: %s",
                page["name"], exc
            )
            continue

        for post in payload.get("data", []) or []:
            post_id = str(post.get("id") or "")
            message = sanitise_social_text(post.get("message", ""))
            created = parse_datetime(post.get("created_time"))
            permalink = canonicalise_url(str(post.get("permalink_url") or ""))
            if not post_id or not message or not is_fresh(created):
                continue
            if should_drop(message) or not is_local(message, page["name"], permalink):
                continue

            records.append({
                "record_id": f"facebook-post:{post_id}",
                "platform": "facebook",
                "kind": "official_post",
                "official": bool(page.get("official", True)),
                "source_name": page["name"],
                "text": message,
                "created_at": iso_utc(created),
                "url": permalink,
                "parent_url": "",
                "parent_text": "",
                "participant_hash": participant_digest(
                    "facebook-page", handle.lower()
                ),
                "related_urls": [permalink] if permalink else [],
                "engagement": 0,
                "image": str(post.get("full_picture") or ""),
            })

            if not FACEBOOK_COMMENTS_ENABLED:
                continue

            comment_endpoint = (
                f"https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/"
                f"{post_id}/comments"
            )
            comment_params = {
                "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
                "fields": (
                    "id,message,created_time,like_count,comment_count,from{id}"
                ),
                "filter": "stream",
                "limit": "100",
            }
            try:
                comment_response = SESSION.get(
                    comment_endpoint,
                    params=comment_params,
                    timeout=REQUEST_TIMEOUT,
                )
                comment_response.raise_for_status()
                comments = comment_response.json().get("data", []) or []
            except Exception as exc:
                log.info(
                    "Facebook comments unavailable for post %s: %s",
                    post_id, exc
                )
                comments = []

            for comment in comments:
                comment_id = str(comment.get("id") or "")
                comment_text = sanitise_social_text(comment.get("message", ""))
                comment_created = parse_datetime(comment.get("created_time"))
                if (
                    not comment_id
                    or not comment_text
                    or not is_fresh(comment_created)
                    or not public_reaction_is_usable(comment_text)
                ):
                    continue

                from_id = str((comment.get("from") or {}).get("id") or comment_id)
                records.append({
                    "record_id": f"facebook-comment:{comment_id}",
                    "platform": "facebook",
                    "kind": "public_comment",
                    "official": False,
                    "source_name": "Public Facebook comments",
                    "text": comment_text,
                    "created_at": iso_utc(comment_created),
                    "url": permalink,
                    "parent_url": permalink,
                    "parent_text": message,
                    "participant_hash": participant_digest(
                        "facebook", from_id
                    ),
                    "related_urls": [permalink] if permalink else [],
                    "engagement": int(comment.get("like_count") or 0)
                        + int(comment.get("comment_count") or 0),
                })

    _FACEBOOK_SOCIAL_CACHE = records
    log.info("Facebook social records collected: %d", len(records))
    return records


def official_social_records_to_candidates(
    records: list[dict[str, Any]]
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for record in records:
        if not record.get("official"):
            continue
        text = sanitise_social_text(record.get("text", ""))
        created = parse_datetime(record.get("created_at"))
        url = canonicalise_url(str(record.get("url") or ""))
        if not text or not url or not is_fresh(created):
            continue

        title = text.split(".")[0].strip()
        if len(title) < 35:
            title = text[:155].rsplit(" ", 1)[0]
        candidates.append(Candidate(
            source_name=str(record.get("source_name") or "Official social update"),
            source_url=url,
            source_title=title[:160],
            source_summary=text[:1000],
            source_published_at=iso_utc(created),
            area=detect_area(
                text,
                "rochdale",
                str(record.get("source_name") or ""),
                url,
            ),
            category=categorise(text),
            image_candidate_url=str(record.get("image") or ""),
            source_body_excerpt=text[:3500],
            source_kind="official_social",
        ))
    return candidates


def correlate_social_context(
    candidates: list[Candidate],
    records: list[dict[str, Any]],
) -> None:
    if not SOCIAL_CONTEXT_ENABLED or not records:
        return

    for candidate in candidates:
        source_text = (
            f"{candidate.source_title} {candidate.source_summary} "
            f"{candidate.source_body_excerpt}"
        )
        sensitive = is_sensitive(source_text, candidate.category)

        scored = []
        for record in records:
            score = social_record_score(candidate, record)
            if score > 0:
                scored.append((score, record))
        scored.sort(
            key=lambda item: (
                item[0],
                int(item[1].get("engagement") or 0),
            ),
            reverse=True,
        )

        official_updates = []
        public_reactions = []
        seen_official_urls = set()
        seen_participants = set()

        for score, record in scored:
            if record.get("official"):
                url = str(record.get("url") or "")
                if url in seen_official_urls:
                    continue
                seen_official_urls.add(url)
                official_updates.append({
                    "platform": record.get("platform"),
                    "kind": "official_update",
                    "source_name": record.get("source_name"),
                    "text": sanitise_social_text(record.get("text", "")),
                    "url": url,
                    "score": round(score, 3),
                })
                if len(official_updates) >= SOCIAL_MAX_OFFICIAL_UPDATES:
                    continue
            elif (
                not sensitive
                and candidate.category != "crime"
                and record.get("kind") in {"public_comment", "reply", "post"}
            ):
                participant = str(record.get("participant_hash") or "")
                if not participant or participant in seen_participants:
                    continue
                text = sanitise_social_text(record.get("text", ""))
                if not public_reaction_is_usable(text):
                    continue
                seen_participants.add(participant)
                public_reactions.append({
                    "platform": record.get("platform"),
                    "kind": "public_reaction",
                    "text": text,
                    "score": round(score, 3),
                })
                if len(public_reactions) >= SOCIAL_MAX_PUBLIC_REACTIONS:
                    continue

        if len(public_reactions) < SOCIAL_MIN_PUBLIC_REACTIONS:
            public_reactions = []

        # Official posts can also corroborate the main report.
        for item in official_updates:
            if item["url"] and all(
                existing.get("url") != item["url"]
                for existing in candidate.related_sources
            ):
                candidate.related_sources.append({
                    "name": item["source_name"],
                    "url": item["url"],
                    "title": item["text"][:160],
                    "summary": item["text"][:900],
                    "published_at": "",
                    "source_kind": "official_social",
                })

        candidate.social_context = official_updates + public_reactions


def collect_facebook_candidates() -> list[Candidate]:
    return official_social_records_to_candidates(
        collect_facebook_social_records()
    )


def collect_x_candidates() -> list[Candidate]:
    return official_social_records_to_candidates(
        collect_x_social_records()
    )


def collect_environment_agency_flood_candidates() -> list[Candidate]:
    """
    Fetch active flood alerts/warnings within 25 km of central Rochdale using
    the Environment Agency real-time flood-monitoring API.
    """
    endpoint = "https://environment.data.gov.uk/flood-monitoring/id/floods"
    params = {"lat": "53.6097", "long": "-2.1561", "dist": "25"}
    try:
        response = SESSION.get(endpoint, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log.warning("Environment Agency flood feed unavailable: %s", exc)
        return []

    candidates: list[Candidate] = []
    for item in payload.get("items", []):
        severity_level = int(item.get("severityLevel") or 4)
        if severity_level >= 4:
            continue
        changed = parse_datetime(
            item.get("timeMessageChanged")
            or item.get("timeSeverityChanged")
            or item.get("timeRaised")
        ) or utc_now()
        area_name = strip_markdown(
            item.get("eaAreaName")
            or item.get("description")
            or item.get("floodArea", {}).get("label")
            or "Rochdale flood alert"
        )
        message = strip_markdown(item.get("message") or item.get("description") or "")
        title = f"{item.get('severity', 'Flood alert')}: {area_name}"
        source_url = str(item.get("@id") or endpoint).replace("http://", "https://")
        text = f"{title} {message}"
        if not is_local(
            text,
            "Environment Agency flood-monitoring API",
            source_url,
        ):
            continue

        detected_area = detect_area(text)
        if not detected_area:
            continue

        candidates.append(Candidate(
            source_name="Environment Agency flood-monitoring API",
            source_url=source_url,
            source_title=title[:160],
            source_summary=message[:900],
            source_published_at=iso_utc(changed),
            area=detected_area,
            category="environment",
            source_body_excerpt=message[:3500],
        ))
    return candidates


def candidate_related_record(candidate: Candidate) -> dict[str, str]:
    return {
        "name": candidate.source_name,
        "url": candidate.source_url,
        "title": candidate.source_title,
        "summary": candidate.source_summary[:1200],
        "published_at": candidate.source_published_at,
        "source_kind": candidate.source_kind,
    }


def deduplicate_and_cross_reference(
    candidates: Iterable[Candidate],
) -> list[Candidate]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            authority_score(item),
            item.source_published_at,
        ),
        reverse=True,
    )
    primaries: list[Candidate] = []
    seen_urls: set[str] = set()

    for candidate in ordered:
        if source_is_denied(candidate.source_name, candidate.source_url):
            continue
        if not candidate.area:
            continue

        candidate.related_sources = [
            item for item in candidate.related_sources
            if not source_is_denied(
                item.get("name", ""),
                item.get("url", ""),
            )
        ]

        url_key = canonicalise_url(candidate.source_url)
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)

        matched = None
        for primary in primaries:
            if same_story(candidate, primary):
                matched = primary
                break

        if matched is None:
            candidate.story_key = build_story_key(candidate)
            primaries.append(candidate)
            continue

        matched.related_sources.append(candidate_related_record(candidate))
        matched.story_key = build_story_key(matched)

    return primaries


def load_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def recent_existing_articles() -> list[dict[str, Any]]:
    kept = []
    for article in load_json_list(OUTPUT_FILE):
        source_name = str(article.get("source_name") or "")
        source_url = str(article.get("source_url") or "")
        if source_is_denied(source_name, source_url):
            continue

        published = parse_datetime(article.get("published_at"))
        source_kind = str(article.get("source_kind") or "article")
        event_start = parse_datetime(article.get("event_start_at"))

        keep = (
            is_fresh(published)
            or (source_kind == "event" and event_is_current_or_future(event_start))
            or (source_kind == "live" and is_current_uk_day(published))
        )
        if keep and article_is_local(article):
            article["title"] = strip_markdown(article.get("title"))
            article["excerpt"] = strip_markdown(article.get("excerpt"))
            kept.append(article)
    return dedupe_article_records(kept)

def _source_image_allowed(candidate: Candidate) -> bool:
    if not candidate.image_candidate_url:
        return False
    source_domain = domain_of(candidate.source_url)
    if candidate.source_kind == "event" and source_domain == "facebook.com":
        return FACEBOOK_EVENT_IMAGE_REUSE
    return USE_SOURCE_IMAGES and source_domain in IMAGE_REUSE_SOURCE_DOMAINS


def cache_source_image(candidate: Candidate, category: str) -> tuple[str, str]:
    fallback = CATEGORY_STOCK_IMAGES.get(category, CATEGORY_STOCK_IMAGES["news"])
    if not _source_image_allowed(candidate):
        return fallback, "Rochdale Daily category image"

    target_name = f"{stable_id(candidate.source_url)}.jpg"
    relative_path = f"assets/img/generated/{target_name}"
    target_path = GENERATED_IMAGE_DIR / target_name
    if target_path.exists() and target_path.stat().st_size > 5000:
        return relative_path, candidate.source_name

    try:
        response = SESSION.get(
            candidate.image_candidate_url,
            timeout=REQUEST_TIMEOUT,
            stream=True,
            headers={"Referer": candidate.source_url},
        )
        response.raise_for_status()
        content = response.content
        if len(content) > 10_000_000:
            raise ValueError("image exceeded 10 MB")
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image).convert("RGB")
        image = ImageOps.fit(image, (1200, 675), method=Image.Resampling.LANCZOS)
        image.save(target_path, format="JPEG", quality=86, optimize=True)
        return relative_path, candidate.source_name
    except (requests.RequestException, OSError, ValueError, UnidentifiedImageError) as exc:
        log.info("Could not cache source image for %s: %s", candidate.source_url, exc)
        return fallback, "Rochdale Daily category image"


def source_image(candidate: Candidate, category: str) -> tuple[str, str]:
    return cache_source_image(candidate, category)

POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)
ADDRESS_RE = re.compile(
    r"\b\d{1,4}[A-Za-z]?\s+(?:[A-Z][a-z'-]+\s+){0,4}"
    r"(?:Street|St|Road|Rd|Lane|Ln|Drive|Dr|Avenue|Ave|Close|Court|Way|Crescent|Place|Terrace|Gardens|Grove)\b",
    re.IGNORECASE,
)
PERSON_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr)?\s*([A-Z][a-z'-]+(?:\s+[A-Z][a-z'-]+){1,2})\b")
NAME_EXCLUSIONS = {
    "Greater Manchester", "Rochdale Daily", "Rochdale Council", "Rochdale Borough Council",
    "Greater Manchester Police", "Manchester Evening News",
    "Rochdale AFC", "Rochdale Hornets", "National Highways", "Bee Network",
    "Northern Care Alliance", "Pennine Care", "Hopwood Hall", "United Kingdom",
}

def source_person_names(text: str) -> set[str]:
    found = set()
    for match in PERSON_RE.finditer(text):
        name = normalise_ws(match.group(1))
        if name not in NAME_EXCLUSIONS and not any(place.lower() in name.lower() for place in LOCAL_TERMS):
            found.add(name)
    return found

def anonymise_output(text: str, source_text: str) -> str:
    result = POSTCODE_RE.sub("the Rochdale area", str(text or ""))
    result = ADDRESS_RE.sub("a location in the Rochdale borough", result)
    for name in sorted(source_person_names(source_text), key=len, reverse=True):
        result = re.sub(rf"\b{re.escape(name)}\b", "an individual", result, flags=re.IGNORECASE)
    result = re.sub(r"\b(?:Mr|Mrs|Ms|Miss)\s+[A-Z][a-z'-]+\b", "the individual", result)
    return strip_markdown(result)

def default_legal_disclaimer(sensitive: bool) -> str:
    if sensitive:
        return (
            "This report is based on information published by identified public sources. "
            "No finding of guilt should be inferred from an arrest, allegation or charge. "
            "Anyone accused of an offence is presumed innocent unless and until convicted. "
            "Rochdale Daily does not publish suspected offenders' names or exact residential addresses "
            "in automatically produced reports, and the article may be updated as verified information changes."
        )
    return (
        "This article was compiled from identified public sources and may be updated when further verified "
        "information becomes available."
    )

def source_led_draft(candidate: Candidate, sensitive: bool) -> dict[str, Any] | None:
    source_text = normalise_ws(
        f"{candidate.source_summary} {candidate.source_body_excerpt}"
    )
    if len(source_text) < 45:
        return None

    clean_summary = strip_markdown(candidate.source_summary or candidate.source_body_excerpt)
    clean_body = strip_markdown(candidate.source_body_excerpt)
    if sensitive:
        clean_summary = anonymise_output(clean_summary, source_text)
        clean_body = anonymise_output(clean_body, source_text)

    paragraphs: list[str] = []
    if clean_summary:
        paragraphs.append(clean_summary[:850])
    if clean_body and clean_body.lower() != clean_summary.lower():
        paragraphs.append(clean_body[:900])

    if candidate.related_sources:
        paragraphs.append(
            f"The update has also been cross-referenced against "
            f"{len(candidate.related_sources)} additional public source"
            f"{'s' if len(candidate.related_sources) != 1 else ''}."
        )
    else:
        paragraphs.append(
            f"The information was published by {candidate.source_name}. "
            "Readers can use the source link for the original notice and any later amendments."
        )

    paragraphs.append(
        "Rochdale Daily will update this report if the identified source publishes "
        "material new information."
    )
    paragraphs = [p for p in paragraphs if p][:6]
    while len(paragraphs) < 3:
        paragraphs.append(
            "The article remains open to correction and further verified information."
        )

    return {
        "publishable": True,
        "title": candidate.source_title,
        "excerpt": clean_summary[:320] or clean_body[:320],
        "paragraphs": paragraphs,
        "category": candidate.category,
        "area": candidate.area,
        "legal_disclaimer": default_legal_disclaimer(sensitive),
        "right_to_reply": (
            f"Anyone directly affected may request a correction or right of reply "
            f"by emailing {RIGHT_TO_REPLY_EMAIL}."
        ),
        "community_reaction": "",
        "social_context_used": False,
        "reason": "Conservative source-led brief used.",
    }


def rewrite_candidate(candidate: Candidate, client: OpenAI | None) -> dict[str, Any] | None:
    source_records = [{
        "name": candidate.source_name,
        "url": candidate.source_url,
        "title": candidate.source_title,
        "summary": candidate.source_summary,
        "body_excerpt": candidate.source_body_excerpt,
        "published_at": candidate.source_published_at,
        "source_kind": candidate.source_kind,
        "event_start_at": candidate.event_start_at,
        "event_end_at": candidate.event_end_at,
        "event_location": candidate.event_location,
    }] + candidate.related_sources[:8]

    social_context = candidate.social_context[:(
        SOCIAL_MAX_OFFICIAL_UPDATES + SOCIAL_MAX_PUBLIC_REACTIONS
    )]

    source_text = normalise_ws(" ".join(
        f"{item.get('title','')} {item.get('summary','')} {item.get('body_excerpt','')}"
        for item in source_records
    ))[:12000]
    sensitive = is_sensitive(source_text, candidate.category)

    if client is None:
        draft = source_led_draft(candidate, sensitive)
        if draft is None:
            return None
    else:
        system_message = (
            "You are the sub-editor for Rochdale Daily, an independent UK local-news publication. "
            "Write an original local article using only the supplied source records. Combine corroborating "
            "details where sources agree, but never invent facts, dates, quotations, prices, statistics, "
            "organisations, contact details or local impact. Do not claim the article is fact-checked. "
            "Do not output Markdown, HTML, hashtags or links. Use neutral UK English and short paragraphs. "
            "For crime, court, safeguarding, deaths, allegations or active investigations: omit every "
            "suspect, defendant, victim, witness and private individual's name; omit house numbers, exact "
            "residential addresses and postcodes; do not mention previous convictions; do not speculate "
            "about guilt, motive or evidence; do not identify sexual-offence complainants or anyone under 18; "
            "and use only confirmed basic facts, official public-safety advice and procedural status. "
            "A legal disclaimer is not permission to publish unsafe facts. If safe anonymisation is impossible "
            "or the source material is too thin or contradictory, set publishable to false. "
            "Never infer a Rochdale location from a person's surname. Middleton, Healey, Wardle, "
            "Bamford, Norden, Hopwood, Birch, Summit and Syke may be names or ordinary words. "
            "Treat them as places only when the source explicitly uses geographical wording such as "
            "'in Middleton', 'Middleton residents', 'Wardle village' or a local postcode. "
            "Langley is not an accepted standalone Rochdale locality in this system. "
            "Official social posts may corroborate facts only when they come from an identified public body "
            "or organisation and agree with the primary records. Public comments and X replies are never "
            "evidence of what happened. Do not quote or identify commenters. Use public reaction only to "
            "summarise a recurring practical question, concern or experience supported by at least three "
            "distinct participants. Do not use public comments at all for crime, court, safeguarding, death, "
            "sexual-offence, child-related or other sensitive stories. The community_reaction field must be "
            "empty when those conditions are not met."
        )
        user_message = json.dumps({
            "primary_source": candidate.source_name,
            "primary_url": candidate.source_url,
            "source_published_at": candidate.source_published_at,
            "detected_area": candidate.area,
            "detected_category": candidate.category,
            "sensitive_story": sensitive,
            "source_records": source_records,
            "social_context": social_context,
            "social_context_policy": {
                "official_updates": (
                    "May be used as attributed corroboration only when consistent "
                    "with the main source records."
                ),
                "public_reactions": (
                    "Unverified reaction only. Never use as factual evidence, "
                    "never identify or quote a commenter, and only summarise a "
                    "theme supported by at least three distinct participants."
                ),
                "sensitive_stories": (
                    "Public reactions must not be used for sensitive stories."
                ),
            },
            "requested_style": (
                "Headline under 150 characters; standfirst of 35-65 words; 4-7 paragraphs. "
                "Add useful background only when it is explicitly present in the supplied records. "
                "For event listings, clearly state the supplied date, time, location, ticket or access "
                "information, age suitability and booking details only when those facts appear in the "
                "source records. Never invent missing event details. Explain practical local relevance "
                "without exaggeration."
            ),
            "required_right_to_reply": (
                f"Anyone directly affected may request a correction or right of reply by emailing "
                f"{RIGHT_TO_REPLY_EMAIL}."
            ),
        }, ensure_ascii=False)
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_schema", "json_schema": ARTICLE_SCHEMA},
                temperature=0.15,
                max_tokens=1400,
            )
            draft = json.loads(response.choices[0].message.content or "{}")
        except Exception as exc:
            log.warning("OpenAI rewrite failed; using source-led brief for %s: %s", candidate.source_url, exc)
            draft = source_led_draft(candidate, sensitive)

    if not draft or not bool(draft.get("publishable")):
        draft = source_led_draft(candidate, sensitive)
        if draft is None:
            return None

    title = strip_markdown(draft.get("title"))[:160]
    excerpt = strip_markdown(draft.get("excerpt"))[:360]
    paragraphs = [
        strip_markdown(item)
        for item in draft.get("paragraphs", [])
        if strip_markdown(item)
    ][:8]
    community_reaction = strip_markdown(
        draft.get("community_reaction", "")
    )[:500]
    social_context_used = bool(draft.get("social_context_used"))
    category = str(draft.get("category") or candidate.category)
    area = str(draft.get("area") or candidate.area)
    if category not in CATEGORY_STOCK_IMAGES:
        category = candidate.category if candidate.category in CATEGORY_STOCK_IMAGES else "news"
    if area not in AREA_KEYWORDS:
        area = candidate.area if candidate.area in AREA_KEYWORDS else "rochdale"

    public_reaction_count = sum(
        1 for item in candidate.social_context
        if item.get("kind") == "public_reaction"
    )
    official_social_count = sum(
        1 for item in candidate.social_context
        if item.get("kind") == "official_update"
    )

    if sensitive:
        title = anonymise_output(title, source_text)
        excerpt = anonymise_output(excerpt, source_text)
        paragraphs = [
            anonymise_output(paragraph, source_text)
            for paragraph in paragraphs
        ]
        paragraphs = [p for p in paragraphs if p]
        community_reaction = ""
        social_context_used = False

    if public_reaction_count < SOCIAL_MIN_PUBLIC_REACTIONS:
        community_reaction = ""
        if official_social_count == 0:
            social_context_used = False

    if community_reaction:
        community_reaction = anonymise_output(
            community_reaction,
            " ".join(
                item.get("text", "")
                for item in candidate.social_context
            ),
        )
        paragraphs.append(f"Community reaction: {community_reaction}")

    if not title or not excerpt or len(paragraphs) < 3:
        return None

    image_url, image_credit = source_image(candidate, category)
    source_urls = [candidate.source_url] + [item["url"] for item in candidate.related_sources[:11] if item.get("url")]
    source_names = [candidate.source_name] + [item["name"] for item in candidate.related_sources[:11] if item.get("name")]

    legal_disclaimer = strip_markdown(draft.get("legal_disclaimer")) or default_legal_disclaimer(sensitive)
    right_to_reply = strip_markdown(draft.get("right_to_reply")) or (
        f"Anyone directly affected may request a correction or right of reply by emailing {RIGHT_TO_REPLY_EMAIL}."
    )

    if sensitive:
        legal_disclaimer = anonymise_output(legal_disclaimer, source_text)
        right_to_reply = anonymise_output(right_to_reply, source_text)

    return {
        "id": stable_id(candidate.source_url),
        "story_key": candidate.story_key or build_story_key(candidate),
        "title": title,
        "slug": make_slug(title),
        "excerpt": excerpt,
        "content_html": "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs),
        "area": area,
        "category": category,
        "types": [category],
        "published_at": candidate.source_published_at,
        "scraped_at": iso_utc(utc_now()),
        "image_url": image_url,
        "image_credit": image_credit,
        "source_image_candidate_url": (
            candidate.image_candidate_url if candidate.source_kind == "event" else ""
        ),
        "source_image_reuse_status": (
            "enabled-by-publisher"
            if candidate.source_kind == "event" and FACEBOOK_EVENT_IMAGE_REUSE
            else "permission-required"
            if candidate.source_kind == "event" and candidate.image_candidate_url
            else ""
        ),
        "event_start_at": candidate.event_start_at,
        "event_end_at": candidate.event_end_at,
        "event_location": candidate.event_location,
        "source_kind": candidate.source_kind,
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "source_names": source_names,
        "source_urls": source_urls,
        "source_count": len(source_urls),
        "social_context_used": social_context_used,
        "social_reaction_count": public_reaction_count,
        "official_social_update_count": official_social_count,
        "social_platforms": sorted({
            str(item.get("platform"))
            for item in candidate.social_context
            if item.get("platform")
        }),
        "social_context_note": (
            "Public reactions are anonymised, aggregated and not treated as "
            "evidence. Raw comments are not stored in the public article feed."
            if social_context_used else ""
        ),
        "sensitive_story": sensitive,
        "police_matter": category == "crime",
        "legal_disclaimer": legal_disclaimer,
        "right_to_reply": right_to_reply,
        "byline": "Rochdale Daily Newsdesk",
        "status": "published",
    }

def write_json_atomic(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)

def safe_collect(
    name: str,
    collector: Any,
    collector_counts: dict[str, int],
    collector_errors: dict[str, str],
) -> list[Candidate]:
    try:
        items = collector()
        collector_counts[name] = len(items)
        return items
    except Exception as exc:
        log.exception("Collector failed: %s", name)
        collector_counts[name] = 0
        collector_errors[name] = str(exc)
        return []


def main() -> int:
    log.info("Starting Rochdale Daily 15-minute pipeline")
    existing = recent_existing_articles()

    existing_by_story = {
        build_story_key(item): item
        for item in existing
    }

    collector_counts: dict[str, int] = {}
    collector_errors: dict[str, str] = {}

    x_social_records = collect_x_social_records()
    facebook_social_records = collect_facebook_social_records()

    batches = {
        "rss_and_google_news": safe_collect(
            "rss_and_google_news",
            collect_rss_candidates,
            collector_counts,
            collector_errors,
        ),
        "website_discovery": safe_collect(
            "website_discovery",
            collect_discovery_candidates,
            collector_counts,
            collector_errors,
        ),
        "live_service_pages": safe_collect(
            "live_service_pages",
            collect_live_page_candidates,
            collector_counts,
            collector_errors,
        ),
        "facebook_events": safe_collect(
            "facebook_events",
            collect_facebook_event_discovery_candidates,
            collector_counts,
            collector_errors,
        ),
        "facebook_official": safe_collect(
            "facebook_official",
            collect_facebook_candidates,
            collector_counts,
            collector_errors,
        ),
        "x_official": safe_collect(
            "x_official",
            collect_x_candidates,
            collector_counts,
            collector_errors,
        ),
        "environment_agency": safe_collect(
            "environment_agency",
            collect_environment_agency_flood_candidates,
            collector_counts,
            collector_errors,
        ),
    }

    raw_candidates = [
        candidate
        for batch in batches.values()
        for candidate in batch
    ]
    candidates = deduplicate_and_cross_reference(raw_candidates)

    correlate_social_context(
        candidates,
        x_social_records + facebook_social_records,
    )
    log.info(
        "Candidate volume: %d raw items -> %d story clusters",
        len(raw_candidates),
        len(candidates),
    )

    api_key = os.getenv("OPENAI_API_KEY")
    run_limit = (
        MAX_AI_ARTICLES_INITIAL
        if len(existing) < MIN_LIVE_STORIES
        else MAX_AI_ARTICLES_PER_RUN
    )

    selected_candidates: list[Candidate] = []
    for candidate in candidates:
        candidate.story_key = candidate.story_key or build_story_key(candidate)
        existing_article = existing_by_story.get(candidate.story_key)

        if existing_article is None:
            selected_candidates.append(candidate)
        else:
            known_urls = {
                canonicalise_url(url)
                for url in existing_article.get("source_urls", [])
                if url
            }
            primary_url = canonicalise_url(
                str(existing_article.get("source_url") or "")
            )
            if primary_url:
                known_urls.add(primary_url)

            candidate_urls = {
                canonicalise_url(candidate.source_url),
                *{
                    canonicalise_url(item.get("url", ""))
                    for item in candidate.related_sources
                    if item.get("url")
                },
            }
            if candidate_urls - known_urls:
                # Rebuild an evolving story when a genuinely new corroborating
                # source or official update has appeared.
                selected_candidates.append(candidate)

        if len(selected_candidates) >= run_limit:
            break

    new_articles: list[dict[str, Any]] = []
    skipped = 0

    def process_candidate(candidate: Candidate) -> dict[str, Any] | None:
        worker_client = OpenAI(api_key=api_key) if api_key else None
        return rewrite_candidate(candidate, worker_client)

    with ThreadPoolExecutor(max_workers=max(1, AI_WORKERS)) as executor:
        future_map = {
            executor.submit(process_candidate, candidate): candidate
            for candidate in selected_candidates
        }
        for future in as_completed(future_map):
            candidate = future_map[future]
            try:
                article = future.result()
            except Exception as exc:
                log.exception(
                    "Rewrite failed for %s: %s",
                    candidate.source_url,
                    exc,
                )
                skipped += 1
                continue
            if article:
                new_articles.append(article)
            else:
                skipped += 1

    ai_count = len(selected_candidates)

    merged: dict[str, dict[str, Any]] = {}
    for article in existing + new_articles:
        story_key = build_story_key(article)
        article["story_key"] = story_key
        if story_key in merged:
            merged[story_key] = merge_article_records(
                merged[story_key],
                article,
            )
        else:
            merged[story_key] = article

    publishable_values = []
    for article in merged.values():
        if source_is_denied(
            str(article.get("source_name") or ""),
            str(article.get("source_url") or ""),
        ):
            continue

        published_at = parse_datetime(article.get("published_at"))
        source_kind = str(article.get("source_kind") or "article")
        event_start = parse_datetime(article.get("event_start_at"))

        if not article_is_local(article):
            log.warning(
                "Rejected non-local article after rewrite: %s",
                article.get("title"),
            )
            continue

        if (
            is_fresh(published_at)
            or (
                source_kind == "event"
                and event_is_current_or_future(event_start)
            )
            or (
                source_kind == "live"
                and is_current_uk_day(published_at)
            )
        ):
            publishable_values.append(article)

    published = sorted(
        dedupe_article_records(publishable_values),
        key=lambda article: (
            parse_datetime(article.get("published_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )[:MAX_PUBLISHED_ARTICLES]

    write_json_atomic(OUTPUT_FILE, published)

    source_counts: dict[str, int] = {}
    for candidate in raw_candidates:
        source_counts[candidate.source_name] = (
            source_counts.get(candidate.source_name, 0) + 1
        )

    write_json_atomic(STATUS_FILE, {
        "last_run_at": iso_utc(utc_now()),
        "raw_candidates": len(raw_candidates),
        "candidate_clusters": len(candidates),
        "duplicates_merged": max(0, len(raw_candidates) - len(candidates)),
        "attempted_rewrites": ai_count,
        "new_articles": len(new_articles),
        "live_articles": len(published),
        "skipped": skipped,
        "collector_counts": collector_counts,
        "collector_errors": collector_errors,
        "source_counts": dict(sorted(
            source_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )),
        "openai_enabled": bool(api_key),
        "same_day_only": SAME_DAY_ONLY,
        "prohibited_sources": [
            "rochdaletimes.co.uk",
            "rochdaleonline.co.uk",
        ],
        "selected_story_keys": [
            candidate.story_key for candidate in selected_candidates
        ],
        "selected_candidate_urls": [
            candidate.source_url for candidate in selected_candidates
        ],
        "x_social_records": len(x_social_records),
        "facebook_social_records": len(facebook_social_records),
        "stories_with_social_context": sum(
            1 for candidate in candidates if candidate.social_context
        ),
        "x_enabled": bool(X_BEARER_TOKEN),
        "facebook_comments_enabled": bool(
            FACEBOOK_PAGE_ACCESS_TOKEN and FACEBOOK_COMMENTS_ENABLED
        ),
        "locality_rule": (
            "Single-word locality names require geographical context; "
            "person surnames are not accepted as locations."
        ),
        "story_identity_rule": (
            "Stories are clustered by named entities, subject terms, area, "
            "category and date; interviews/reactions are merged into the "
            "underlying announcement where they describe the same event."
        ),
    })

    log.info(
        "Complete: %d live articles, %d new, %d AI/fallback attempts, "
        "%d skipped, %d duplicates merged",
        len(published),
        len(new_articles),
        ai_count,
        skipped,
        max(0, len(raw_candidates) - len(candidates)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
