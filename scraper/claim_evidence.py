#!/usr/bin/env python3
"""Fail-closed evidence contract for NEW automated reporting.

A source URL alone is not a fact check. A producer must supply a captured
primary-source extract and claim-level pointers to exact text in that extract.
This validates *traceability*, not truth, site authenticity, or contradiction.
No network requests are made at publish time.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse

PRIMARY = (
    "rochdale.gov.uk", "gmp.police.uk", "manchesterfire.gov.uk",
    "gov.uk", "legislation.gov.uk", "judiciary.uk",
    "nhs.uk", "ofsted.gov.uk", "reports.ofsted.gov.uk",
    "tfgm.com", "greatermanchester-ca.gov.uk", "gmca.gov.uk",
    "ons.gov.uk", "parliament.uk", "thegazette.co.uk",
)
def host(url):
    p=urlparse(str(url or ""))
    if p.scheme!="https" or p.username or p.password:
        return ""
    return (p.hostname or "").lower().removeprefix("www.")

def is_primary(url):
    h=host(url)
    return bool(h and any(h==d or h.endswith("."+d) for d in PRIMARY))

def norm(s):
    return re.sub(r"\s+"," ",str(s or "").strip()).casefold()

def evidence_issues(article):
    if article.get("sponsored") or article.get("manual_article"):
        return []
    sources=article.get("evidence_sources")
    claims=article.get("verified_claims")
    problems=[]
    if not isinstance(sources,list) or not sources:
        return ["missing evidence_sources: source URL alone is not proof"]
    evidence={}
    for i,source in enumerate(sources):
        if not isinstance(source,dict): problems.append(f"evidence_sources[{i}] invalid");continue
        url=source.get("url")
        excerpt=source.get("captured_text")
        if not is_primary(url):
            problems.append(f"evidence_sources[{i}] not an allowlisted HTTPS primary source")
        if len(norm(excerpt))<60:
            problems.append(f"evidence_sources[{i}] lacks captured original text (60+ chars)")
        if is_primary(url) and len(norm(excerpt))>=60:
            evidence[url]=norm(excerpt)
    if not isinstance(claims,list) or not claims:
        problems.append("missing verified_claims")
    else:
        for i,claim in enumerate(claims):
            if not isinstance(claim,dict):
                problems.append(f"verified_claims[{i}] invalid");continue
            url=claim.get("source_url")
            quote=norm(claim.get("supporting_excerpt"))
            assertion=norm(claim.get("claim"))
            if not assertion or len(assertion)<12:
                problems.append(f"verified_claims[{i}] lacks substantive claim")
            if url not in evidence or len(quote)<25 or quote not in evidence.get(url,""):
                problems.append(f"verified_claims[{i}] lacks matching source evidence")
    if not article.get("primary_source_verified"):
        problems.append("primary-source verification not explicitly attested")
    return problems
