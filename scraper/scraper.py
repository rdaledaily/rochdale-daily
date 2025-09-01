import os
import re
import json
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
from openai import OpenAI

# Load OpenAI key from GitHub secrets
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Facebook groups to scrape
GROUPS = {
    "heywood": "https://www.facebook.com/groups/heywoodcommunity/",
    "rochdale": "https://www.facebook.com/groups/2321259874849245/",
    "littleborough": "https://www.facebook.com/groups/779196125547484/",
    "kirkholt": "https://www.facebook.com/groups/230300881463167/",
    "norden": "https://www.facebook.com/groups/419623505980244/",
    "whitworth": "https://www.facebook.com/groups/76137500365/"
}

# Category keywords
CATEGORIES = {
    "crime": ["arrest", "burglary", "police", "theft", "crime"],
    "politics": ["council", "election", "MP", "vote", "government"],
    "education": ["school", "college", "exam", "teacher", "university"],
    "sport": ["football", "match", "league", "team", "]()
