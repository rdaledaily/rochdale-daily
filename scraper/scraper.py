"""
Rochdale Daily autonomous local-news pipeline.

The pipeline:
- checks public RSS feeds, public news pages, selected local organisations,
  social accounts, live service pages and Google News RSS searches every run;
- searches the borough, townships, wards and named neighbourhoods;
- keeps the original source date and rejects stale, undated and non-local material;
- cross-references similar reports before asking OpenAI for an original article;
- publishes crime, police and court material automatically when it passes the same
  source, date, locality, duplication and minimum-content checks as other stories;
- falls back to an attributed source-led brief when an AI rewrite is unavailable,
  invalid or declined, so crime candidates are not silently discarded;
- protects identities that must not be exposed, including children and sexual-
  offence complainants, without putting ordinary crime reports into an approval queue;
- adds a standing correction and right-to-reply invitation;
- uses locally stored category artwork by default, avoiding unlicensed image reuse.

The pipeline does not use a crime review queue. All published facts remain attributed
and must come from the cited source records.
"""
from __future__ import annotations
from source_presentation import clean_candidate_public_text, is_subtle_source, sanitise_article
from house_style import STYLE_VERSION
from editorial_upgrade import (
    SERVICE_SENTENCE_RE,
    SYMPATHY_SENTENCE_RE,
    article_word_count as editorial_word_count,
    compact_records as editorial_compact_records,
    deterministic_category as editorial_category,
    enrich_records as editorial_enrich_records,
    quality_issues as editorial_quality_issues,
    request_article as editorial_request_article,
    strip_service_furniture,
)
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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from openai import OpenAI
from PIL import Image, ImageOps, UnidentifiedImageError
from dateparser.search import search_dates
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from search_queries import build_search_query_specs
from locations import LOCATION_BY_SLUG
from food_hygiene import fetch_recent_low_ratings, rating_article_fields
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / 'articles.json'
LOG_FILE = ROOT / 'scraper' / 'scraper.log'
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
AI_REWRITE_REQUIRED = False
MAX_NEWS_AGE_HOURS = max(168, int(os.getenv('MAX_NEWS_AGE_HOURS', '168')))
# articles.json is the permanent archive. Freshness only controls discovery/front-page
# selection; it must never prune previously published records.
RETENTION_DAYS = None
MAX_PUBLISHED_ARTICLES = None
MAX_AI_ARTICLES_PER_RUN = int(os.getenv('MAX_AI_ARTICLES_PER_RUN', '30'))
MAX_AI_ARTICLES_INITIAL = int(os.getenv('MAX_AI_ARTICLES_INITIAL', '60'))
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '12'))
GOOGLE_NEWS_REQUEST_DELAY_SECONDS = float(os.getenv('GOOGLE_NEWS_REQUEST_DELAY_SECONDS', '1.5'))
DISCOVERY_LINKS_PER_SOURCE = int(os.getenv('DISCOVERY_LINKS_PER_SOURCE', '40'))
RSS_ITEMS_PER_SOURCE = int(os.getenv('RSS_ITEMS_PER_SOURCE', '100'))
GOOGLE_SEARCH_QUERY_LIMIT = int(os.getenv('GOOGLE_SEARCH_QUERY_LIMIT', '128'))
DISCOVERY_PAGE_LIMIT = int(os.getenv('DISCOVERY_PAGE_LIMIT', '3'))
DISCOVERY_WORKERS = int(os.getenv('DISCOVERY_WORKERS', '16'))
AI_WORKERS = int(os.getenv('AI_WORKERS', '6'))
MIN_LIVE_STORIES = int(os.getenv('MIN_LIVE_STORIES', '30'))
MIN_BALANCED_SELECTION_LIMIT = int(os.getenv('MIN_BALANCED_SELECTION_LIMIT', '40'))
MAX_SELECTED_PER_SOURCE = max(12, int(os.getenv('MAX_SELECTED_PER_SOURCE', '12')))
MAX_SELECTED_PER_CATEGORY = max(20, int(os.getenv('MAX_SELECTED_PER_CATEGORY', '20')))
HTTP_POOL_CONNECTIONS = int(os.getenv('HTTP_POOL_CONNECTIONS', '64'))
HTTP_POOL_MAXSIZE = int(os.getenv('HTTP_POOL_MAXSIZE', '64'))
STATUS_FILE = ROOT / 'scraper_status.json'
GENERATED_IMAGE_DIR = ROOT / 'assets' / 'img' / 'generated'
GENERATED_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
RESPECT_ROBOTS = True
USE_SOURCE_IMAGES = os.getenv('USE_SOURCE_IMAGES', 'false').lower() in {'1', 'true', 'yes'}
RIGHT_TO_REPLY_EMAIL = os.getenv('RIGHT_TO_REPLY_EMAIL', 'news@rochdaledaily.co.uk')
UK_TZ = ZoneInfo('Europe/London')
SAME_DAY_ONLY = False
SOURCE_DENY_DOMAINS = {'rochdaletimes.co.uk', 'rochdaleonline.co.uk', 'pressreader.com', 'rochdaleobserver.co.uk'}
SOURCE_DENY_NAMES = {'rochdale times', 'rochdale times paper', 'rochdale online', 'rochdale observer', 'pressreader'}
LIVE_SOURCE_NAMES = {'rochdale council service updates', 'tfgm travel alerts', 'northern service updates', 'united utilities incidents', 'environment agency flood-monitoring api'}
FACEBOOK_EVENTS_DISCOVERY_URL = os.getenv('FACEBOOK_EVENTS_DISCOVERY_URL', 'https://www.facebook.com/events/?date_filter_option=ANY_DATE&discover_tab=CUSTOM&location_id=108023932551149').strip()
FACEBOOK_EVENTS_BROWSER_ENABLED = os.getenv('FACEBOOK_EVENTS_BROWSER_ENABLED', 'true').lower() not in {'0', 'false', 'no', 'off'}
FACEBOOK_EVENTS_MAX = int(os.getenv('FACEBOOK_EVENTS_MAX', '18'))
FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS = int(os.getenv('FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS', '30000'))
FACEBOOK_EVENT_IMAGE_REUSE = os.getenv('FACEBOOK_EVENT_IMAGE_REUSE', 'false').lower() in {'1', 'true', 'yes'}
IMAGE_REUSE_SOURCE_DOMAINS = {item.strip().lower() for item in os.getenv('IMAGE_REUSE_SOURCE_DOMAINS', 'rochdale.gov.uk,gmp.police.uk,manchesterfire.gov.uk,rochdaleafc.co.uk,hornetsrugbyleague.co.uk,tfgm.com,gmca.gov.uk,nationalhighways.co.uk,hopwood.ac.uk,northerncarealliance.nhs.uk,penninecare.nhs.uk,rochvalleyradio.com,actiontogether.org.uk,yourtrustrochdale.co.uk,facebook.com').split(',') if item.strip()}
RSS_SOURCES = [{'name': 'BBC Manchester', 'url': 'https://feeds.bbci.co.uk/news/england/manchester/rss.xml', 'default_area': 'rochdale'}, {'name': 'Manchester Evening News — Rochdale', 'url': 'https://www.manchestereveningnews.co.uk/all-about/rochdale?service=rss', 'section_url': 'https://www.manchestereveningnews.co.uk/all-about/rochdale', 'default_area': 'rochdale', 'rss_only': True, 'publisher_domain': 'manchestereveningnews.co.uk'}, {'name': 'Greater Manchester Fire and Rescue Service', 'url': 'https://www.manchesterfire.gov.uk/news-events/news/feed/', 'default_area': 'rochdale'}, {'name': 'Rochdale AFC', 'url': 'https://www.rochdaleafc.co.uk/news/feed', 'default_area': 'rochdale'}]
DISCOVERY_PAGES = [{'name': 'Rochdale Council Events', 'url': 'https://www.rochdale.gov.uk/events', 'default_area': 'rochdale', 'link_pattern': '/events/event/'}, {'name': 'Rochdale Council Your Events', 'url': 'https://www.rochdale.gov.uk/yourevents', 'default_area': 'rochdale', 'link_pattern': '/events/|/directory-record/'}, {'name': 'Rochdale Development Agency', 'url': 'https://investinrochdale.co.uk/news', 'default_area': 'rochdale', 'link_pattern': '/news/'}, {'name': 'Visit Rochdale', 'url': 'https://www.visitrochdale.com/whats-on', 'default_area': 'rochdale', 'link_pattern': '/whats-on/'}, {'name': 'Rochdale Town Hall Events', 'url': 'https://www.rochdaletownhall.co.uk/events?page=1', 'default_area': 'rochdale', 'link_pattern': '/events/event/'}, {'name': 'Action Together Rochdale News', 'url': 'https://www.actiontogether.org.uk/rochdale-news', 'default_area': 'rochdale', 'link_pattern': '/'}, {'name': 'Action Together Latest News', 'url': 'https://www.actiontogether.org.uk/whats-happening', 'default_area': 'rochdale', 'link_pattern': '/'}, {'name': 'Your Trust Rochdale News', 'url': 'https://www.yourtrustrochdale.co.uk/news/', 'default_area': 'rochdale', 'link_pattern': '/news/|/category/news/'}, {'name': 'Your Trust Rochdale News Archive', 'url': 'https://www.yourtrustrochdale.co.uk/category/news/', 'default_area': 'rochdale', 'link_pattern': '/'}, {'name': 'Roch Valley Radio Local News', 'url': 'https://www.rochvalleyradio.com/news/local-news/', 'default_area': 'rochdale', 'default_category': 'news', 'trusted_local': True, 'link_pattern': '/news/local-news/'}, {'name': 'Roch Valley Radio Notices', 'url': 'https://www.rochvalleyradio.com/news/notices/', 'default_area': 'rochdale', 'default_category': 'community', 'trusted_local': True, 'link_pattern': '/news/notices/|/news/local-news/'}, {'name': 'Greater Manchester Police', 'url': 'https://www.gmp.police.uk/news/', 'default_area': 'rochdale', 'default_category': 'crime', 'page_limit': 12, 'link_pattern': '/news/'}, {'name': 'Greater Manchester Fire and Rescue Service', 'url': 'https://www.manchesterfire.gov.uk/news-events/news/', 'default_area': 'rochdale', 'link_pattern': '/news'}, {'name': 'TfGM Newsroom', 'url': 'https://news.tfgm.com/', 'default_area': 'rochdale', 'link_pattern': '/press-releases/'}, {'name': 'TfGM Travel Alerts', 'url': 'https://tfgm.com/travel-updates/travel-alerts', 'default_area': 'rochdale', 'link_pattern': '/travel-updates/'}, {'name': 'Northern News', 'url': 'https://media.northernrailway.co.uk/news/', 'default_area': 'rochdale', 'link_pattern': '/news/'}, {'name': 'Northern Service Updates', 'url': 'https://www.northernrailway.co.uk/service-updates', 'default_area': 'rochdale', 'link_pattern': '/service-updates|/news/'}, {'name': 'National Highways North West', 'url': 'https://nationalhighways.co.uk/our-roads/north-west/north-west-maintenance-schemes/', 'default_area': 'rochdale', 'link_pattern': '/'}, {'name': 'United Utilities Incidents', 'url': 'https://www.unitedutilities.com/emergencies/up-my-street/', 'default_area': 'rochdale', 'link_pattern': '/emergencies/|/incident/'}, {'name': 'GMCA News', 'url': 'https://www.greatermanchester-ca.gov.uk/news/', 'default_area': 'rochdale', 'link_pattern': '/news/'}, {'name': 'BBC Manchester', 'url': 'https://www.bbc.co.uk/news/england/manchester', 'default_area': 'rochdale', 'link_pattern': '/news/'}, {'name': 'About Manchester', 'url': 'https://aboutmanchester.co.uk/?s=Rochdale', 'default_area': 'rochdale', 'link_pattern': '/'}, {'name': 'Rochdale Boroughwide Housing', 'url': 'https://www.rbh.org.uk/', 'default_area': 'rochdale', 'default_category': 'community', 'trusted_local': True, 'link_pattern': '/news/|/latest-news/|/updates/|/our-news/'}, {'name': 'Rochdale Riverside News', 'url': 'https://rochdaleriverside.com/news/', 'default_area': 'rochdale', 'default_category': 'business', 'trusted_local': True, 'link_pattern': '/news/'}, {'name': 'The Independent — Rochdale', 'url': 'https://www.independent.co.uk/topic/rochdale', 'default_area': 'rochdale', 'default_category': 'news', 'link_pattern': '/news/|/topic/rochdale'}, {'name': 'Rochdale Council Webcasts', 'url': 'https://rochdale.public-i.tv/core/data/21235/archived/1/future/1/agenda/1/enctag/Council', 'default_area': 'rochdale', 'default_category': 'politics', 'trusted_local': True, 'link_pattern': '/core/portal/|/core/data/'}, {'name': 'Rochdale Valiant', 'url': 'https://www.rochdalevaliant.uk/', 'default_area': 'rochdale', 'default_category': 'news', 'trusted_local': True, 'link_pattern': '/'}, {'name': 'Northern Care Alliance Rochdale', 'url': 'https://www.northerncarealliance.nhs.uk/news/rochdale-news', 'default_area': 'rochdale', 'default_category': 'health', 'link_pattern': '/news/'}, {'name': 'Northern Care Alliance News', 'url': 'https://www.northerncarealliance.nhs.uk/nca-news', 'default_area': 'rochdale', 'default_category': 'health', 'link_pattern': '/nca-news/|/news/'}, {'name': 'Pennine Care NHS', 'url': 'https://www.penninecare.nhs.uk/about-us/latest-news', 'default_area': 'rochdale', 'default_category': 'health', 'link_pattern': '/latest-news/|/news/'}, {'name': 'Hopwood Hall College', 'url': 'https://www.hopwood.ac.uk/news-and-events/latest-news/', 'default_area': 'rochdale', 'default_category': 'education', 'link_pattern': '/news-and-events/'}, {'name': 'Rochdale Sixth Form College', 'url': 'https://www.rochdalesfc.ac.uk/news/', 'default_area': 'rochdale', 'default_category': 'education', 'link_pattern': '/news/'}, {'name': 'Falinge Park High School', 'url': 'https://www.falingepark.com/news-and-events/', 'default_area': 'falinge', 'default_category': 'education', 'trusted_local': True, 'link_pattern': '/news-and-events/|/news/'}, {'name': 'Oulder Hill Leadership Academy', 'url': 'https://www.oulderhillacademy.com/latest-news/', 'default_area': 'rochdale', 'default_category': 'education', 'trusted_local': True, 'link_pattern': '/latest-news/|/news/'}, {'name': 'Wardle Academy', 'url': 'https://www.wchs.co/topic/news-and-events', 'default_area': 'wardle', 'default_category': 'education', 'trusted_local': True, 'link_pattern': '/topic/news-and-events|/news/'}, {'name': "St Cuthbert's RC High School", 'url': 'https://stcuthberts.com/news', 'default_area': 'rochdale', 'default_category': 'education', 'trusted_local': True, 'link_pattern': '/news'}, {'name': 'Edgar Wood Academy', 'url': 'https://www.edgarwood.org/80/news-and-events', 'default_area': 'middleton', 'default_category': 'education', 'trusted_local': True, 'link_pattern': '/80/news-and-events|/news-and-events|/news/'}, {'name': 'Rochdale AFC', 'url': 'https://rochdaleafc.co.uk/news/', 'default_area': 'rochdale', 'default_category': 'sport', 'link_pattern': '/news/'}, {'name': 'Rochdale Hornets', 'url': 'https://www.hornetsrugbyleague.co.uk/news', 'default_area': 'rochdale', 'default_category': 'sport', 'link_pattern': '/news'}]
LIVE_PAGE_SOURCES = [{'name': 'Bee Network live travel alerts', 'url': 'https://tfgm.com/travel-updates/travel-alerts?ContensisTextOnly=true', 'category': 'transport', 'default_area': 'rochdale'}, {'name': 'Northern live service updates', 'url': 'https://www.northernrailway.co.uk/service-updates', 'category': 'transport', 'default_area': 'rochdale'}, {'name': 'Traffic Update — Rochdale', 'url': 'https://www.traffic-update.co.uk/traffic/rochdale.asp', 'category': 'traffic', 'default_area': 'rochdale', 'trusted_local': True, 'max_blocks': 12}, {'name': 'Met Office — Rochdale forecast', 'url': 'https://weather.metoffice.gov.uk/forecast/gcw3nb4ge', 'category': 'environment', 'default_area': 'rochdale', 'trusted_local': True, 'whole_page': True, 'max_blocks': 1, 'title': 'Rochdale weather forecast'}]
AGGREGATOR_PAGES = [{'name': 'NewsNow — Rochdale', 'url': 'https://www.newsnow.co.uk/h/UK/England/Greater+Manchester/Rochdale', 'default_area': 'rochdale', 'default_category': 'news', 'max_links': 30}, {'name': 'Ground News — Rochdale', 'url': 'https://ground.news/interest/rochdale', 'default_area': 'rochdale', 'default_category': 'news', 'max_links': 30}]
DISCOVERY_LISTING_OVERRIDES = {'Rochdale Borough Council News': ['https://www.rochdale.gov.uk/news', 'https://www.rochdale.gov.uk/news?page=2', 'https://www.rochdale.gov.uk/news?page=3'], 'Rochdale Council Events': ['https://www.rochdale.gov.uk/events?page=1', 'https://www.rochdale.gov.uk/events?page=2', 'https://www.rochdale.gov.uk/events?page=3'], 'Rochdale Town Hall Events': ['https://www.rochdaletownhall.co.uk/events?page=1', 'https://www.rochdaletownhall.co.uk/events?page=2', 'https://www.rochdaletownhall.co.uk/events?page=3'], 'Greater Manchester Police': [*[f'https://www.gmp.police.uk/news/news-search/?ct=News&fdte=&page={page}&tdte=' for page in range(1, 9)], *[f'https://www.gmp.police.uk/news/news-search/?ct=Appeals&fdte=&page={page}&tdte=' for page in range(1, 5)]], 'Roch Valley Radio Local News': ['https://www.rochvalleyradio.com/news/local-news/', 'https://www.rochvalleyradio.com/news/local-news/?page=2', 'https://www.rochvalleyradio.com/news/local-news/?page=3']}
SEARCH_QUERY_SPECS = build_search_query_specs(GOOGLE_SEARCH_QUERY_LIMIT)
SEARCH_GROUPS = [spec.query for spec in SEARCH_QUERY_SPECS]
FACEBOOK_GRAPH_VERSION = os.getenv('FACEBOOK_GRAPH_VERSION', 'v22.0')
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN', '').strip()
FACEBOOK_COMMENTS_ENABLED = os.getenv('FACEBOOK_COMMENTS_ENABLED', 'true').lower() not in {'0', 'false', 'no'}
X_BEARER_TOKEN = os.getenv('X_BEARER_TOKEN', '').strip()
X_API_BASE = os.getenv('X_API_BASE', 'https://api.x.com/2').rstrip('/')
X_RECENT_SEARCH_MAX = max(10, min(100, int(os.getenv('X_RECENT_SEARCH_MAX', '100'))))
SOCIAL_CONTEXT_ENABLED = os.getenv('SOCIAL_CONTEXT_ENABLED', 'true').lower() not in {'0', 'false', 'no'}
SOCIAL_MIN_PUBLIC_REACTIONS = max(3, int(os.getenv('SOCIAL_MIN_PUBLIC_REACTIONS', '3')))
SOCIAL_MAX_PUBLIC_REACTIONS = max(SOCIAL_MIN_PUBLIC_REACTIONS, int(os.getenv('SOCIAL_MAX_PUBLIC_REACTIONS', '12')))
SOCIAL_MAX_OFFICIAL_UPDATES = max(1, int(os.getenv('SOCIAL_MAX_OFFICIAL_UPDATES', '4')))
OFFICIAL_X_HANDLES = {'gmprochdale': 'Rochdale Police (GMP)', 'gmpolice': 'Greater Manchester Police', 'highwaysnwest': 'National Highways North West'}
OFFICIAL_X_PROFILE_URLS = {'gmprochdale': 'https://x.com/GMPRochdale', 'highwaysnwest': 'https://x.com/HighwaysNWEST'}
try:
    extra_x_handles = json.loads(os.getenv('OFFICIAL_X_HANDLES_JSON', '{}'))
    if isinstance(extra_x_handles, dict):
        OFFICIAL_X_HANDLES.update({str(handle).lstrip('@').lower(): str(name) for handle, name in extra_x_handles.items() if str(handle).strip() and str(name).strip()})
