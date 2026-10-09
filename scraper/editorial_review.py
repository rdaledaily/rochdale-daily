#!/usr/bin/env python3
"""Conservative editorial QA flags. Heuristics flag review, not factual truth."""
from __future__ import annotations
import re
from html import unescape
from urllib.parse import urlparse

VAGUE = (
    "local residents have expressed", "sparking debate", "the community is buzzing",
    "has sparked widespread", "in a move that", "in a significant development",
    "many people are saying", "locals have been left", "the event highlights",
)
SENSITIVE = re.compile(r"\b(arrested|charged|convicted|murder|rape|sexual assault|fraud|terroris[mt]|died|death|suicide)\b", re.I)
ATTRIBUTION = re.compile(r"\b(according to|police said|court heard|council said|the (?:NHS|school|force) said|a spokesperson said|in a statement|records show|the report states)\b", re.I)
WORD = re.compile(r"[\w’'-]+", re.U)

def plain(html):
    return unescape(re.sub(r"<[^>]+>", " ", str(html or ""))).strip()

def tokens(s):
    return {w.lower() for w in WORD.findall(str(s or "")) if len(w)>3 and w.lower() not in {"about","after","their","where","there","would","could","should","rochdale","greater","manchester","with","from","that","this","into","over","under","more","says","said","news","local"}}

def review_flags(article):
    """Return advisory flags: never reject or silently change content."""
    if article.get("sponsored"):
        return []  # Advertorials are assessed under a separate advertising standard.
    title=str(article.get("title") or "")
    body=plain(article.get("content_html"))
    if not title or not body: return ["missing headline or body"]
    flags=[]
    lead=" ".join(body.split()[:110])
    meaningful=tokens(title)
    if len(meaningful)>=3 and len(meaningful & tokens(lead))==0:
        flags.append("headline has no distinctive terms in the opening 110 words; check headline/body alignment")
    lower=body.lower()
    matched=[p for p in VAGUE if p in lower]
    if len(matched)>=2:
        flags.append("multiple generic unsupported narrative phrases: "+", ".join(matched[:3]))
    if SENSITIVE.search(title+" "+body) and not ATTRIBUTION.search(body):
        flags.append("sensitive allegation or death reporting lacks an explicit attribution phrase; manually check sources")
    source=str(article.get("source_url") or "").strip()
    if not source and not article.get("manual_article"):
        flags.append("automated article missing original source URL")
    if source and urlparse(source).scheme not in ("http","https"):
        flags.append("source URL is not HTTP(S)")
    return flags
