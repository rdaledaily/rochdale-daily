#!/usr/bin/env python3
"""Fail-closed evidence contract for NEW automated reporting.

A source URL alone is not a fact check. A producer must supply captured
source material and claim-level pointers to the original text. Official primary
sources and named local news publishers have distinct verification labels.
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

# Publishers may provide sourced material for independent rewrite checks.
# Their reporting must never be mislabelled official primary-source verification.
LOCAL_PUBLISHERS = (
    "rochvalleyradio.com", "rochdaletimes.co.uk", "manchestereveningnews.co.uk",
    "rochdaleonline.co.uk", "rochdaleobserver.co.uk", "theburytimes.co.uk",
    "burytimes.co.uk",
)
def is_local_publisher(url):
    h = host(url)
    return bool(h and any(h == d or h.endswith("." + d) for d in LOCAL_PUBLISHERS))

def approved_evidence_source(url):
    return is_primary(url) or is_local_publisher(url)

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
        if not approved_evidence_source(url):
            problems.append(f"evidence_sources[{i}] not an approved HTTPS source")
        if len(norm(excerpt))<60:
            problems.append(f"evidence_sources[{i}] lacks captured original text (60+ chars)")
        if approved_evidence_source(url) and len(norm(excerpt))>=60:
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
    # A publisher rewrite may be independently cross-checked against its
    # original article; that is attribution, not independent primary evidence.
    if not article.get("source_review_verified"):
        problems.append("independent source/claim review not attested")
    all_primary = all(is_primary(s.get("url")) for s in sources if isinstance(s,dict))
    if all_primary and not article.get("primary_source_verified"):
        problems.append("primary-source verification not explicitly attested")
    if not all_primary and article.get("primary_source_verified"):
        problems.append("publisher source incorrectly labelled as primary verified")
    return problems