except json.JSONDecodeError:
    pass
X_SEARCH_QUERIES = ['(Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow OR Newhey OR Wardle OR Norden OR Castleton OR Kirkholt OR Spotland OR Falinge OR Deeplish) lang:en -is:retweet', '(from:GMPRochdale OR from:gmpolice) lang:en -is:retweet', '(to:GMPRochdale OR @GMPRochdale) lang:en -is:retweet', 'from:HighwaysNWEST ("M62 J19" OR "M62 J20" OR "M62 J21" OR "M62 junction 19" OR "M62 junction 20" OR "M62 junction 21" OR "A627(M)" OR Rochdale OR Heywood OR Milnrow OR Middleton OR Littleborough) lang:en -is:retweet']
try:
    extra_x_queries = json.loads(os.getenv('X_SEARCH_QUERIES_JSON', '[]'))
    if isinstance(extra_x_queries, list):
        X_SEARCH_QUERIES.extend((str(query) for query in extra_x_queries if str(query).strip()))
except json.JSONDecodeError:
    pass
PUBLIC_FACEBOOK_PAGES = [{'name': 'Rochdale Police - GMP Facebook', 'handle': 'GMPRochdale', 'url': 'https://www.facebook.com/GMPRochdale', 'default_area': 'rochdale', 'official': True}, {'name': 'Roch Valley Radio Facebook', 'handle': 'rochvalleyradio', 'url': 'https://www.facebook.com/rochvalleyradio', 'default_area': 'rochdale'}, {'name': 'Rochdale Borough Council Facebook', 'handle': 'rochdalecouncil', 'url': 'https://www.facebook.com/rochdalecouncil', 'default_area': 'rochdale'}, {'name': 'Bee Network Facebook', 'handle': 'beenetworkgm', 'url': 'https://www.facebook.com/beenetworkgm', 'default_area': 'rochdale'}, {'name': 'Rochdale Sixth Form College Facebook', 'handle': 'rochdalesfc', 'url': 'https://www.facebook.com/rochdalesfc', 'default_area': 'rochdale'}, {'name': 'My Rochdale News Facebook', 'handle': 'MyRochdaleNews', 'url': 'https://www.facebook.com/MyRochdaleNews/', 'default_area': 'rochdale', 'official': False, 'publish_as_source': True, 'trusted_local': True}]
try:
    extra_facebook_pages = json.loads(os.getenv('FACEBOOK_PAGES_JSON', '[]'))
    if isinstance(extra_facebook_pages, list):
        PUBLIC_FACEBOOK_PAGES.extend((page for page in extra_facebook_pages if isinstance(page, dict) and page.get('handle') and page.get('name')))
except json.JSONDecodeError:
    pass
LOCAL_TERMS = {'rochdale', 'rochdale town centre', 'heywood', 'middleton', 'littleborough', 'milnrow', 'newhey', 'norden', 'bamford', 'kirkholt', 'shawclough', 'healey', 'whitworth', 'wardle', 'smithy bridge', 'castleton', 'spotland', 'falinge', 'balderstone', 'deeplish', 'smallbridge', 'firgrove', 'syke', 'cutgate', 'darnhill', 'hopwood', 'alkrington', 'boarshaw', 'belfield', 'wardleworth', 'sudden', 'buersil', 'cloverhall', 'lowerplace', 'meanwood', 'mandale park', 'summit', 'hollingworth lake', 'slattocks', 'birch', 'caldershaw'}
AREA_KEYWORDS = {'darnhill': {'darnhill'}, 'hopwood': {'hopwood'}, 'alkrington': {'alkrington'}, 'boarshaw': {'boarshaw'}, 'newhey': {'newhey'}, 'smithy_bridge': {'smithy bridge'}, 'wardle': {'wardle'}, 'smallbridge': {'smallbridge'}, 'norden': {'norden'}, 'bamford': {'bamford'}, 'cutgate': {'cutgate', 'caldershaw'}, 'kirkholt': {'kirkholt'}, 'castleton': {'castleton'}, 'spotland': {'spotland'}, 'falinge': {'falinge'}, 'deeplish': {'deeplish'}, 'balderstone': {'balderstone'}, 'firgrove': {'firgrove'}, 'shawclough': {'shawclough'}, 'healey': {'healey'}, 'syke': {'syke'}, 'wardleworth': {'wardleworth'}, 'sudden': {'sudden'}, 'lowerplace': {'lowerplace'}, 'meanwood': {'meanwood'}, 'littleborough': {'littleborough', 'hollingworth lake', 'summit'}, 'milnrow': {'milnrow', 'slattocks'}, 'heywood': {'heywood'}, 'middleton': {'middleton'}, 'whitworth': {'whitworth'}, 'rochdale': {'rochdale', 'rochdale town centre', 'town centre'}}
AMBIGUOUS_LOCAL_TERMS = {'middleton', 'healey', 'wardle', 'bamford', 'norden', 'hopwood', 'birch', 'summit', 'syke'}
UNAMBIGUOUS_LOCAL_TERMS = LOCAL_TERMS - AMBIGUOUS_LOCAL_TERMS
TRUSTED_LOCAL_SOURCE_PREFIXES = ('Rochdale Borough Council', 'Rochdale Council', 'Rochdale AFC', 'Rochdale Hornets', 'Rochdale Development Agency', 'Rochdale Town Hall', 'Rochdale Police', 'Action Together Rochdale', 'Your Trust Rochdale', 'Visit Rochdale', 'Northern Care Alliance Rochdale', 'Hopwood Hall College', 'Rochdale Sixth Form College', 'Facebook Events — Rochdale')
PLACE_CONTEXT_SUFFIXES = ('town', 'town centre', 'area', 'ward', 'estate', 'village', 'residents', 'community', 'council', 'borough', 'school', 'college', 'library', 'road', 'street', 'lane', 'avenue', 'park', 'station', 'market', 'police', 'fire station', 'hospital', 'clinic', 'businesses', 'shops', 'pub', 'events', 'traffic', 'services', 'neighbourhood')
PLACE_CONTEXT_PREFIXES = ('in', 'at', 'near', 'around', 'across', 'from', 'within', 'throughout', 'towards', 'toward', 'outside', 'serving', 'based in', 'located in', 'residents of', 'people in', 'businesses in', 'schools in', 'school in', 'police in', 'firefighters in', 'travelling to', 'roads in')
CATEGORY_KEYWORDS = {'crime': {'arrest', 'arrested', 'police', 'officer', 'officers', 'charged', 'charge', 'court', 'magistrates', 'crown court', 'burglary', 'robbery', 'assault', 'stabbing', 'shooting', 'theft', 'fraud', 'wanted', 'jailed', 'murder', 'manslaughter', 'grooming', 'convicted', 'sentenced', 'sentencing', 'warrant', 'raid', 'seized', 'drugs', 'cannabis farm', 'appeal for information', 'appeal for witnesses', 'anti-social behaviour', 'criminal behaviour order', 'public order', 'deported', 'deportation', 'parole', 'released from prison'}, 'traffic': {'traffic', 'roadworks', 'road work', 'road closure', 'road closed', 'collision', 'crash', 'm62', 'a627', 'junction', 'lane closure', 'lane closed', 'carriageway', 'diversion', 'congestion', 'temporary traffic lights', 'motorway incident'}, 'transport': {'bus', 'train', 'tram', 'metrolink', 'bee network', 'station', 'timetable', 'public transport'}, 'politics': {'councillor', 'council budget', 'council tax', 'election', 'cabinet', 'mayor', 'resigns', 'resignation', 'steps down', 'stands down', 'quits', 'mp '}, 'education': {'school', 'college', 'university', 'ofsted', 'teacher', 'pupil', 'student', 'education'}, 'sport': {'football', 'rochdale afc', 'hornets', 'dale', 'match', 'fixture', 'league', 'rugby', 'cricket', 'boxing'}, 'events': {'festival', 'concert', 'event', 'fair', 'market', 'open day', 'exhibition', 'gig', 'performance', 'parade'}, 'business': {'business', 'shop', 'restaurant', 'pub', 'company', 'investment', 'opening', 'closure'}, 'community': {'community', 'charity', 'fundraiser', 'volunteer', 'library', 'support group', 'appeal'}, 'health': {'nhs', 'hospital', 'health', 'doctor', 'gp', 'clinic', 'care service', 'mental health'}, 'environment': {'flood', 'weather', 'environment', 'recycling', 'litter', 'climate', 'wildlife', 'park'}}
CHILD_MENTION_PATTERN = '\\b(child|children|minor|youth|under[- ]?18|schoolgirl|schoolboy)\\b'
SENSITIVE_PATTERNS = ['\\b(rape|sexual assault|sexual offence|sexual abuse)\\b', '\\b(child sexual abuse|child grooming|child victim|minor victim)\\b']
SAFEGUARDING_CONTEXT_PATTERN = '\\b(alleged|allegedly|accused|suspect|suspected|charged|arrested|court|trial|jury|inquest|coroner|murder|manslaughter|rape|sexual|assault|abuse|grooming|stabbing|death|died|killed|suicide|self-harm|domestic abuse|domestic violence|missing|kidnap|neglect|safeguarding)\\b'
# Four live articles proved the classified/advert net had holes: a used-car
# listing ("available in Rochdale for £10,495", via Autouncle), a Tes
# job-search NO-RESULTS template ("No ... Jobs Found in Rochdale"), a
# service-directory page ("Breakdown Recovery Services Available in Heywood")
# and a US house-rental listing. All arrived through Google News queries, so
# source denylisting alone cannot cover the long tail of SEO publishers; the
# template LANGUAGE is the cheap early signal, and the editorial gate in
# editorial_upgrade.py is the semantic defence behind it. Deliberately NOT
# matched: "new warehouse to create 500 jobs" (jobs as news), "tickets on
# sale from £15" (price lacks a thousands separator), "£10,495,000
# investment" (no sale verb within 70 chars before the price).
DROP_PATTERNS = ['\\b(?:opinion|comment|column|editorial)\\b', '\\bfor sale\\b|\\bfor rent\\b|\\broom to let\\b', '\\brecommendations please\\b|\\bdoes anyone know\\b|\\bgetting rid of\\b', "\\bno [a-z][a-z\\s,'-]{0,70}jobs? (?:found|available|listed)\\b", '\\bjobs? (?:found|matching|listed) in\\b', '\\b(?:available|on sale|for sale|priced)\\b[^.]{0,70}£\\s?\\d{1,3}(?:,\\d{3})+', '\\bservices? available in\\b', '\\b(?:house|home|flat|apartment|property|room) (?:rental|to let|for rent|to rent)\\b|\\brental available\\b', '\\bproperty auction\\b|\\bauction (?:scheduled|to be held)\\b|\\b(?:goes?|going) under the hammer\\b|\\bguide price\\b']
PLACEHOLDER_PATTERNS = ['\\[(?:insert|relevant|contact|date|number|details|link)[^\\]]*\\]', '\\babout this article\\b.*$', '\\brelated topics\\b.*$', '#rochdalenews|#greatermanchester', '\\bfact-checked local journalism\\b']
CATEGORY_STOCK_IMAGES = {category: f'assets/img/stock_{category}.jpg' for category in ['news', 'crime', 'traffic', 'transport', 'politics', 'education', 'sport', 'events', 'business', 'community', 'health', 'environment']}
# ARTICLE_SCHEMA carries the editorial gate (see EDITORIAL_GATE_INSTRUCTIONS
# in editorial_upgrade.py). Strict json_schema means the model MUST answer
# both gate questions on every draft; the pipeline then applies a
# deterministic veto: content_class != 'news_report' is never published
# (adverts, classifieds, job/recruitment pages, search-results and "no
# results found" templates, directory pages, marketing copy), and
# is_about_rochdale_borough == false is never published (Middleton in
# Idaho/Wisconsin/Leeds and every other namesake, without maintaining a
# counter-term list per impostor town).
ARTICLE_SCHEMA = {'name': 'rochdale_daily_article', 'strict': True, 'schema': {'type': 'object', 'additionalProperties': False, 'properties': {'publishable': {'type': 'boolean'}, 'content_class': {'type': 'string', 'enum': ['news_report', 'advert_or_listing', 'job_or_recruitment', 'search_results_or_index_page', 'directory_or_services_page', 'press_release_marketing', 'other_non_news']}, 'is_about_rochdale_borough': {'type': 'boolean'}, 'title': {'type': 'string'}, 'excerpt': {'type': 'string'}, 'paragraphs': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 4, 'maxItems': 12}, 'category': {'type': 'string', 'enum': list(CATEGORY_STOCK_IMAGES)}, 'area': {'type': 'string', 'enum': list(AREA_KEYWORDS)}, 'legal_disclaimer': {'type': 'string'}, 'right_to_reply': {'type': 'string'}, 'community_reaction': {'type': 'string'}, 'social_context_used': {'type': 'boolean'}, 'reason': {'type': 'string'}}, 'required': ['publishable', 'content_class', 'is_about_rochdale_borough', 'title', 'excerpt', 'paragraphs', 'category', 'area', 'legal_disclaimer', 'right_to_reply', 'community_reaction', 'social_context_used', 'reason']}}
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()])
log = logging.getLogger('rochdale_daily')
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'RochdaleDaily/3.2 (+https://rochdaledaily.co.uk; contact: news@rochdaledaily.co.uk)', 'Accept-Language': 'en-GB,en;q=0.9'})
HTTP_RETRY = Retry(total=2, connect=2, read=2, backoff_factor=0.35, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({'GET', 'HEAD'}), raise_on_status=False)
HTTP_ADAPTER = HTTPAdapter(pool_connections=max(16, HTTP_POOL_CONNECTIONS), pool_maxsize=max(16, HTTP_POOL_MAXSIZE), max_retries=HTTP_RETRY, pool_block=True)
SESSION.mount('https://', HTTP_ADAPTER)
SESSION.mount('http://', HTTP_ADAPTER)
ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser] = {}
ROBOTS_DENIED_URLS: list[str] = []
ROBOTS_DENIED_SEEN: set[str] = set()

