#!/usr/bin/env python3
"""Conservative pre-publication source evidence preparation.

Only approved public HTTPS hosts; no redirects, credentials or private IPs.
Local publishers provide attributable source evidence, not primary certification.
Evidence is advisory until claim-level independent review is complete.
"""
from __future__ import annotations
import hashlib
import ipaddress
import re
import socket
from urllib.robotparser import RobotFileParser
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from claim_evidence import approved_evidence_source, is_primary, norm

MAX_BYTES=1_000_000
VERIFIER_USER_AGENT="RochdaleDailyEditorialVerifier/1.0"
_ROBOTS_CACHE={}
def publisher_robots_allows(url, client):
    """Honour publishers' crawl exclusions before capturing their article."""
    host=urlparse(url).hostname
    if host in _ROBOTS_CACHE:
        return _ROBOTS_CACHE[host].can_fetch(VERIFIER_USER_AGENT,url)
    robots_url="https://"+host+"/robots.txt"
    safe_host(robots_url)
    response=client.get(robots_url,timeout=(3,6),allow_redirects=False,
                        headers={"User-Agent":VERIFIER_USER_AGENT,"Accept":"text/plain"})
    if response.status_code==404:
        _ROBOTS_CACHE[host]=RobotFileParser()
        _ROBOTS_CACHE[host].parse([])
        return True
    if response.status_code in (401,403):
        return False
    if response.status_code!=200:
        raise ValueError("Unable to establish publisher robots policy")
    if len(response.content)>100_000:
        raise ValueError("Publisher robots policy exceeds safe limit")
    parser=RobotFileParser()
    parser.parse(response.text.splitlines())
    _ROBOTS_CACHE[host]=parser
    return parser.can_fetch(VERIFIER_USER_AGENT,url)

def safe_host(url):
    p=urlparse(url)
    if not approved_evidence_source(url) or p.port not in (None,443) or p.username or p.password:
        raise ValueError("Unapproved source URL")
    host=p.hostname
    for address in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
        ip=ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Non-public source IP")
    return host

def fetch_source(url, session=None):
    safe_host(url)
    client=session or requests
    if not is_primary(url) and not publisher_robots_allows(url,client):
        raise PermissionError("Publisher robots.txt disallows direct evidence capture")
    response=client.get(url,timeout=(5,12),allow_redirects=False,
                        headers={"User-Agent":VERIFIER_USER_AGENT,"Accept":"text/html"})
    response.raise_for_status()
    if response.is_redirect or 300<=response.status_code<400:
        raise ValueError("Redirected sources require separate validation")
    if "text/html" not in response.headers.get("Content-Type","").lower():
        raise ValueError("Unsupported source format")
    if len(response.content)>MAX_BYTES:
        raise ValueError("Source exceeds size limit")
    soup=BeautifulSoup(response.content,"html.parser")
    for node in soup(["script","style","nav","footer","noscript"]):
        node.decompose()
    text=" ".join(soup.stripped_strings)
    if len(text)<60:
        raise ValueError("Insufficient source text")
    return {"url":url,"source_type":"primary" if is_primary(url) else "publisher","captured_text":text[:25000],
            "captured_at":datetime.now(timezone.utc).isoformat(),
            "sha256":hashlib.sha256(response.content).hexdigest()}

def suggest_claim_support(claim, source):
    """Suggest matching passages for review; never attest semantic accuracy."""
    words={x for x in re.findall(r"[a-z0-9]+",norm(claim)) if len(x)>4}
    text=source["captured_text"]
    sentences=re.split(r"(?<=[.!?])\s+",text)
    ranked=sorted(sentences,key=lambda s:len(words & set(re.findall(r"[a-z0-9]+",norm(s)))),reverse=True)
    return [s for s in ranked[:3] if len(s)>=25]

def prepare(article):
    """Capture source and suggest supporting passages without claiming verification."""
    url=article.get("source_url","")
    evidence=fetch_source(url)
    article=dict(article)
    article["evidence_sources"]=[evidence]
    article["evidence_candidates"]={
        "headline":suggest_claim_support(article.get("title",""),evidence),
        "summary":suggest_claim_support(article.get("excerpt",""),evidence)
    }
    article["primary_source_verified"]=False
    article["source_review_verified"]=False
    return article