@dataclass
class Candidate:
    source_name: str
    source_url: str
    source_title: str
    source_summary: str
    source_published_at: str
    area: str
    category: str
    image_candidate_url: str = ''
    source_body_excerpt: str = ''
    event_start_at: str = ''
    event_end_at: str = ''
    event_location: str = ''
    source_kind: str = 'article'
    related_sources: list[dict[str, str]] = field(default_factory=list)
    social_context: list[dict[str, Any]] = field(default_factory=list)
    story_key: str = ''
    discovery_query_label: str = ''
    searched_location_slug: str = ''
    searched_location_name: str = ''

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or '').lower()
    return host[4:] if host.startswith('www.') else host

def source_is_denied(source_name: str='', source_url: str='') -> bool:
    name = normalise_ws(source_name).lower()
    domain = domain_of(source_url)
    return domain in SOURCE_DENY_DOMAINS or any((blocked in name for blocked in SOURCE_DENY_NAMES))

def is_current_uk_day(value: datetime | None) -> bool:
    return bool(value) and value.astimezone(UK_TZ).date() == utc_now().astimezone(UK_TZ).date()

def event_is_current_or_future(value: datetime | None) -> bool:
    if value is None:
        return False
    return utc_now() - timedelta(hours=12) <= value <= utc_now() + timedelta(days=550)

def canonicalise_url(url: str) -> str:
    parsed = urlparse(url)
    query_parts = []
    for part in parsed.query.split('&'):
        low = part.lower()
        if part and (not low.startswith(('utm_', 'at_medium=', 'at_campaign=', 'fbclid=', 'gclid='))):
            query_parts.append(part)
    return urlunparse((parsed.scheme or 'https', parsed.netloc.lower(), parsed.path, '', '&'.join(query_parts), ''))

def stable_id(url: str) -> str:
    return hashlib.sha256(canonicalise_url(url).encode('utf-8')).hexdigest()[:18]

def normalise_ws(value: Any) -> str:
    return re.sub('\\s+', ' ', str(value or '')).strip()

def strip_markdown(value: Any) -> str:
    text = str(value or '')
    text = re.sub('!\\[([^\\]]*)\\]\\([^)]+\\)', '\\1', text)
    text = re.sub('\\[([^\\]]+)\\]\\([^)]+\\)', '\\1', text)
    text = re.sub('^\\s{0,3}#{1,6}\\s*', '', text, flags=re.MULTILINE)
    text = re.sub('(\\*\\*|__)(.*?)\\1', '\\2', text, flags=re.DOTALL)
    text = re.sub('(?<!\\*)\\*([^*\\n]+)\\*(?!\\*)', '\\1', text)
    text = re.sub('(?<!_)_([^_\\n]+)_(?!_)', '\\1', text)
    text = re.sub('`{1,3}([^`]+)`{1,3}', '\\1', text)
    text = re.sub('^\\s*[-*+]\\s+', '', text, flags=re.MULTILINE)
    for pattern in PLACEHOLDER_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
    return normalise_ws(text).strip('*_#- ')

def make_slug(title: str) -> str:
    return re.sub('[^a-z0-9]+', '-', strip_markdown(title).lower()).strip('-')[:80] or 'local-news-update'

def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    except ValueError:
        try:
            result = parsedate_to_datetime(str(value).strip())
        except (TypeError, ValueError, OverflowError):
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)

def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

def is_fresh(value: datetime | None) -> bool:
    if value is None:
        return False
    age = utc_now() - value
    if not timedelta(minutes=-30) <= age <= timedelta(hours=MAX_NEWS_AGE_HOURS):
        return False
    if SAME_DAY_ONLY:
        return is_current_uk_day(value)
    return True

def _plain_text(value: Any) -> str:
    raw = str(value or '')
    if '<' in raw and '>' in raw:
        raw = BeautifulSoup(raw, 'lxml').get_text(' ', strip=True)
    return normalise_ws(raw)

def _term_pattern(term: str) -> str:
    return f'(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])'

def _contains_term(text: str, term: str) -> bool:
    return bool(re.search(_term_pattern(term), text, flags=re.IGNORECASE))

def _has_geographical_context(text: str, term: str) -> bool:
    term_pattern = _term_pattern(term)
    prefix_pattern = '|'.join((re.escape(prefix) for prefix in PLACE_CONTEXT_PREFIXES))
    suffix_pattern = '|'.join((re.escape(suffix) for suffix in PLACE_CONTEXT_SUFFIXES))
    before = f'\\b(?:{prefix_pattern})\\s+(?:the\\s+)?{term_pattern}'
    after = f"{term_pattern}(?:'s)?\\s+(?:{suffix_pattern})\\b"
    qualified = f'{term_pattern}\\s*,\\s*(?:Rochdale|Greater Manchester)\\b'
    postcode_context = f'{term_pattern}.{{0,80}}\\b(?:OL|M)\\d{{1,2}}\\s*\\d[A-Z]{{2}}\\b'
    return any((re.search(pattern, text, flags=re.IGNORECASE) for pattern in (before, after, qualified, postcode_context)))

def locality_evidence(text: str, source_name: str='', source_url: str='') -> dict[str, Any]:
    plain = _plain_text(text)
    evidence: list[str] = []
    score = 0
    if source_is_denied(source_name, source_url):
        return {'local': False, 'score': 0, 'evidence': ['denied-source']}
    if source_name.startswith(TRUSTED_LOCAL_SOURCE_PREFIXES):
        score += 5
        evidence.append(f'trusted-source:{source_name}')
    if _contains_term(plain, 'rochdale'):
        score += 5
        evidence.append('place:rochdale')
    for term in sorted(UNAMBIGUOUS_LOCAL_TERMS - {'rochdale'}, key=len, reverse=True):
        if _contains_term(plain, term):
            score += 2
            evidence.append(f'place:{term}')
    for term in sorted(AMBIGUOUS_LOCAL_TERMS, key=len, reverse=True):
        if _has_geographical_context(plain, term):
            score += 2
            evidence.append(f'contextual-place:{term}')
    return {'local': score >= 2, 'score': score, 'evidence': evidence}

def detect_area(text: str, fallback: str='rochdale') -> str:
    plain = _plain_text(text)
    for area, terms in AREA_KEYWORDS.items():
        if area == 'rochdale':
            continue
        for term in sorted(terms, key=len, reverse=True):
            if term in AMBIGUOUS_LOCAL_TERMS:
                if _has_geographical_context(plain, term):
                    return area
            elif _contains_term(plain, term):
                return area
    if _contains_term(plain, 'rochdale'):
        return 'rochdale'
    return fallback

def categorise(text: str) -> str:
    low = text.lower()
    scores = {category: sum((1 for keyword in keywords if keyword in low)) for category, keywords in CATEGORY_KEYWORDS.items()}
    category, score = max(scores.items(), key=lambda item: item[1])
    return category if score else 'news'

def is_local(text: str, source_name: str, source_url: str='') -> bool:
    return bool(locality_evidence(text, source_name, source_url)['local'])

def article_is_local(article: dict[str, Any]) -> bool:
    combined = ' '.join([str(article.get('title') or ''), str(article.get('excerpt') or ''), str(article.get('content_html') or ''), str(article.get('event_location') or '')])
    return is_local(combined, str(article.get('source_name') or ''), str(article.get('source_url') or ''))
from rewrite_safety import excessive_source_overlap
from selection_policy import PUBLISH_CATEGORIES, ROCHDALE_WARDS, balanced_select, is_classified_listing_post, is_job_or_career_post, ward_for_item
from story_identity import authority_score, build_story_key, dedupe_article_records, merge_article_records, same_story
from story_blocklist import is_blocked_article, is_blocked_text, load_blocklist as load_story_blocklist
from locality_rules import AREA_KEYWORDS, LOCAL_TERMS, article_is_local, detect_area, has_disqualifying_evidence, is_local, locality_evidence, source_is_denied as locality_source_is_denied

def source_is_denied(source_name: str='', source_url: str='') -> bool:
    """Keep Roch Valley Radio allowed while hard-blocking prohibited outlets.

    autouncle.co.uk (used-car classifieds) and tes.com (teaching-job listings
    and their "no results" SEO templates) both reached the live site through
    Google News RSS entries, where the entry's own <source> element exposes
    the real publisher domain, so this check fires at collection time. Names
    are matched by substring, so only 'autouncle' is safe to add as a name;
    'tes' as a bare substring would collide with ordinary source names.
    """
    name = normalise_ws(source_name).lower()
    domain = domain_of(source_url)
    if domain == 'rochvalleyradio.com' or 'roch valley radio' in name:
        return False
    if domain in {'rochdaletimes.co.uk', 'rochdaleonline.co.uk', 'pressreader.com', 'rochdaleobserver.co.uk', 'autouncle.co.uk', 'tes.com'}:
        return True
    if any((blocked in name for blocked in ('rochdale times', 'rochdale times paper', 'rochdale online', 'rochdale observer', 'pressreader', 'autouncle'))):
        return True
    return locality_source_is_denied(source_name, source_url)
ROCHDALE_TRAFFIC_AREA_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (('heywood', ('\\bm62\\s+(?:junction|j)\\s*19\\b', '\\bpilsworth road\\b', "\\bqueen'?s park road\\b")), ('rochdale', ('\\bm62\\s+(?:junction|j)\\s*20\\b', '\\ba627\\s*\\(m\\)\\b', '\\bedinburgh way\\b', '\\broch valley way\\b', '\\bmilnrow road\\b', '\\bsandbrook park\\b')), ('milnrow', ('\\bm62\\s+(?:junction|j)\\s*21\\b', '\\belizabethan way\\b')), ('middleton', ('\\bmanchester new road\\b', '\\ba664\\b.{0,100}\\bmiddleton\\b', '\\bmiddleton\\b.{0,100}\\ba664\\b')), ('littleborough', ('\\bhare hill road\\b', '\\ba58\\b.{0,100}\\blittleborough\\b', '\\blittleborough\\b.{0,100}\\ba58\\b')))
TRAFFIC_CONTEXT_RE = re.compile('\\b(?:traffic|collision|crash|incident|roadworks|road work|road closed|road closure|closed|closure|lane closed|lane closure|carriageway|congestion|delay|delays|diversion|temporary traffic lights|motorway)\\b', flags=re.IGNORECASE)

def rochdale_traffic_area(text: str) -> str:
    plain = normalise_ws(text)
    if not TRAFFIC_CONTEXT_RE.search(plain):
        return ''
    for area, patterns in ROCHDALE_TRAFFIC_AREA_PATTERNS:
        if any((re.search(pattern, plain, flags=re.IGNORECASE) for pattern in patterns)):
            return area
    return ''

def source_text_is_local(text: str, source_name: str='', source_url: str='', trusted_local: bool=False) -> bool:
    """Fail closed when explicit external geography contradicts a local name.

    Trusted publishers and names such as Castleton are positive evidence, not a
    licence to ignore phrases such as "Hudson, NY" or "New York". The
    disqualifying-geography veto must therefore run before every positive path.
    """
    if source_is_denied(source_name, source_url):
        return False
    if has_disqualifying_evidence(text, source_name, source_url):
        return False
    return bool(
        trusted_local
        or is_local(text, source_name, source_url)
        or rochdale_traffic_area(text)
    )

def source_text_area(text: str, fallback: str='', source_name: str='', source_url: str='', trusted_local: bool=False) -> str:
    if source_is_denied(source_name, source_url):
        return ''
    if has_disqualifying_evidence(text, source_name, source_url):
        return ''
    area = detect_area(text, fallback, source_name, source_url)
    if area:
        return area
    traffic_area = rochdale_traffic_area(text)
    if traffic_area:
        return traffic_area
    return fallback if trusted_local else ''

def location_query_result_allowed(
    text: str,
    source_name: str = '',
    source_url: str = '',
    location_slug: str = '',
) -> bool:
    """Reject a location-query result when it contains a known external match.

    The requested search location is metadata only and never proves locality. The
    normal source_text_is_local() check must still pass using the actual headline,
    summary, publisher identity, URL or article content. This guard specifically
    stops ambiguous searches such as Norden from accepting Norden in Swanage or a
    Stevenage/Hertfordshire result.
    """
    slug = normalise_ws(location_slug).lower()
    if not slug:
        return True
    profile = LOCATION_BY_SLUG.get(slug)
    if profile is None:
        log.warning('Rejected result from unknown location query: %s', slug)
        return False
    actual_result_text = normalise_ws(f'{text} {source_name} {source_url}').casefold()
    for reject_term in profile.reject_terms:
        term = normalise_ws(reject_term).casefold()
        if term and term in actual_result_text:
            log.info(
                'Rejected external match for %s query because result contained %r: %s',
                profile.name,
                reject_term,
                source_name or source_url,
            )
            return False
    return True

def live_category(text: str, fallback: str) -> str:
    detected = categorise(text)
    if detected == 'traffic':
        return 'traffic'
    if detected != 'news' and fallback == 'news':
        return detected
    return fallback or detected or 'news'

def should_drop(text: str, url: str='') -> bool:
    low = text.lower()
    return is_job_or_career_post(text, url) or is_classified_listing_post(text, url) or any((re.search(pattern, low) for pattern in DROP_PATTERNS))

def is_sensitive(text: str, category: str) -> bool:
    """Crime is never routed through the sensitive-story publication path.

    This function remains for non-crime material only. Crime candidates go
    through the standard grounded rewrite like every other category.
    """
    if category == 'crime':
        return False
    if any((re.search(pattern, text, flags=re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)):
        return True
    if re.search(CHILD_MENTION_PATTERN, text, flags=re.IGNORECASE) and re.search(SAFEGUARDING_CONTEXT_PATTERN, text, flags=re.IGNORECASE):
        return True
    return False

def robots_allows(url: str) -> bool:
    if not RESPECT_ROBOTS:
        return True
    parsed = urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}'
    robot = ROBOTS_CACHE.get(base)
    if robot is None:
        robot = urllib.robotparser.RobotFileParser()
        robot.set_url(urljoin(base, '/robots.txt'))
        try:
            robot.read()
        except Exception:
            log.warning('Could not read robots.txt for %s; allowing a standard public-page request.', base)
            return True
        ROBOTS_CACHE[base] = robot
    try:
        return robot.can_fetch(SESSION.headers['User-Agent'], url)
    except Exception:
        return True

def fetch_html(url: str) -> tuple[str, str]:
    if not robots_allows(url):
        canonical = canonicalise_url(url)
        if canonical not in ROBOTS_DENIED_SEEN:
            ROBOTS_DENIED_SEEN.add(canonical)
            ROBOTS_DENIED_URLS.append(canonical)
            log.info('robots.txt declined direct fetch; relying on RSS, indexed search results or authorised APIs instead: %s', canonical)
        raise PermissionError(f'robots.txt does not permit fetching {url}')
    response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get('content-type', '')
    if 'html' not in content_type and '<html' not in response.text[:500].lower():
        raise ValueError(f'Not an HTML page: {content_type}')
    return (response.url, response.text)

def first_meta(soup: BeautifulSoup, selectors: Iterable[tuple[str, dict[str, str]]]) -> str:
    for tag, attrs in selectors:
        node = soup.find(tag, attrs=attrs)
        if node and node.get('content'):
            return normalise_ws(node.get('content'))
    return ''

def extract_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for node in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        queue = payload if isinstance(payload, list) else [payload]
        for item in queue:
            if isinstance(item, dict) and isinstance(item.get('@graph'), list):
                queue.extend(item['@graph'])
            elif isinstance(item, dict):
                objects.append(item)
    return objects

def image_from_jsonld(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return image_from_jsonld(value[0])
    if isinstance(value, dict):
        return str(value.get('url') or value.get('contentUrl') or '')
    return ''

def page_metadata(url: str) -> dict[str, str]:
    final_url, raw_html = fetch_html(url)
    soup = BeautifulSoup(raw_html, 'lxml')
    jsonld = extract_jsonld(soup)
    title = first_meta(soup, [('meta', {'property': 'og:title'}), ('meta', {'name': 'twitter:title'})])
    if not title:
        h1 = soup.find('h1')
        title = normalise_ws(h1.get_text(' ', strip=True) if h1 else '')
    if not title and soup.title:
        title = normalise_ws(soup.title.get_text(' ', strip=True))
    description = first_meta(soup, [('meta', {'property': 'og:description'}), ('meta', {'name': 'description'}), ('meta', {'name': 'twitter:description'})])
    image_url = first_meta(soup, [('meta', {'property': 'og:image:secure_url'}), ('meta', {'property': 'og:image'}), ('meta', {'name': 'twitter:image'})])
    published = first_meta(soup, [('meta', {'property': 'article:published_time'}), ('meta', {'name': 'article:published_time'}), ('meta', {'name': 'date'}), ('meta', {'name': 'pubdate'}), ('meta', {'itemprop': 'datePublished'})])
    modified = first_meta(soup, [('meta', {'property': 'article:modified_time'}), ('meta', {'itemprop': 'dateModified'})])
    event_start = ''
    event_end = ''
    event_location = ''
    content_type = 'article'
    body_parts: list[str] = []
    for item in jsonld:
        kind = item.get('@type')
        kinds = set(kind if isinstance(kind, list) else [kind])
        if 'Event' in kinds:
            content_type = 'event'
            title = title or normalise_ws(item.get('name'))
            description = description or normalise_ws(item.get('description'))
            event_start = event_start or normalise_ws(item.get('startDate'))
            event_end = event_end or normalise_ws(item.get('endDate'))
            location = item.get('location')
            if isinstance(location, dict):
                address = location.get('address')
                if isinstance(address, dict):
                    event_location = normalise_ws(' '.join((str(address.get(key) or '') for key in ('streetAddress', 'addressLocality', 'postalCode'))))
                event_location = event_location or normalise_ws(location.get('name'))
            image_url = image_url or image_from_jsonld(item.get('image'))
        if kinds.intersection({'NewsArticle', 'Article', 'ReportageNewsArticle'}):
            title = title or normalise_ws(item.get('headline') or item.get('name'))
            description = description or normalise_ws(item.get('description'))
            published = published or normalise_ws(item.get('datePublished'))
            modified = modified or normalise_ws(item.get('dateModified'))
            image_url = image_url or image_from_jsonld(item.get('image'))
            article_body = normalise_ws(item.get('articleBody'))
            if article_body:
                body_parts.append(article_body[:3500])
    if not published and content_type != 'event':
        # Only trust <time> elements inside the story itself. The first
        # <time> on the PAGE is frequently a current-date widget or a
        # related-articles sidebar, which resurrected a years-old Rochdale
        # Riverside opening story as current news.
        date_scope = soup.select_one('article') or soup.select_one('main')
        for time_node in (date_scope.find_all('time') if date_scope else []):
            candidate_date = time_node.get('datetime') or time_node.get('content')
            if parse_datetime(candidate_date):
                published = str(candidate_date)
                break
    if not event_start and content_type == 'event':
        visible = normalise_ws(soup.get_text(' ', strip=True))
        event_start = extract_future_event_date(visible)
    if not body_parts:
        paragraphs = [normalise_ws(p.get_text(' ', strip=True)) for p in soup.select('article p, main p')]
        body_parts.extend([p for p in paragraphs if len(p) >= 40][:8])
    # 'published' is a real publication date or empty — never dateModified.
    # A site-wide template change touches dateModified on every page at
    # once, which made archive pages look freshly published. Pages exposing
    # no genuine publication date are treated as undated and rejected by
    # the is_fresh() gates: an unverifiable date is a reason not to
    # publish, not a gap to paper over.
    return {'url': canonicalise_url(final_url), 'title': strip_markdown(title), 'description': strip_markdown(description), 'published': published, 'modified': modified, 'image': urljoin(final_url, image_url) if image_url else '', 'body_excerpt': normalise_ws(' '.join(body_parts))[:5000], 'content_type': content_type, 'event_start': event_start, 'event_end': event_end, 'event_location': event_location}

def entry_datetime(entry: Any) -> datetime | None:
    for key in ('published', 'updated', 'created'):
        parsed = parse_datetime(getattr(entry, key, None))
        if parsed:
            return parsed
    for key in ('published_parsed', 'updated_parsed', 'created_parsed'):
        value = getattr(entry, key, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None

def rss_image(entry: Any) -> str:
    for attr in ('media_content', 'media_thumbnail'):
        for item in getattr(entry, attr, None) or []:
            if isinstance(item, dict) and item.get('url'):
                return str(item['url'])
    for item in getattr(entry, 'enclosures', None) or []:
        if isinstance(item, dict) and str(item.get('type') or '').startswith('image/') and item.get('href'):
            return str(item['href'])
    return ''

def google_news_sources() -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    exclusions = ' when:1d -site:rochdaleonline.co.uk -site:rochdaletimes.co.uk -vacancy -vacancies -careers -recruitment -hiring -apprenticeship -internship'
    for index, spec in enumerate(SEARCH_QUERY_SPECS, start=1):
        sources.append({
            'name': f'Google News — {spec.label}',
            'url': f'https://news.google.com/rss/search?q={quote_plus(spec.query + exclusions)}&hl=en-GB&gl=GB&ceid=GB:en',
            'default_area': 'rochdale',
            'aggregator': 'google',
            'query_label': spec.label,
            'query_category': spec.category,
            'query_ward': spec.ward,
            'query_person': spec.person,
            'query_location_slug': spec.location_slug,
            'query_location_name': spec.location_name,
        })
    return sources

def collect_rss_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    for source in RSS_SOURCES + google_news_sources():
        log.info('Reading RSS: %s', source['name'])
        if source.get('aggregator') == 'google':
            time.sleep(GOOGLE_NEWS_REQUEST_DELAY_SECONDS)
        feed = feedparser.parse(source['url'], agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
        if getattr(feed, 'bozo', False):
            log.warning('RSS warning for %s: %s', source['name'], getattr(feed, 'bozo_exception', 'unknown'))
        raw_entry_count = len(feed.entries)
        log.info('Raw entries for %s: %d', source['name'], raw_entry_count)
        for entry in list(feed.entries)[:RSS_ITEMS_PER_SOURCE]:
            source_url = canonicalise_url(str(getattr(entry, 'link', '') or ''))
            source_title = strip_markdown(getattr(entry, 'title', ''))
            summary_html = str(getattr(entry, 'summary', '') or getattr(entry, 'description', '') or '')
            summary = strip_markdown(BeautifulSoup(summary_html, 'lxml').get_text(' ', strip=True))
            published = entry_datetime(entry)
            source_name = source['name']
            entry_source = getattr(entry, 'source', None)
            if isinstance(entry_source, dict):
                source_name = strip_markdown(entry_source.get('title')) or source_name
                entry_source_url = str(entry_source.get('href') or '')
            else:
                entry_source_url = ''
            if source_is_denied(source_name, entry_source_url or source_url):
                log.info('Blocked prohibited source: %s', source_name or source_url)
                continue
            text = f'{source_title} {summary}'
            if not source_url or not source_title or (not is_fresh(published)):
                continue
            if should_drop(text, source_url):
                continue
            locality_source_url = entry_source_url or source_url
            if not location_query_result_allowed(
                text,
                source_name,
                locality_source_url,
                str(source.get('query_location_slug') or ''),
            ):
                continue
            if not source_text_is_local(
                text,
                source_name,
                locality_source_url,
                bool(source.get('trusted_local')),
            ):
                continue
            image_url = rss_image(entry)
            body_excerpt = summary
            if source.get('aggregator') != 'google' and (not source.get('rss_only')) and (not image_url or len(summary) < 100):
                try:
                    meta = page_metadata(source_url)
                    source_title = meta['title'] or source_title
                    summary = meta['description'] or summary
                    image_url = image_url or meta['image']
                    body_excerpt = meta['body_excerpt'] or body_excerpt
                    page_date = parse_datetime(meta['published'])
                    if page_date:
                        published = page_date
                except Exception as exc:
                    log.debug('Metadata fallback failed for %s: %s', source_url, exc)
            if not is_fresh(published):
                continue
            combined = f'{source_title} {summary} {body_excerpt}'
            candidates.append(Candidate(
                source_name=source_name,
                source_url=source_url,
                source_title=source_title,
                source_summary=summary,
                source_published_at=iso_utc(published),
                area=source_text_area(
                    combined,
                    source['default_area'],
                    source_name,
                    entry_source_url or source_url,
                    bool(source.get('trusted_local')),
                ),
                category=(
                    categorise(combined)
                    if categorise(combined) != 'news'
                    else source.get('query_category') or source.get('default_category', 'news')
                ),
                image_candidate_url=image_url,
                source_body_excerpt=body_excerpt,
                source_kind='publisher_rss' if source.get('rss_only') else 'article',
                discovery_query_label=str(source.get('query_label') or ''),
                searched_location_slug=str(source.get('query_location_slug') or ''),
                searched_location_name=str(source.get('query_location_name') or ''),
            ))
    return candidates

def discovery_listing_urls(source: dict[str, Any]) -> list[str]:
    configured = DISCOVERY_LISTING_OVERRIDES.get(source['name'], [])
    page_limit = max(1, int(source.get('page_limit') or DISCOVERY_PAGE_LIMIT))
    if configured:
        return configured[:page_limit]
    listing_urls = source.get('listing_urls') or []
    if listing_urls:
        return [str(url) for url in listing_urls[:page_limit]]
    return [source['url']]

def discovery_links(source: dict[str, str]) -> list[str]:
    pattern = re.compile(source['link_pattern'], re.IGNORECASE)
    links: list[str] = []
    seen: set[str] = set()
    for listing_url in discovery_listing_urls(source):
        try:
            final_url, raw_html = fetch_html(listing_url)
        except Exception as exc:
            log.warning('Discovery page failed for %s (%s): %s', source['name'], listing_url, exc)
            continue
        soup = BeautifulSoup(raw_html, 'lxml')
        for anchor in soup.find_all('a', href=True):
            url = canonicalise_url(urljoin(final_url, anchor['href']))
            if url in seen or domain_of(url) != domain_of(final_url):
                continue
            if source_is_denied(source.get('name', ''), url):
                continue
            if not pattern.search(urlparse(url).path + '?' + urlparse(url).query):
                continue
            seen.add(url)
            links.append(url)
            if len(links) >= DISCOVERY_LINKS_PER_SOURCE:
                return links
    return links

def _discovery_candidate(source: dict[str, str], url: str) -> Candidate | None:
    if source_is_denied(source.get('name', ''), url):
        return None
    try:
        meta = page_metadata(url)
    except PermissionError as exc:
        log.info('%s', exc)
        return None
    except Exception as exc:
        log.debug('Page metadata failed for %s: %s', url, exc)
        return None
    text = f"{meta['title']} {meta['description']} {meta['body_excerpt']}"
    trusted_local = bool(source.get('trusted_local'))
    if not meta['title'] or should_drop(text, meta['url']) or (not source_text_is_local(text, source['name'], meta['url'], trusted_local)):
        return None
    source_name_lower = source['name'].lower()
    event_start = parse_datetime(meta.get('event_start'))
    is_event = meta.get('content_type') == 'event' or 'event' in source_name_lower or "what's on" in source_name_lower or ('/events/' in urlparse(url).path.lower())
    if is_event and event_is_current_or_future(event_start):
        published = utc_now()
        source_kind = 'event'
        category = 'events'
    else:
        published = parse_datetime(meta.get('published'))
        source_kind = 'article'
        detected_category = categorise(text)
        category = detected_category if detected_category != 'news' else source.get('default_category', 'news')
        if not is_fresh(published):
            if source_name_lower in LIVE_SOURCE_NAMES and len(text) >= 80:
                published = utc_now()
                source_kind = 'live'
            else:
                return None
    return Candidate(source_name=source['name'], source_url=meta['url'], source_title=meta['title'], source_summary=meta['description'] or meta['body_excerpt'][:900], source_published_at=iso_utc(published), area=source_text_area(text, source['default_area'], source['name'], meta['url'], trusted_local), category=category, image_candidate_url=meta['image'], source_body_excerpt=meta['body_excerpt'], event_start_at=iso_utc(event_start) if event_start else '', event_end_at=meta.get('event_end', ''), event_location=meta.get('event_location', ''), source_kind=source_kind)

def collect_discovery_candidates() -> list[Candidate]:
    jobs: list[tuple[dict[str, str], str]] = []
    for source in DISCOVERY_PAGES:
        if source_is_denied(source.get('name', ''), source.get('url', '')):
            continue
        log.info('Discovering pages: %s', source['name'])
        jobs.extend(((source, url) for url in discovery_links(source)))
    candidates: list[Candidate] = []
    with ThreadPoolExecutor(max_workers=max(1, DISCOVERY_WORKERS)) as executor:
        future_map = {executor.submit(_discovery_candidate, source, url): (source['name'], url) for source, url in jobs}
        for future in as_completed(future_map):
            try:
                candidate = future.result()
            except Exception as exc:
                source_name, url = future_map[future]
                log.debug('Discovery worker failed for %s %s: %s', source_name, url, exc)
                continue
            if candidate:
                candidates.append(candidate)
    return candidates

def _embedded_external_url(raw_url: str, base_url: str) -> str:
    """Return a direct external URL from an aggregator anchor where possible."""
    absolute = urljoin(base_url, raw_url)
    parsed = urlparse(absolute)
    query = urllib.parse.parse_qs(parsed.query)
    for key in ('url', 'u', 'target', 'destination', 'redirect', 'redirect_url'):
        values = query.get(key) or []
        for value in values:
            decoded = urllib.parse.unquote(str(value))
            if decoded.startswith(('http://', 'https://')):
                return canonicalise_url(decoded)
    return canonicalise_url(absolute)

def aggregator_outbound_links(source: dict[str, Any]) -> list[str]:
    try:
        final_url, raw_html = fetch_html(source['url'])
    except Exception as exc:
        log.warning('Aggregator page failed for %s: %s', source['name'], exc)
        return []
    aggregator_domain = domain_of(final_url)
    links: list[str] = []
    seen: set[str] = set()
    soup = BeautifulSoup(raw_html, 'lxml')
    max_links = max(1, int(source.get('max_links') or 30))
    for anchor in soup.find_all('a', href=True):
        url = _embedded_external_url(str(anchor.get('href') or ''), final_url)
        domain = domain_of(url)
        if not url.startswith(('http://', 'https://')) or not domain or domain == aggregator_domain or (domain in {'facebook.com', 'x.com', 'twitter.com', 'instagram.com'}) or source_is_denied('', url) or (url in seen):
            continue
        seen.add(url)
        links.append(url)
        if len(links) >= max_links:
            break
    return links

def _publisher_name_for_url(url: str) -> str:
    domain = domain_of(url)
    stem = domain.split('.')[0].replace('-', ' ').strip()
    return stem.title() if stem else domain

def collect_aggregator_candidates() -> list[Candidate]:
    """Use NewsNow/Ground News only to discover original publisher pages."""
    jobs: list[tuple[dict[str, Any], str]] = []
    for aggregator in AGGREGATOR_PAGES:
        log.info('Discovering outbound publisher links: %s', aggregator['name'])
        for url in aggregator_outbound_links(aggregator):
            source = {'name': _publisher_name_for_url(url), 'url': url, 'default_area': aggregator.get('default_area', 'rochdale'), 'default_category': aggregator.get('default_category', 'news'), 'trusted_local': False}
            jobs.append((source, url))
    candidates: list[Candidate] = []
    with ThreadPoolExecutor(max_workers=max(1, DISCOVERY_WORKERS)) as executor:
        future_map = {executor.submit(_discovery_candidate, source, url): url for source, url in jobs}
        for future in as_completed(future_map):
            try:
                candidate = future.result()
            except Exception as exc:
                log.debug('Aggregator outbound worker failed for %s: %s', future_map[future], exc)
                continue
            if candidate:
                candidate.source_kind = 'aggregator_discovered_article'
                candidates.append(candidate)
    return candidates

def collect_live_page_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    for source in LIVE_PAGE_SOURCES:
        if source_is_denied(source['name'], source['url']):
            continue
        try:
            final_url, raw_html = fetch_html(source['url'])
        except Exception as exc:
            log.warning('Live page failed for %s: %s', source['name'], exc)
            continue
        soup = BeautifulSoup(raw_html, 'lxml')
        blocks: list[str] = []
        seen_blocks: set[str] = set()
        trusted_local = bool(source.get('trusted_local'))
        max_blocks = max(1, int(source.get('max_blocks') or 12))
        if source.get('whole_page'):
            main_node = soup.select_one('main') or soup.body or soup
            whole_text = normalise_ws(main_node.get_text(' ', strip=True))
            if len(whole_text) >= 45:
                blocks.append(whole_text[:5000])
        else:
            for node in soup.select('article, li, section, .alert, .travel-alert, .service-update, main p'):
                block_text = normalise_ws(node.get_text(' ', strip=True))
                if len(block_text) < 45:
                    continue
                if not source_text_is_local(block_text, source['name'], final_url, trusted_local):
                    continue
                key = block_text.lower()[:240]
                if key in seen_blocks:
                    continue
                seen_blocks.add(key)
                blocks.append(block_text)
                if len(blocks) >= max_blocks:
                    break
        for block in blocks[:max_blocks]:
            if not source_text_is_local(block, source['name'], final_url, trusted_local):
                continue
            area = source_text_area(block, source['default_area'], source['name'], final_url, trusted_local)
            if not area:
                continue
            short = normalise_ws(str(source.get('title') or ''))
            if not short:
                short = block[:145].rsplit(' ', 1)[0]
            candidates.append(Candidate(source_name=source['name'], source_url=f'{canonicalise_url(final_url)}#live-{stable_id(block)}', source_title=short[:160], source_summary=block[:1000], source_published_at=iso_utc(utc_now()), area=area, category=live_category(block, source['category']), source_body_excerpt=block[:3500], source_kind='live'))
    return candidates

def extract_future_event_date(text: str) -> str:
    """
    Extract a likely future event date from visible Facebook event-card text.

    Facebook's discovery UI changes frequently, so this is intentionally
    conservative. It returns an empty string if no plausible date is found.
    """
    cleaned = normalise_ws(text)
    if not cleaned:
        return ''
    try:
        matches = search_dates(cleaned, languages=['en'], settings={'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': utc_now(), 'RETURN_AS_TIMEZONE_AWARE': True, 'TIMEZONE': 'Europe/London', 'TO_TIMEZONE': 'UTC'}) or []
    except Exception:
        return ''
    for matched_text, value in matches[:5]:
        if value is None:
            continue
        value_utc = value.astimezone(timezone.utc)
        if utc_now() - timedelta(hours=12) <= value_utc <= utc_now() + timedelta(days=550):
            return iso_utc(value_utc)
    return ''

def clean_facebook_event_title(value: str) -> str:
    title = strip_markdown(value)
    title = re.sub('^(?:Facebook|Events?|Interested|Going|Share)\\s*[-:|]\\s*', '', title, flags=re.IGNORECASE)
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
    if not FACEBOOK_EVENTS_BROWSER_ENABLED:
        log.info('Facebook Events browser collection skipped on this frequent run; the hourly browser-enabled run will collect it.')
        return []
    if not FACEBOOK_EVENTS_DISCOVERY_URL:
        return []
    log.info('Reading Facebook Events discovery source: %s', FACEBOOK_EVENTS_DISCOVERY_URL)
    raw_cards: list[dict[str, str]] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--disable-dev-shm-usage', '--no-sandbox', '--disable-blink-features=AutomationControlled'])
            context = browser.new_context(locale='en-GB', timezone_id='Europe/London', viewport={'width': 1440, 'height': 1100}, user_agent=SESSION.headers['User-Agent'])
            page = context.new_page()
            page.set_default_timeout(FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS)
            try:
                page.goto(FACEBOOK_EVENTS_DISCOVERY_URL, wait_until='domcontentloaded', timeout=FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                log.warning('Facebook Events discovery page timed out during initial load.')
            for label in ('Allow all cookies', 'Decline optional cookies', 'Only allow essential cookies', 'Close', 'Not now'):
                try:
                    button = page.get_by_role('button', name=re.compile(label, re.I))
                    if button.count():
                        button.first.click(timeout=1500)
                except Exception:
                    pass
            page.wait_for_timeout(3500)
            for _ in range(4):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(900)
            body_text = normalise_ws(page.locator('body').inner_text(timeout=5000))
            if re.search('\\blog in\\b|\\bsign up\\b', body_text, flags=re.IGNORECASE):
                log.info('Facebook displayed a login prompt; checking for public event cards.')
            raw_cards = page.evaluate('\n                () => {\n                  const results = [];\n                  const seen = new Set();\n                  const links = Array.from(document.querySelectorAll(\'a[href*="/events/"]\'));\n\n                  for (const link of links) {\n                    const rawHref = link.href || link.getAttribute(\'href\') || \'\';\n                    const match = rawHref.match(/facebook\\.com\\/events\\/(\\d+)/i);\n                    if (!match) continue;\n\n                    const eventUrl = `https://www.facebook.com/events/${match[1]}/`;\n                    if (seen.has(eventUrl)) continue;\n                    seen.add(eventUrl);\n\n                    let card = link.closest(\'[role="article"]\');\n                    if (!card) {\n                      let current = link;\n                      for (let depth = 0; depth < 7 && current; depth += 1) {\n                        if (current.querySelector && current.querySelector(\'img\')) {\n                          card = current;\n                        }\n                        current = current.parentElement;\n                      }\n                    }\n                    card = card || link.parentElement || link;\n\n                    const text = (card.innerText || link.innerText || \'\').trim();\n                    const aria = (link.getAttribute(\'aria-label\') || \'\').trim();\n                    const image = card.querySelector ? card.querySelector(\'img[src]\') : null;\n                    const title =\n                      aria ||\n                      (link.innerText || \'\').trim() ||\n                      (text.split(\'\\n\').find(line => line.trim().length > 3) || \'\');\n\n                    results.push({\n                      url: eventUrl,\n                      title,\n                      text,\n                      image: image ? (image.currentSrc || image.src || \'\') : \'\',\n                    });\n\n                    if (results.length >= 40) break;\n                  }\n                  return results;\n                }\n                ')
            context.close()
            browser.close()
    except Exception as exc:
        log.warning('Facebook Events browser collector unavailable: %s', exc)
        return []
    if not raw_cards:
        log.warning('No public event cards were exposed by the supplied Facebook Events page. The source remains configured and will be retried on the next run.')
        return []
    candidates: list[Candidate] = []
    seen_urls: set[str] = set()
    for card in raw_cards:
        event_url = canonicalise_url(card.get('url', ''))
        if not event_url or event_url in seen_urls:
            continue
        seen_urls.add(event_url)
        visible_text = strip_markdown(card.get('text', ''))
        title = clean_facebook_event_title(card.get('title', ''))
        if not title or len(title) < 4:
            lines = [normalise_ws(line) for line in str(card.get('text', '')).splitlines()]
            title = next((line for line in lines if len(line) >= 4), '')
            title = clean_facebook_event_title(title)
        if not title:
            continue
        combined = f'{title} {visible_text}'
        if not source_text_is_local(combined, 'Facebook Events — Rochdale discovery', event_url, True):
            continue
        event_start = extract_future_event_date(visible_text)
        image_url = str(card.get('image') or '').strip()
        summary_parts = [visible_text]
        if event_start:
            summary_parts.append(f'Structured event start: {event_start}')
        summary = normalise_ws(' '.join(summary_parts))[:1600]
        candidates.append(Candidate(source_name='Facebook Events — Rochdale discovery', source_url=event_url, source_title=title, source_summary=summary, source_published_at=iso_utc(utc_now()), area=detect_area(combined, 'rochdale', 'Facebook Events — Rochdale discovery', event_url), category='events', image_candidate_url=image_url, source_body_excerpt=visible_text[:4000], event_start_at=event_start, event_location='Rochdale area', source_kind='event'))
        if len(candidates) >= FACEBOOK_EVENTS_MAX:
            break
    log.info('Facebook Events discovery collected %d public event listings.', len(candidates))
    return candidates
SOCIAL_STOPWORDS = {'about', 'after', 'again', 'against', 'been', 'before', 'being', 'between', 'could', 'from', 'have', 'into', 'local', 'more', 'news', 'people', 'rochdale', 'said', 'that', 'their', 'there', 'these', 'they', 'this', 'today', 'under', 'what', 'when', 'where', 'which', 'with', 'would', 'your', 'heywood', 'middleton', 'littleborough'}
SOCIAL_UNSAFE_PATTERNS = ['\\b(name and shame|paedophile|pedophile|rapist|murderer|terrorist)\\b', '\\b(he did it|she did it|they did it|definitely guilty|must be guilty)\\b', '\\bI know who\\b|\\bthe suspect is\\b|\\bthe offender is\\b', '\\bkill (?:him|her|them)\\b|\\bdeserves to die\\b']
URL_RE = re.compile('https?://\\S+|www\\.\\S+', re.IGNORECASE)
EMAIL_RE = re.compile('\\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}\\b', re.IGNORECASE)
PHONE_RE = re.compile('(?<!\\d)(?:\\+?44\\s?|0)\\d(?:[\\s()-]*\\d){8,12}(?!\\d)')
_FACEBOOK_SOCIAL_CACHE: list[dict[str, Any]] | None = None
_X_SOCIAL_CACHE: list[dict[str, Any]] | None = None

def participant_digest(platform: str, identifier: str) -> str:
    raw = f'{platform}:{identifier}'.encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:16]

def sanitise_social_text(value: Any) -> str:
    text = strip_markdown(value)
    text = URL_RE.sub('', text)
    text = EMAIL_RE.sub('', text)
    text = PHONE_RE.sub('', text)
    text = POSTCODE_RE.sub('the local area', text)
    text = ADDRESS_RE.sub('a local location', text)
    text = re.sub('(?<!\\w)@[A-Za-z0-9_]{1,30}', '', text)
    text = re.sub('\\s+', ' ', text).strip()
    return text[:700]

def public_reaction_is_usable(text: str) -> bool:
    if len(text) < 18:
        return False
    return not any((re.search(pattern, text, flags=re.IGNORECASE) for pattern in SOCIAL_UNSAFE_PATTERNS))

def social_tokens(value: str) -> set[str]:
    return {token for token in re.findall('[a-z0-9]+', value.lower()) if len(token) >= 4 and token not in SOCIAL_STOPWORDS}

def social_record_score(candidate: Candidate, record: dict[str, Any]) -> float:
    candidate_text = f'{candidate.source_title} {candidate.source_summary} {candidate.source_body_excerpt[:1200]}'
    record_text = f"{record.get('parent_text', '')} {record.get('text', '')}"
    candidate_tokens = social_tokens(candidate_text)
    record_tokens = social_tokens(record_text)
    if not candidate_tokens or not record_tokens:
        return 0.0
    overlap = candidate_tokens & record_tokens
    if len(overlap) < 2:
        return 0.0
    score = len(overlap) / max(4, min(len(candidate_tokens), len(record_tokens)))
    candidate_url = canonicalise_url(candidate.source_url)
    for related_url in record.get('related_urls', []) or []:
        if canonicalise_url(str(related_url)) == candidate_url:
            score += 2.0
    if record.get('official'):
        score += 0.12
    if record.get('parent_url') == candidate_url:
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
        log.info('X social correlation inactive: add the X_BEARER_TOKEN GitHub secret.')
        _X_SOCIAL_CACHE = []
        return _X_SOCIAL_CACHE
    records_by_id: dict[str, dict[str, Any]] = {}
    headers = {'Authorization': f'Bearer {X_BEARER_TOKEN}'}
    for query in X_SEARCH_QUERIES:
        params = {'query': query, 'start_time': today_start_utc(), 'max_results': X_RECENT_SEARCH_MAX, 'tweet.fields': 'created_at,author_id,conversation_id,in_reply_to_user_id,public_metrics,referenced_tweets,entities,lang', 'expansions': 'author_id', 'user.fields': 'username,name,verified,protected'}
        try:
            response = SESSION.get(f'{X_API_BASE}/tweets/search/recent', headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            log.warning('X recent-search query failed: %s', exc)
            continue
        users = {str(user.get('id')): user for user in payload.get('includes', {}).get('users', [])}
        for post in payload.get('data', []) or []:
            post_id = str(post.get('id') or '')
            text = sanitise_social_text(post.get('text', ''))
            created = parse_datetime(post.get('created_at'))
            if not post_id or not text or (not is_fresh(created)):
                continue
            user = users.get(str(post.get('author_id') or ''), {})
            username = str(user.get('username') or '').lstrip('@')
            username_lower = username.lower()
            official = username_lower in OFFICIAL_X_HANDLES
            trusted_local_handle = username_lower == 'gmprochdale'
            post_url = f'https://x.com/{username}/status/{post_id}' if username else f'https://x.com/i/web/status/{post_id}'
            source_name = OFFICIAL_X_HANDLES.get(username_lower) if official else 'X public post'
            if not source_text_is_local(text, str(source_name or ''), post_url, trusted_local_handle):
                continue
            referenced = post.get('referenced_tweets') or []
            is_reply = any((str(item.get('type')) == 'replied_to' for item in referenced if isinstance(item, dict)))
            related_urls = []
            for url_item in (post.get('entities') or {}).get('urls', []) or []:
                expanded = url_item.get('expanded_url') or url_item.get('unwound_url') or url_item.get('url')
                if expanded:
                    related_urls.append(str(expanded))
            metrics = post.get('public_metrics') or {}
            records_by_id[post_id] = {'record_id': f'x:{post_id}', 'platform': 'x', 'kind': 'reply' if is_reply else 'post', 'official': official, 'source_name': OFFICIAL_X_HANDLES.get(username_lower) if official else 'Public X discussion', 'trusted_local': trusted_local_handle, 'publish_as_source': official, 'text': text, 'created_at': iso_utc(created), 'url': post_url, 'parent_url': '', 'parent_text': '', 'conversation_id': str(post.get('conversation_id') or ''), 'participant_hash': participant_digest('x', str(post.get('author_id') or post_id)), 'related_urls': related_urls, 'engagement': int(metrics.get('like_count') or 0) + int(metrics.get('reply_count') or 0) + int(metrics.get('retweet_count') or 0)}
    for record in records_by_id.values():
        conversation_id = record.get('conversation_id')
        parent = records_by_id.get(str(conversation_id))
        if record.get('kind') == 'reply' and parent:
            record['parent_text'] = parent.get('text', '')
            record['parent_url'] = parent.get('url', '')
    _X_SOCIAL_CACHE = list(records_by_id.values())
    log.info('X social records collected: %d', len(_X_SOCIAL_CACHE))
    return _X_SOCIAL_CACHE

def collect_facebook_social_records() -> list[dict[str, Any]]:
    global _FACEBOOK_SOCIAL_CACHE
    if _FACEBOOK_SOCIAL_CACHE is not None:
        return _FACEBOOK_SOCIAL_CACHE
    if not SOCIAL_CONTEXT_ENABLED or not FACEBOOK_PAGE_ACCESS_TOKEN:
        log.info('Facebook comment correlation inactive: add the FACEBOOK_PAGE_ACCESS_TOKEN secret with the required Page access.')
        _FACEBOOK_SOCIAL_CACHE = []
        return _FACEBOOK_SOCIAL_CACHE
    records: list[dict[str, Any]] = []
    for page in PUBLIC_FACEBOOK_PAGES:
        handle = str(page['handle']).strip('/')
        endpoint = f'https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/{handle}/posts'
        params = {'access_token': FACEBOOK_PAGE_ACCESS_TOKEN, 'fields': 'id,message,created_time,permalink_url,full_picture', 'limit': '30'}
        try:
            response = SESSION.get(endpoint, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            log.warning('Facebook Page source unavailable for %s: %s', page['name'], exc)
            continue
        for post in payload.get('data', []) or []:
            post_id = str(post.get('id') or '')
            message = sanitise_social_text(post.get('message', ''))
            created = parse_datetime(post.get('created_time'))
            permalink = canonicalise_url(str(post.get('permalink_url') or ''))
            if not post_id or not message or (not is_fresh(created)):
                continue
            trusted_local = bool(page.get('trusted_local'))
            if should_drop(message, permalink) or not source_text_is_local(message, page['name'], permalink, trusted_local):
                continue
            records.append({'record_id': f'facebook-post:{post_id}', 'platform': 'facebook', 'kind': 'official_post', 'official': bool(page.get('official', True)), 'publish_as_source': bool(page.get('publish_as_source', page.get('official', True))), 'trusted_local': trusted_local, 'source_name': page['name'], 'text': message, 'created_at': iso_utc(created), 'url': permalink, 'parent_url': '', 'parent_text': '', 'participant_hash': participant_digest('facebook-page', handle.lower()), 'related_urls': [permalink] if permalink else [], 'engagement': 0, 'image': str(post.get('full_picture') or '')})
            if not FACEBOOK_COMMENTS_ENABLED:
                continue
            comment_endpoint = f'https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/{post_id}/comments'
            comment_params = {'access_token': FACEBOOK_PAGE_ACCESS_TOKEN, 'fields': 'id,message,created_time,like_count,comment_count,from{id}', 'filter': 'stream', 'limit': '100'}
            try:
                comment_response = SESSION.get(comment_endpoint, params=comment_params, timeout=REQUEST_TIMEOUT)
                comment_response.raise_for_status()
                comments = comment_response.json().get('data', []) or []
            except Exception as exc:
                log.info('Facebook comments unavailable for post %s: %s', post_id, exc)
                comments = []
            for comment in comments:
                comment_id = str(comment.get('id') or '')
                comment_text = sanitise_social_text(comment.get('message', ''))
                comment_created = parse_datetime(comment.get('created_time'))
                if not comment_id or not comment_text or (not is_fresh(comment_created)) or (not public_reaction_is_usable(comment_text)):
                    continue
                from_id = str((comment.get('from') or {}).get('id') or comment_id)
                records.append({'record_id': f'facebook-comment:{comment_id}', 'platform': 'facebook', 'kind': 'public_comment', 'official': False, 'source_name': 'Public Facebook comments', 'text': comment_text, 'created_at': iso_utc(comment_created), 'url': permalink, 'parent_url': permalink, 'parent_text': message, 'participant_hash': participant_digest('facebook', from_id), 'related_urls': [permalink] if permalink else [], 'engagement': int(comment.get('like_count') or 0) + int(comment.get('comment_count') or 0)})
    _FACEBOOK_SOCIAL_CACHE = records
    log.info('Facebook social records collected: %d', len(records))
    return records

def official_social_records_to_candidates(records: list[dict[str, Any]]) -> list[Candidate]:
    candidates: list[Candidate] = []
    for record in records:
        if not (record.get('official') or record.get('publish_as_source')):
            continue
        text = sanitise_social_text(record.get('text', ''))
        created = parse_datetime(record.get('created_at'))
        url = canonicalise_url(str(record.get('url') or ''))
        if not text or not url or (not is_fresh(created)):
            continue
        title = text.split('.')[0].strip()
        if len(title) < 35:
            title = text[:155].rsplit(' ', 1)[0]
        candidates.append(Candidate(source_name=str(record.get('source_name') or 'Official social update'), source_url=url, source_title=title[:160], source_summary=text[:1000], source_published_at=iso_utc(created), area=source_text_area(text, 'rochdale', str(record.get('source_name') or ''), url, bool(record.get('trusted_local'))), category=categorise(text), image_candidate_url=str(record.get('image') or ''), source_body_excerpt=text[:3500], source_kind='official_social'))
    return candidates

def correlate_social_context(candidates: list[Candidate], records: list[dict[str, Any]]) -> None:
    if not SOCIAL_CONTEXT_ENABLED or not records:
        return
    for candidate in candidates:
        source_text = f'{candidate.source_title} {candidate.source_summary} {candidate.source_body_excerpt}'
        sensitive = is_sensitive(source_text, candidate.category)
        scored = []
        for record in records:
            score = social_record_score(candidate, record)
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda item: (item[0], int(item[1].get('engagement') or 0)), reverse=True)
        official_updates = []
        public_reactions = []
        seen_official_urls = set()
        seen_participants = set()
        for score, record in scored:
            if record.get('official'):
                url = str(record.get('url') or '')
                if url in seen_official_urls:
                    continue
                seen_official_urls.add(url)
                official_updates.append({'platform': record.get('platform'), 'kind': 'official_update', 'source_name': record.get('source_name'), 'text': sanitise_social_text(record.get('text', '')), 'url': url, 'score': round(score, 3)})
                if len(official_updates) >= SOCIAL_MAX_OFFICIAL_UPDATES:
                    continue
            elif not sensitive and record.get('kind') in {'public_comment', 'reply', 'post'}:
                participant = str(record.get('participant_hash') or '')
                if not participant or participant in seen_participants:
                    continue
                text = sanitise_social_text(record.get('text', ''))
                if not public_reaction_is_usable(text):
                    continue
                seen_participants.add(participant)
                public_reactions.append({'platform': record.get('platform'), 'kind': 'public_reaction', 'text': text, 'score': round(score, 3)})
                if len(public_reactions) >= SOCIAL_MAX_PUBLIC_REACTIONS:
                    continue
        if len(public_reactions) < SOCIAL_MIN_PUBLIC_REACTIONS:
            public_reactions = []
        for item in official_updates:
            if item['url'] and all((existing.get('url') != item['url'] for existing in candidate.related_sources)):
                candidate.related_sources.append({'name': item['source_name'], 'url': item['url'], 'title': item['text'][:160], 'summary': item['text'][:900], 'published_at': '', 'source_kind': 'official_social'})
        candidate.social_context = official_updates + public_reactions

def collect_facebook_candidates() -> list[Candidate]:
    return official_social_records_to_candidates(collect_facebook_social_records())

def collect_x_candidates() -> list[Candidate]:
    return official_social_records_to_candidates(collect_x_social_records())

def collect_environment_agency_flood_candidates() -> list[Candidate]:
    """
    Fetch active flood alerts/warnings within 25 km of central Rochdale using
    the Environment Agency real-time flood-monitoring API.
    """
    endpoint = 'https://environment.data.gov.uk/flood-monitoring/id/floods'
    params = {'lat': '53.6097', 'long': '-2.1561', 'dist': '25'}
    try:
        response = SESSION.get(endpoint, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log.warning('Environment Agency flood feed unavailable: %s', exc)
        return []
    candidates: list[Candidate] = []
    for item in payload.get('items', []):
        severity_level = int(item.get('severityLevel') or 4)
        if severity_level >= 4:
            continue
        changed = parse_datetime(item.get('timeMessageChanged') or item.get('timeSeverityChanged') or item.get('timeRaised')) or utc_now()
        area_name = strip_markdown(item.get('eaAreaName') or item.get('description') or item.get('floodArea', {}).get('label') or 'Rochdale flood alert')
        message = strip_markdown(item.get('message') or item.get('description') or '')
        title = f"{item.get('severity', 'Flood alert')}: {area_name}"
        source_url = str(item.get('@id') or endpoint).replace('http://', 'https://')
        text = f'{title} {message}'
        if not is_local(text, 'Environment Agency flood-monitoring API', source_url):
            continue
        detected_area = detect_area(text)
        if not detected_area:
            continue
        candidates.append(Candidate(source_name='Environment Agency flood-monitoring API', source_url=source_url, source_title=title[:160], source_summary=message[:900], source_published_at=iso_utc(changed), area=detected_area, category='environment', source_body_excerpt=message[:3500]))
    return candidates

def collect_food_hygiene_candidates() -> list[Candidate]:
    """New low food hygiene ratings in the borough, from the FSA's open API.

    Primary data, not aggregation: the FSA publishes this API for reuse, so
    there is no robots.txt question and no other outlet to rewrite. Prose is
    generated deterministically in food_hygiene.py from published facts only.
    """
    if os.getenv('FOOD_HYGIENE_ENABLED', 'true').lower() != 'true':
        return []
    days = int(os.getenv('FOOD_HYGIENE_DAYS', '8'))
    max_rating = int(os.getenv('FOOD_HYGIENE_MAX_RATING', '2'))
    try:
        records = fetch_recent_low_ratings(SESSION.get, days=days, max_rating=max_rating)
    except Exception as exc:
        log.warning('FSA food hygiene API unavailable: %s', exc)
        return []
    candidates: list[Candidate] = []
    for record in records:
        fields = rating_article_fields(record)
        text = f"{fields['title']} {fields['summary']}"
        detected_area = detect_area(text) or 'rochdale'
        candidates.append(Candidate(
            source_name='Food Standards Agency',
            source_url=record['url'],
            source_title=fields['title'][:160],
            source_summary=fields['summary'][:900],
            source_published_at=iso_utc(record['rating_date']),
            area=detected_area,
            category='business',
            source_body_excerpt=fields['body'][:3500],
        ))
    return candidates

def candidate_related_record(candidate: Candidate) -> dict[str, str]:
    return {
        'name': candidate.source_name,
        'url': candidate.source_url,
        'title': candidate.source_title,
        'summary': candidate.source_summary[:1200],
        'published_at': candidate.source_published_at,
        'source_kind': candidate.source_kind,
        'discovery_query_label': candidate.discovery_query_label,
        'searched_location_slug': candidate.searched_location_slug,
        'searched_location_name': candidate.searched_location_name,
    }

def deduplicate_and_cross_reference(candidates: Iterable[Candidate]) -> list[Candidate]:
    ordered = sorted(candidates, key=lambda item: (authority_score(item), item.source_published_at), reverse=True)
    primaries: list[Candidate] = []
    seen_urls: set[str] = set()
    story_blocklist = load_story_blocklist()
    for candidate in ordered:
        if source_is_denied(candidate.source_name, candidate.source_url):
            continue
        if is_blocked_text(candidate.source_title, candidate.source_url, story_blocklist):
            continue
        if not candidate.area:
            continue
        candidate.related_sources = [item for item in candidate.related_sources if not source_is_denied(item.get('name', ''), item.get('url', ''))]
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
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def recent_existing_articles() -> list[dict[str, Any]]:
    kept = []
    story_blocklist = load_story_blocklist()
    for article in load_json_list(OUTPUT_FILE):
        if (is_job_or_career_post(article) or is_classified_listing_post(article)):
            continue
        if is_blocked_article(article, story_blocklist):
            log.warning('Dropped editorially removed story from retained feed: %s', article.get('title'))
            continue
        source_name = str(article.get('source_name') or '')
        source_url = str(article.get('source_url') or '')
        if source_is_denied(source_name, source_url):
            continue
        if not article.get('editorial_lock'):
            # The editorial gate only vets NEW rewrites, so an advert or
            # listing that slipped in before the gate existed would
            # otherwise persist for its full retention window (a house-
            # rental listing and a property-auction listing both did).
            # Apply the same cheap template-language check to retained
            # headlines and standfirsts on every run. Hand-locked articles
            # are exempt: the editor has explicitly approved those.
            probe = _plain_text(f"{article.get('title') or ''} {article.get('excerpt') or ''}")
            if should_drop(probe, source_url):
                log.warning('Purged advert/listing-style article from retained feed: %s', article.get('title'))
                continue
            # Self-heal misplaced editorial furniture in retained copy: the
            # Crimestoppers service sentence belongs only in crime reports,
            # and the sympathy line only in reports of a death. The model
            # was adding both to everything, which also poisoned category
            # scoring ("police" filed community stories as crime).
            body = str(article.get('content_html') or '')
            if body:
                cleaned = body
                if str(article.get('category') or '') != 'crime':
                    cleaned = SERVICE_SENTENCE_RE.sub(' ', cleaned)
                plain_body = _plain_text(SYMPATHY_SENTENCE_RE.sub(' ', cleaned))
                if not re.search('\\b(?:died|dies|death|dead|killed|fatal(?:ly)?|inquest|funeral|passed away)\\b', plain_body, flags=re.IGNORECASE):
                    cleaned = SYMPATHY_SENTENCE_RE.sub(' ', cleaned)
                if cleaned != body:
                    cleaned = re.sub('\\s+', ' ', cleaned)
                    cleaned = re.sub('<p>\\s*</p>', '', cleaned)
                    article['content_html'] = cleaned.strip()
                    article['excerpt'] = normalise_ws(SYMPATHY_SENTENCE_RE.sub(' ', SERVICE_SENTENCE_RE.sub(' ', str(article.get('excerpt') or ''))))
        if article_is_low_quality(article):
            log.warning('Removed low-quality template article so it can be rewritten: %s', article.get('title'))
            continue
        published = parse_datetime(article.get('published_at'))
        source_kind = str(article.get('source_kind') or 'article')
        event_start = parse_datetime(article.get('event_start_at'))
        keep = is_fresh(published) or (source_kind == 'event' and event_is_current_or_future(event_start)) or (source_kind == 'live' and is_current_uk_day(published))
        if keep and article_passes_locality(article):
            article['title'] = strip_markdown(article.get('title'))
            article['excerpt'] = strip_markdown(article.get('excerpt'))
            # Self-heal categories on retained articles: score-based
            # recategorisation from the article's own final text, so old
            # stock misfiled by first-match category selection (a football
            # report labelled traffic because one paragraph mentioned
            # matchday congestion) is corrected on the next run. When the
            # card image is a category stock image, it moves with the
            # category; genuine source images are never touched.
            # Ticket events are exempt: their category is "events" by
            # definition, and text scoring misfiles them (a concert whose
            # only category keyword was "opening" scored as business).
            if source_kind == 'event':
                if article.get('category') != 'events' and not article.get('editorial_lock'):
                    article['category'] = 'events'
                    article['types'] = ['events']
                kept.append(article)
                continue
            text = ' '.join(str(article.get(field) or '') for field in ('title', 'excerpt', 'content_html'))
            corrected = editorial_category(text, fallback=str(article.get('category') or 'news'))
            if corrected != article.get('category') and not article.get('editorial_lock'):
                old_stock = CATEGORY_STOCK_IMAGES.get(str(article.get('category') or ''), '')
                if str(article.get('image_url') or '') == old_stock:
                    article['image_url'] = CATEGORY_STOCK_IMAGES.get(corrected, CATEGORY_STOCK_IMAGES['news'])
                article['category'] = corrected
                if corrected != 'crime':
                    article['police_matter'] = False
            kept.append(article)
    return dedupe_article_records(kept)

def _source_image_allowed(candidate: Candidate) -> bool:
    if not candidate.image_candidate_url:
        return False
    source_domain = domain_of(candidate.source_url)
    if candidate.source_kind == 'event' and source_domain == 'facebook.com':
        return FACEBOOK_EVENT_IMAGE_REUSE
    return USE_SOURCE_IMAGES and source_domain in IMAGE_REUSE_SOURCE_DOMAINS

def cache_source_image(candidate: Candidate, category: str) -> tuple[str, str]:
    if is_subtle_source(candidate.source_name, candidate.source_url):
        fallback = CATEGORY_STOCK_IMAGES.get(category, CATEGORY_STOCK_IMAGES['news'])
        return (fallback, 'Rochdale Daily category image')
    fallback = CATEGORY_STOCK_IMAGES.get(category, CATEGORY_STOCK_IMAGES['news'])
    if not _source_image_allowed(candidate):
        return (fallback, 'Rochdale Daily category image')
    target_name = f'{stable_id(candidate.source_url)}.jpg'
    relative_path = f'assets/img/generated/{target_name}'
    target_path = GENERATED_IMAGE_DIR / target_name
    if target_path.exists() and target_path.stat().st_size > 5000:
        return (relative_path, candidate.source_name)
    try:
        response = SESSION.get(candidate.image_candidate_url, timeout=REQUEST_TIMEOUT, stream=True, headers={'Referer': candidate.source_url})
        response.raise_for_status()
        content = response.content
        if len(content) > 10000000:
            raise ValueError('image exceeded 10 MB')
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image).convert('RGB')
        image = ImageOps.fit(image, (1200, 675), method=Image.Resampling.LANCZOS)
        image.save(target_path, format='JPEG', quality=86, optimize=True)
        return (relative_path, candidate.source_name)
    except (requests.RequestException, OSError, ValueError, UnidentifiedImageError) as exc:
        log.info('Could not cache source image for %s: %s', candidate.source_url, exc)
        return (fallback, 'Rochdale Daily category image')

def source_image(candidate: Candidate, category: str) -> tuple[str, str]:
    return cache_source_image(candidate, category)
POSTCODE_RE = re.compile('\\b[A-Z]{1,2}\\d[A-Z\\d]?\\s*\\d[A-Z]{2}\\b', re.IGNORECASE)
ADDRESS_RE = re.compile("\\b\\d{1,4}[A-Za-z]?\\s+(?:[A-Z][a-z'-]+\\s+){0,4}(?:Street|St|Road|Rd|Lane|Ln|Drive|Dr|Avenue|Ave|Close|Court|Way|Crescent|Place|Terrace|Gardens|Grove)\\b", re.IGNORECASE)
PERSON_RE = re.compile("\\b(?:Mr|Mrs|Ms|Miss|Dr)?\\s*([A-Z][a-z'-]+(?:\\s+[A-Z][a-z'-]+){1,2})\\b")
NAME_EXCLUSIONS = {'Greater Manchester', 'Rochdale Daily', 'Rochdale Council', 'Rochdale Borough Council', 'Greater Manchester Police', 'Manchester Evening News', 'Rochdale AFC', 'Rochdale Hornets', 'National Highways', 'Bee Network', 'Northern Care Alliance', 'Pennine Care', 'Hopwood Hall', 'United Kingdom'}

def source_person_names(text: str) -> set[str]:
    found = set()
    for match in PERSON_RE.finditer(text):
        name = normalise_ws(match.group(1))
        if name not in NAME_EXCLUSIONS and (not any((place.lower() in name.lower() for place in LOCAL_TERMS))):
            found.add(name)
    return found

def anonymise_output(text: str, source_text: str) -> str:
    result = POSTCODE_RE.sub('the Rochdale area', str(text or ''))
    result = ADDRESS_RE.sub('a location in the Rochdale borough', result)
    for name in sorted(source_person_names(source_text), key=len, reverse=True):
        result = re.sub(f'\\b{re.escape(name)}\\b', 'an individual', result, flags=re.IGNORECASE)
    result = re.sub("\\b(?:Mr|Mrs|Ms|Miss)\\s+[A-Z][a-z'-]+\\b", 'the individual', result)
    return strip_markdown(result)

def default_legal_disclaimer(sensitive: bool) -> str:
    if sensitive:
        return 'This report is based on information published by identified public sources. No finding of guilt should be inferred from an arrest, allegation or charge. Anyone accused of an offence is presumed innocent unless and until convicted, and the article may be updated as verified information changes.'
    return 'This article was compiled from identified public sources and may be updated when further verified information becomes available.'


GENERIC_ARTICLE_PATTERNS = (
    r"\bhas published (?:a|an) (?:crime|police|court|public[- ]safety|news) update\b",
    r"\bthe (?:source|source item|original source) is (?:linked|included|titled)\b",
    r"\bthe update was published by\b",
    r"\bhas been categorised as\b",
    r"\bfurther confirmed information will be added\b",
    r"\bwill update this report if the identified source\b",
    r"\bthe article remains open to correction\b",
    r"\bthis automated brief does not add\b",
    r"\breaders can use the source link\b",
)
GENERIC_ARTICLE_RE = re.compile("|".join(GENERIC_ARTICLE_PATTERNS), re.IGNORECASE)
QUALITY_STOPWORDS = {
    'about', 'after', 'again', 'against', 'also', 'among', 'because', 'before',
    'being', 'between', 'could', 'from', 'have', 'into', 'latest', 'local',
    'more', 'news', 'over', 'said', 'says', 'that', 'their', 'there', 'these',
    'they', 'this', 'through', 'today', 'under', 'update', 'updates', 'what',
    'when', 'where', 'which', 'with', 'would', 'will', 'rochdale', 'greater',
    'manchester', 'source', 'report', 'reports', 'reported',
}


def redact_private_location(value: Any) -> str:
    """Remove private addresses without turning every adult name into 'an individual'."""
    text = POSTCODE_RE.sub('the Rochdale area', str(value or ''))
    text = ADDRESS_RE.sub('a location in the Rochdale borough', text)
    return strip_markdown(text)


def compact_source_value(value: Any, limit: int = 2600) -> str:
    text = _plain_text(value)
    if len(text) <= limit:
        return text
    shortened = text[:limit]
    boundary = max(shortened.rfind('. '), shortened.rfind('! '), shortened.rfind('? '))
    if boundary >= int(limit * 0.62):
        shortened = shortened[: boundary + 1]
    return shortened.strip()


def compact_source_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    total = 0
    for record in records[:8]:
        clean = dict(record)
        clean['title'] = compact_source_value(clean.get('title'), 260)
        clean['summary'] = compact_source_value(clean.get('summary'), 1500)
        clean['body_excerpt'] = compact_source_value(clean.get('body_excerpt'), 3200)
        size = len(json.dumps(clean, ensure_ascii=False))
        if compacted and total + size > 14000:
            break
        compacted.append(clean)
        total += size
    return compacted


def draft_quality_issues(draft: Any, source_text: str, candidate: Candidate) -> list[str]:
    if not isinstance(draft, dict):
        return ['The model did not return an article object.']
    if not bool(draft.get('publishable')):
        return ['The draft was marked unpublishable.']

    title = strip_markdown(draft.get('title'))
    excerpt = strip_markdown(draft.get('excerpt'))
    paragraphs = [strip_markdown(item) for item in draft.get('paragraphs', []) if strip_markdown(item)]
    combined = normalise_ws(' '.join([title, excerpt, *paragraphs]))
    issues: list[str] = []

    if len(title.split()) < 5 or len(title) > 155:
        issues.append('The headline must be a complete, specific headline of 5-24 words.')
    first_alpha = next((char for char in title if char.isalpha()), '')
    if first_alpha and first_alpha.islower():
        issues.append('The headline begins like a clipped sentence fragment.')
    if title.endswith((':', '-', '–', '—', ',')):
        issues.append('The headline ends as an incomplete fragment.')
    if len(excerpt.split()) < 22:
        issues.append('The standfirst is too thin to explain the story.')
    if len(paragraphs) < 3:
        issues.append('The article needs at least three factual paragraphs.')
    if any(len(paragraph.split()) < 8 for paragraph in paragraphs):
        issues.append('One or more paragraphs are filler rather than a complete factual sentence.')
    if GENERIC_ARTICLE_RE.search(combined):
        issues.append('The copy discusses the source or publishing process instead of reporting the story.')

    normalised_paragraphs = [normalise_ws(p).casefold() for p in paragraphs]
    if len(normalised_paragraphs) != len(set(normalised_paragraphs)):
        issues.append('The article repeats a paragraph.')

    source_tokens = {
        token for token in re.findall(r'[a-z0-9]+', source_text.lower())
        if len(token) >= 4 and token not in QUALITY_STOPWORDS
    }
    output_tokens = {
        token for token in re.findall(r'[a-z0-9]+', combined.lower())
        if len(token) >= 4 and token not in QUALITY_STOPWORDS
    }
    if len(source_text) >= 120 and len(source_tokens & output_tokens) < 4:
        issues.append('The article is not sufficiently grounded in the supplied facts.')
    if excessive_source_overlap(combined, source_text):
        issues.append('The wording is too close to the source material and must be rewritten more originally.')
    return issues


def request_grounded_draft(
    candidate: Candidate,
    client: OpenAI,
    source_records: list[dict[str, Any]],
    social_context: list[dict[str, Any]],
    source_text: str,
    sensitive: bool,
) -> dict[str, Any] | None:
    system_message = (
        "You are the senior sub-editor for Rochdale Daily, an independent UK local-news publication. "
        "Write a coherent, original local news report using only facts explicitly contained in the supplied records. "
        "The opening paragraph must explain the actual development: who or what is involved, what happened, where it happened and when, whenever those facts are supplied. "
        "Do not write about the source having published an update, the article being categorised, the automated process, the availability of a source link, or facts being added later. "
        "Do not use filler. Do not say that something is connected to Rochdale unless the records themselves establish the geographical connection. "
        "The headline must be a complete, natural headline rather than a copied or clipped source fragment. Do not prefix a town merely because it was used as discovery metadata. "
        "Use neutral UK English, short paragraphs and a clear chronological structure. Explain practical local relevance only when supported by the records. "
        "Never invent a quotation, identity, allegation, motive, date, age, address, statistic, organisation, sentence, charge or outcome. "
        "Attribute allegations and procedural status precisely. Do not imply guilt before conviction. Adult defendants and convicted offenders may be named when the records explicitly name them. "
        "Never identify a sexual-offence complainant or a protected child. Omit exact private residential addresses and postcodes. "
        "Never reproduce ten or more consecutive words from a source. Never mirror the source's sentence order or paragraph structure. "
        "If the supplied records do not contain enough concrete facts for a meaningful article, set publishable to false instead of producing generic copy. "
        "Never publish job adverts, recruitment posts, vacancies or application invitations."
    )

    base_payload = {
        'primary_source': candidate.source_name,
        'primary_url': candidate.source_url,
        'source_published_at': candidate.source_published_at,
        'detected_area': candidate.area,
        'detected_category': candidate.category,
        'searched_location': {
            'slug': candidate.searched_location_slug,
            'name': candidate.searched_location_name,
            'warning': 'Discovery metadata only. It is not evidence that the incident happened there.',
        },
        'sensitive_story': sensitive,
        'source_records': source_records,
        'social_context': social_context,
        'requested_style': (
            'Headline of 5-24 words; standfirst of 35-70 words; 3-7 factual paragraphs. '
            'Lead with the news, not with attribution or publishing metadata. Add background only when supplied. '
            'Crime and court stories must clearly distinguish allegation, charge, conviction and sentence.'
        ),
        'required_right_to_reply': f'Anyone directly affected may request a correction or right of reply by emailing {RIGHT_TO_REPLY_EMAIL}.',
    }

    previous: dict[str, Any] | None = None
    feedback: list[str] = []
    for attempt in range(2):
        payload = dict(base_payload)
        if attempt:
            payload['repair_required'] = feedback
            payload['previous_draft'] = previous
            payload['repair_instruction'] = (
                'Rewrite the article from scratch. Correct every listed problem. Do not merely edit the previous wording.'
            )
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {'role': 'system', 'content': system_message},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={'type': 'json_schema', 'json_schema': ARTICLE_SCHEMA},
                temperature=0.1,
                max_tokens=1800,
            )
            draft = json.loads(response.choices[0].message.content or '{}')
        except Exception as exc:
            log.warning('Grounded rewrite attempt %d failed for %s: %s', attempt + 1, candidate.source_url, exc)
            continue
        feedback = draft_quality_issues(draft, source_text, candidate)
        if not feedback:
            return draft
        previous = draft
        log.warning('Rejected rewrite attempt %d for %s: %s', attempt + 1, candidate.source_url, '; '.join(feedback))
    return None


def article_is_low_quality(article: dict[str, Any]) -> bool:
    route = str(article.get('publication_route') or '').lower()
    if route in {'direct-crime-autopublish', 'automatic-attributed-crime-fallback', 'source-led-fallback'}:
        return True
    text = _plain_text(' '.join(str(article.get(field) or '') for field in ('title', 'excerpt', 'summary', 'content_html')))
    return bool(GENERIC_ARTICLE_RE.search(text))

def rewrite_candidate(candidate: Candidate, client: OpenAI | None) -> dict[str, Any] | None:
    clean_candidate_public_text(candidate)
    if (is_job_or_career_post(candidate) or is_classified_listing_post(candidate)):
        log.info('Rejected careers/vacancy post: %s', candidate.source_url)
        return None
    if candidate.category == 'events':
        log.info("Skipping general event candidate because What's Occurrin' Events is the approved event feed: %s", candidate.source_url)
        return None

    source_records = [{
        'name': candidate.source_name,
        'url': candidate.source_url,
        'title': candidate.source_title,
        'summary': candidate.source_summary,
        'body_excerpt': candidate.source_body_excerpt,
        'published_at': candidate.source_published_at,
        'source_kind': candidate.source_kind,
        'event_start_at': candidate.event_start_at,
        'event_end_at': candidate.event_end_at,
        'event_location': candidate.event_location,
        'discovery_query_label': candidate.discovery_query_label,
        'searched_location_slug': candidate.searched_location_slug,
        'searched_location_name': candidate.searched_location_name,
    }] + candidate.related_sources[:11]
    source_records = enrich_source_records(source_records)
    source_records = compact_source_records(source_records)
    social_context = candidate.social_context[:SOCIAL_MAX_OFFICIAL_UPDATES + SOCIAL_MAX_PUBLIC_REACTIONS]
    source_text = normalise_ws(' '.join(
        f"{item.get('title', '')} {item.get('summary', '')} {item.get('body_excerpt', '')}"
        for item in source_records
    ))[:32000]
    sensitive = is_sensitive(source_text, candidate.category)

    if client is None:
        log.error('OpenAI is unavailable; refusing to publish generic filler for %s', candidate.source_url)
        return None

    draft = request_grounded_draft(
        candidate,
        client,
        source_records,
        social_context,
        source_text,
        sensitive,
    )
    if draft is None:
        log.warning('No coherent grounded rewrite could be produced; skipped: %s', candidate.source_url)
        return None

    title = strip_markdown(draft.get('title'))[:160]
    excerpt = strip_markdown(draft.get('excerpt'))[:360]
    paragraphs = [strip_markdown(item) for item in draft.get('paragraphs', []) if strip_markdown(item)][:8]
    community_reaction = strip_markdown(draft.get('community_reaction', ''))[:500]
    social_context_used = bool(draft.get('social_context_used'))
    draft_category = str(draft.get('category') or '')
    # Categorise the PUBLISHED article only. Raw source_text is excluded:
    # a story found via a traffic search query can arrive wrapped in traffic
    # page furniture, and those words outvoted the finished football
    # report's own vocabulary (live example: "Rochdale to face Swindon Town"
    # labelled traffic).
    category_evidence = normalise_ws(
        f"{title} {excerpt} {' '.join(paragraphs)}"
    )
    category = editorial_category(
        category_evidence,
        draft_category or candidate.category or 'news',
    )
    area = str(draft.get('area') or candidate.area)
    if category not in CATEGORY_STOCK_IMAGES:
        category = 'news'
    if area not in AREA_KEYWORDS:
        area = candidate.area if candidate.area in AREA_KEYWORDS else 'rochdale'

    # The category is now final, so misplaced furniture can be removed
    # deterministically: the Crimestoppers service sentence outside crime
    # reports, and the sympathy line outside reports of a death. The house
    # style forbids both, but the model was adding them anyway, and the
    # word "police" inside the service sentence then dragged whole
    # community stories into the crime category.
    paragraphs = strip_service_furniture(paragraphs, category)

    public_reaction_count = sum(1 for item in candidate.social_context if item.get('kind') == 'public_reaction')
    official_social_count = sum(1 for item in candidate.social_context if item.get('kind') == 'official_update')
    if sensitive:
        # The model is instructed not to identify protected people. The deterministic
        # layer only removes private locations; it no longer destroys legitimate adult
        # defendant/offender names by replacing every person with "an individual".
        title = redact_private_location(title)
        excerpt = redact_private_location(excerpt)
        paragraphs = [redact_private_location(paragraph) for paragraph in paragraphs]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]
        community_reaction = ''
        social_context_used = False
    if public_reaction_count < SOCIAL_MIN_PUBLIC_REACTIONS:
        community_reaction = ''
        if official_social_count == 0:
            social_context_used = False
    if community_reaction:
        community_reaction = redact_private_location(community_reaction)
        paragraphs.append(f'Community reaction: {community_reaction}')

    final_draft = {
        'publishable': True,
        'title': title,
        'excerpt': excerpt,
        'paragraphs': paragraphs,
    }
    final_issues = draft_quality_issues(final_draft, source_text, candidate)
    if final_issues:
        log.warning('Final rewrite failed quality checks for %s: %s', candidate.source_url, '; '.join(final_issues))
        return None

    image_url, image_credit = source_image(candidate, category)
    source_urls = [candidate.source_url] + [item['url'] for item in candidate.related_sources[:11] if item.get('url')]
    source_names = [candidate.source_name] + [item['name'] for item in candidate.related_sources[:11] if item.get('name')]
    legal_disclaimer = strip_markdown(draft.get('legal_disclaimer')) or default_legal_disclaimer(sensitive)
    right_to_reply = strip_markdown(draft.get('right_to_reply')) or f'Anyone directly affected may request a correction or right of reply by emailing {RIGHT_TO_REPLY_EMAIL}.'
    if sensitive:
        legal_disclaimer = redact_private_location(legal_disclaimer)
        right_to_reply = redact_private_location(right_to_reply)

    return {
        'id': stable_id(candidate.source_url),
        'story_key': candidate.story_key or build_story_key(candidate),
        'title': title,
        'slug': make_slug(title),
        'excerpt': excerpt,
        'content_html': ''.join(f'<p>{html.escape(paragraph)}</p>' for paragraph in paragraphs),
        'area': area,
        'category': category,
        'types': [category],
        'published_at': candidate.source_published_at,
        'scraped_at': iso_utc(utc_now()),
        'image_url': image_url,
        'image_credit': image_credit,
        'source_image_candidate_url': '',
        'source_image_reuse_status': '',
        'event_start_at': candidate.event_start_at,
        'event_end_at': candidate.event_end_at,
        'event_location': candidate.event_location,
        'source_kind': candidate.source_kind,
        'source_name': candidate.source_name,
        'source_url': candidate.source_url,
        'source_names': source_names,
        'source_urls': source_urls,
        'source_count': len(source_urls),
        'social_context_used': social_context_used,
        'social_reaction_count': public_reaction_count,
        'official_social_update_count': official_social_count,
        'social_platforms': sorted({str(item.get('platform')) for item in candidate.social_context if item.get('platform')}),
        'social_context_note': 'Public reactions are anonymised, aggregated and not treated as evidence. Raw comments are not stored in the public article feed.' if social_context_used else '',
        'sensitive_story': sensitive,
        'police_matter': category == 'crime',
        'requires_approval': False,
        'legal_disclaimer': legal_disclaimer,
        'right_to_reply': right_to_reply,
        'byline': 'Rochdale Daily Newsdesk',
        'status': 'published',
        'publication_route': 'ai-grounded-rewrite',
        'rewrite_quality_checked': True,
        'editorial_style_version': STYLE_VERSION,
        'style_rewrite_status': 'generated-in-house-style',
        'discovery_query_label': candidate.discovery_query_label,
        'searched_location_slug': candidate.searched_location_slug,
        'searched_location_name': candidate.searched_location_name,
    }

def write_json_atomic(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)

def safe_collect(name: str, collector: Any, collector_counts: dict[str, int], collector_errors: dict[str, str]) -> list[Candidate]:
    try:
        items = collector()
        collector_counts[name] = len(items)
        return items
    except Exception as exc:
        log.exception('Collector failed: %s', name)
        collector_counts[name] = 0
        collector_errors[name] = str(exc)
        return []


# ROCHDALE_EDITORIAL_QUALITY_V2
def categorise(text: str) -> str:
    return editorial_category(text, "news")


def article_public_word_count(article: dict[str, Any]) -> int:
    return editorial_word_count(article)


# Heavy-namesake towns (middleton, wardle, norden, bamford, healey, hopwood)
# are deliberately ABSENT from this finished-text acceptance regex. "In
# Middleton" appears in finished copy about Middleton, Nova Scotia and
# Middleton, Wisconsin precisely because the namesake fooled the earlier
# stages; those names must earn locality through locality_evidence(), where
# the known-publisher rule and the impostor/rival vetoes apply. The names
# kept here have no significant namesakes.
BOROUGH_FINISHED_LOCATION_RE = re.compile(
    r"\b(?:in|at|near|around|across|from|within|throughout|towards|outside|serving|based in|located in)\s+"
    r"(?:the\s+)?(?:heywood|littleborough|milnrow|newhey|"
    r"kirkholt|castleton|spotland|falinge|deeplish|smallbridge|firgrove|shawclough|"
    r"balderstone|darnhill|alkrington|boarshaw|smithy bridge|rochdale)\b|"
    r"\b(?:heywood|littleborough|milnrow|newhey|kirkholt|"
    r"castleton|spotland|falinge|deeplish|smallbridge|firgrove|shawclough|balderstone|"
    r"darnhill|alkrington|boarshaw|smithy bridge)\s+"
    r"(?:town|town centre|area|ward|estate|village|residents|community|road|street|school|"
    r"college|library|station|market|business|businesses|shops|club|services|families)\b",
    re.IGNORECASE,
)


def article_passes_locality(article: dict[str, Any]) -> bool:
    """Final fail-closed locality validation for finished articles.

    Explicit foreign or rival geography always wins over a matching Rochdale
    neighbourhood name, assigned area, search query, or trusted-source flag.
    This prevents namesake stories such as Castleton, Hudson, New York from
    being published as Castleton, Rochdale.
    """
    source_name = normalise_ws(article.get("source_name", ""))
    source_url = str(article.get("source_url") or "")
    source_domain = domain_of(source_url)
    text = " ".join(
        str(article.get(field) or "")
        for field in (
            "title", "excerpt", "summary", "content_html",
            "event_location", "source_title", "source_summary",
            "source_body_excerpt",
        )
    )

    if source_is_denied(source_name, source_url):
        return False

    # This veto must be first. Positive local tokens must never cancel explicit
    # evidence of New York, another US state, another UK town, or other known
    # non-local geography.
    if has_disqualifying_evidence(text, source_name, source_url):
        return False

    if article_is_local(article):
        return True

    trusted_names = {
        str(source.get("name") or "")
        for source in DISCOVERY_PAGES + LIVE_PAGE_SOURCES
        if source.get("trusted_local")
    } | {
        str(page.get("name") or "")
        for page in PUBLIC_FACEBOOK_PAGES
        if page.get("trusted_local")
    }
    trusted_domains = {
        domain_of(str(source.get("url") or ""))
        for source in DISCOVERY_PAGES + LIVE_PAGE_SOURCES
        if source.get("trusted_local")
    }
    if source_name in trusted_names or source_domain in trusted_domains:
        return True

    return bool(
        rochdale_traffic_area(text)
        or BOROUGH_FINISHED_LOCATION_RE.search(normalise_ws(text))
    )


def enrich_source_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return editorial_enrich_records(
        records,
        page_metadata,
        canonicalise_url,
        source_is_denied,
        log,
    )


def compact_source_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return editorial_compact_records(records)


def draft_quality_issues(draft: Any, source_text: str, candidate: Candidate) -> list[str]:
    return editorial_quality_issues(draft, source_text)


def request_grounded_draft(
    candidate: Candidate,
    client: OpenAI,
    source_records: list[dict[str, Any]],
    social_context: list[dict[str, Any]],
    source_text: str,
    sensitive: bool,
) -> dict[str, Any] | None:
    return editorial_request_article(
        client=client,
        model=OPENAI_MODEL,
        schema=ARTICLE_SCHEMA,
        candidate=candidate,
        source_records=source_records,
        social_context=social_context,
        source_text=source_text,
        sensitive=sensitive,
        right_to_reply_email=RIGHT_TO_REPLY_EMAIL,
        logger=log,
    )


def candidate_is_rewrite_eligible(candidate: Candidate, existing_by_story: dict[str, dict[str, Any]]) -> bool:
    """Decide whether a clustered candidate earns one of the run's rewrite slots.

    A story that is already published stays published exactly as it is; it is
    only re-attempted when the house style version changes or when the
    candidate brings a source URL the article has never seen (i.e. genuinely
    new material arrived).

    There is deliberately NO "under 200 words" re-eligibility rule here.
    length_budget() intentionally produces short briefs (as few as 50 body
    words) from thin sources, so a word-count threshold re-queued the same
    correctly-sized briefs for a fresh rewrite on every 15-minute run: each
    rewrite produced a slightly different headline, which changed the slug,
    which orphaned the old article page (median measured page lifespan on the
    live site: 4.3 hours). A short article only genuinely improves when MORE
    source material arrives, and that is exactly the new-source-URL check.
    """
    if (is_job_or_career_post(candidate) or is_classified_listing_post(candidate)):
        return False
    if candidate.category == 'events':
        # rewrite_candidate() unconditionally rejects general event
        # candidates because What's Occurrin' Events is the approved feed,
        # so selecting them only wastes rewrite slots and inflates the skip
        # count. Filter them before selection instead of after.
        return False
    candidate.story_key = candidate.story_key or build_story_key(candidate)
    existing_article = existing_by_story.get(candidate.story_key)
    if existing_article is None:
        return True
    if existing_article.get('editorial_lock'):
        # Hand-edited by the editor: the pipeline never rewrites it.
        return False
    if existing_article.get('editorial_style_version') != STYLE_VERSION:
        return True
    known_urls = {canonicalise_url(url) for url in existing_article.get('source_urls', []) if url}
    primary_url = canonicalise_url(str(existing_article.get('source_url') or ''))
    if primary_url:
        known_urls.add(primary_url)
    candidate_urls = {canonicalise_url(candidate.source_url), *{canonicalise_url(item.get('url', '')) for item in candidate.related_sources if item.get('url')}}
    return bool(candidate_urls - known_urls)

def main() -> int:
    log.info('Starting Rochdale Daily 15-minute pipeline')
    existing = recent_existing_articles()
    existing_by_story = {build_story_key(item): item for item in existing}
    collector_counts: dict[str, int] = {}
    collector_errors: dict[str, str] = {}
    x_social_records = collect_x_social_records()
    facebook_social_records = collect_facebook_social_records()
    batches = {'rss_and_google_news': safe_collect('rss_and_google_news', collect_rss_candidates, collector_counts, collector_errors), 'website_discovery': safe_collect('website_discovery', collect_discovery_candidates, collector_counts, collector_errors), 'aggregator_discovery': safe_collect('aggregator_discovery', collect_aggregator_candidates, collector_counts, collector_errors), 'live_service_pages': safe_collect('live_service_pages', collect_live_page_candidates, collector_counts, collector_errors), 'facebook_events': [], 'facebook_official': safe_collect('facebook_official', collect_facebook_candidates, collector_counts, collector_errors), 'x_official': safe_collect('x_official', collect_x_candidates, collector_counts, collector_errors), 'environment_agency': safe_collect('environment_agency', collect_environment_agency_flood_candidates, collector_counts, collector_errors), 'food_hygiene': safe_collect('food_hygiene', collect_food_hygiene_candidates, collector_counts, collector_errors)}
    raw_candidates_all = [candidate for batch in batches.values() for candidate in batch]
    rejected_job_candidates = [candidate for candidate in raw_candidates_all if (is_job_or_career_post(candidate) or is_classified_listing_post(candidate))]
    raw_candidates = [candidate for candidate in raw_candidates_all if not (is_job_or_career_post(candidate) or is_classified_listing_post(candidate))]
    candidates = deduplicate_and_cross_reference(raw_candidates)
    correlate_social_context(candidates, x_social_records + facebook_social_records)
    log.info('Candidate volume: %d raw items -> %d story clusters', len(raw_candidates), len(candidates))
    api_key = os.getenv('OPENAI_API_KEY')
    run_limit = MAX_AI_ARTICLES_INITIAL if len(existing) < MIN_LIVE_STORIES else MAX_AI_ARTICLES_PER_RUN
    eligible_candidates = [
        candidate for candidate in candidates
        if candidate_is_rewrite_eligible(candidate, existing_by_story)
    ]
    effective_limit = min(len(eligible_candidates), max(run_limit, MIN_BALANCED_SELECTION_LIMIT))
    selected_candidates, selection_diagnostics = balanced_select(eligible_candidates, limit=effective_limit, max_per_source=MAX_SELECTED_PER_SOURCE, max_per_category=MAX_SELECTED_PER_CATEGORY)
    log.info('Balanced selection: %d eligible -> %d selected; categories=%s; wards=%s', len(eligible_candidates), len(selected_candidates), selection_diagnostics.get('selected_categories', []), selection_diagnostics.get('selected_wards', []))
    new_articles: list[dict[str, Any]] = []
    skipped = 0

    def process_candidate(candidate: Candidate) -> dict[str, Any] | None:
        worker_client = OpenAI(api_key=api_key) if api_key else None
        return rewrite_candidate(candidate, worker_client)
    with ThreadPoolExecutor(max_workers=max(1, AI_WORKERS)) as executor:
        future_map = {executor.submit(process_candidate, candidate): candidate for candidate in selected_candidates}
        for future in as_completed(future_map):
            candidate = future_map[future]
            try:
                article = future.result()
                if article:
                    article = sanitise_article(article)
            except Exception as exc:
                log.exception('Rewrite failed for %s: %s', candidate.source_url, exc)
                skipped += 1
                continue
            if article:
                new_articles.append(article)
            else:
                skipped += 1
    ai_count = len(selected_candidates)
    # URL stability: a story that has already been published keeps its slug,
    # id and first-publication date forever, even when the latest rewrite
    # produced a different headline. Headline drift must never change the
    # public URL of an already-indexed article page.
    for article in new_articles:
        prior = existing_by_story.get(str(article.get('story_key') or ''))
        if not prior:
            continue
        for field in ('slug', 'id'):
            if prior.get(field):
                article[field] = prior[field]
        if prior.get('first_published_at'):
            article['first_published_at'] = prior['first_published_at']
    merged: dict[str, dict[str, Any]] = {}
    for article in existing + new_articles:
        article = sanitise_article(article)
        # Trust the stored story key when one exists: recomputing identity
        # from the freshly rewritten headline made the same story oscillate
        # between keys run-to-run, splitting it into duplicates whose merge
        # then dropped one slug (and deleted its page).
        story_key = str(article.get('story_key') or '') or build_story_key(article)
        article['story_key'] = story_key
        if story_key in merged:
            merged[story_key] = merge_article_records(merged[story_key], article)
        else:
            merged[story_key] = article
    publishable_values = []
    for article in merged.values():
        if (is_job_or_career_post(article) or is_classified_listing_post(article)):
            continue
        if source_is_denied(str(article.get('source_name') or ''), str(article.get('source_url') or '')):
            continue
        published_at = parse_datetime(article.get('published_at'))
        source_kind = str(article.get('source_kind') or 'article')
        event_start = parse_datetime(article.get('event_start_at'))
        if not article_passes_locality(article):
            log.warning('Rejected non-local article after rewrite: %s', article.get('title'))
            continue
        # New candidates were already freshness-checked during collection. At
        # this stage existing records are the permanent archive and must not be
        # discarded merely because their publication date is old.
        publishable_values.append(article)
    deduped_publishable = dedupe_article_records(publishable_values)
    short_after_merge = [
        article for article in deduped_publishable
        if str(article.get('source_kind') or 'article') != 'event'
        and article_public_word_count(article) < 200
    ]
    if short_after_merge:
        log.warning(
            'Held back %d article(s) below the 200-word publication floor after merging: %s',
            len(short_after_merge),
            '; '.join(str(article.get('title') or 'Untitled') for article in short_after_merge[:10]),
        )
    publication_ready = [
        article for article in deduped_publishable
        if str(article.get('source_kind') or 'article') == 'event'
        or article_public_word_count(article) >= 50
    ]
    published = sorted(
        publication_ready,
        key=lambda article: parse_datetime(
            article.get('first_published_at')
            or article.get('published_at')
            or article.get('scraped_at')
        ) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    write_json_atomic(OUTPUT_FILE, published)
    source_counts: dict[str, int] = {}
    for candidate in raw_candidates:
        source_counts[candidate.source_name] = source_counts.get(candidate.source_name, 0) + 1
    published_by_category: dict[str, int] = {}
    for article in published:
        category_name = str(article.get('category') or 'news')
        published_by_category[category_name] = published_by_category.get(category_name, 0) + 1
    selected_by_category: dict[str, int] = {}
    for candidate in selected_candidates:
        selected_by_category[candidate.category] = selected_by_category.get(candidate.category, 0) + 1
    write_json_atomic(STATUS_FILE, {'last_run_at': iso_utc(utc_now()), 'raw_candidates_before_job_filter': len(raw_candidates_all), 'job_or_career_posts_rejected': len(rejected_job_candidates), 'raw_candidates': len(raw_candidates), 'candidate_clusters': len(candidates), 'duplicates_merged': max(0, len(raw_candidates) - len(candidates)), 'attempted_rewrites': ai_count, 'new_articles': len(new_articles), 'live_articles': len(published), 'skipped': skipped, 'collector_counts': collector_counts, 'collector_errors': collector_errors, 'source_counts': dict(sorted(source_counts.items(), key=lambda item: item[1], reverse=True)), 'selected_by_category': dict(sorted(selected_by_category.items())), 'published_by_category': dict(sorted(published_by_category.items())), 'openai_enabled': bool(api_key), 'ai_rewrite_required': AI_REWRITE_REQUIRED, 'source_led_fallback_enabled': True, 'crime_auto_publish_enabled': True, 'crime_direct_publish_enabled': True, 'crime_ai_gate_enabled': False, 'crime_review_queue_enabled': False, 'crime_anonymisation_enabled': False, 'crime_source_overlap_guard_enabled': False, 'protected_identity_filter_enabled_for_non_crime': True, 'source_overlap_guard_enabled_for_non_crime': True, 'same_day_only': SAME_DAY_ONLY, 'prohibited_sources': ['rochdaletimes.co.uk', 'rochdaleonline.co.uk'], 'selected_story_keys': [candidate.story_key for candidate in selected_candidates], 'selected_candidate_urls': [candidate.source_url for candidate in selected_candidates], 'x_social_records': len(x_social_records), 'facebook_social_records': len(facebook_social_records), 'stories_with_social_context': sum((1 for candidate in candidates if candidate.social_context)), 'x_enabled': bool(X_BEARER_TOKEN), 'facebook_comments_enabled': bool(FACEBOOK_PAGE_ACCESS_TOKEN and FACEBOOK_COMMENTS_ENABLED), 'locality_rule': 'Single-word locality names require geographical context; person surnames are not accepted as locations.', 'story_identity_rule': 'Stories are clustered by named entities, subject terms, area, category and date; interviews/reactions are merged into the underlying announcement where they describe the same event.', 'selection_policy': 'One story is reserved for each represented category and each represented official ward before source-rotating fill selection.', 'coverage': selection_diagnostics, 'official_ward_count': len(ROCHDALE_WARDS), 'career_and_vacancy_content_banned': True, 'search_query_count': len(SEARCH_QUERY_SPECS), 'search_queries': [{'label': spec.label, 'query': spec.query, 'category': spec.category, 'ward': spec.ward, 'person': spec.person, 'location_slug': spec.location_slug, 'location_name': spec.location_name} for spec in SEARCH_QUERY_SPECS], 'robots_policy': 'Direct fetching is never attempted when robots.txt declines it; RSS, indexed search results and authorised APIs are used instead.', 'robots_denied_count': len(ROBOTS_DENIED_URLS), 'robots_denied_urls': ROBOTS_DENIED_URLS[:100], 'men_rochdale_source': {'enabled': True, 'mode': 'official section RSS', 'section_url': 'https://www.manchestereveningnews.co.uk/all-about/rochdale', 'feed_url': 'https://www.manchestereveningnews.co.uk/all-about/rochdale?service=rss', 'direct_page_crawling': False}})
    log.info('Complete: %d live articles, %d new, %d AI/fallback attempts, %d skipped, %d duplicates merged', len(published), len(new_articles), ai_count, skipped, max(0, len(raw_candidates) - len(candidates)))
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
