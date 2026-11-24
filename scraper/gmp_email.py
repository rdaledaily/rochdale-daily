"""GMP press releases emailed to news@ that are marked for immediate release.

Editor's rule (18 Nov 2026): of the emails that reach news@, apart from death
notices, the ones the paper acts on automatically are Greater Manchester
Police press releases that concern the Rochdale borough and say they are for
immediate release. They go into the news pipeline like any other source, so
Rochdale Daily writes its own story and credits GMP (agreed 13 Sep 2026: use
GMP as a source, never republish its words verbatim). Every rewrite,
copyright and legal gate still runs.

Not picked up:
  - anything not sent from a gmp.police.uk address (the From domain that
    email_intake.py recorded); a forwarded release arrives from the
    forwarder's address and is left for the editor;
  - anything embargoed, or that does not say "immediate release";
  - anything older than RELEASE_WINDOW.
A release concerns the borough when it names a borough place or postcode
district (concerns_borough). The general locality test is not used: it
treats Middleton or Heywood as ambiguous (there are Middletons all over the
country), but GMP only polices Greater Manchester, where each of these names
means one place.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SOURCE_NAME = "Greater Manchester Police"
RELEASE_WINDOW = timedelta(days=3)
GMP_DOMAINS = ("gmp.police.uk", "gmp.pnn.police.uk")
# Since at least October 2026 GMP's press office sends its releases through
# Onclusive PR Manager, From gmp@onclusivenews.com. Onclusive mails for many
# organisations, so its domain alone is not enough: the release must also carry
# GMP's own newsroom link or press-office sign-off. These mails are the
# published newsroom item and never say "for immediate release"; an embargo is
# still honoured.
ONCLUSIVE_DOMAINS = ("onclusivenews.com",)
ONCLUSIVE_GMP_MARKER = re.compile(
    r"gmp-newsroom\.prgloo\.com|Issued by GMP Press Office|News from Greater Manchester Police", re.I
)
GMP_NEWSROOM_LINK = re.compile(r"https?://gmp-newsroom\.prgloo\.com/news/[^\s<>\")']+", re.I)
IMMEDIATE = re.compile(r"\bfor\s+immediate\s+release\b|\bimmediate\s+release\b", re.I)
EMBARGO = re.compile(r"\bembargo(ed)?\b|\bnot\s+for\s+publication\s+(until|before)\b", re.I)
GMP_NEWS_LINK = re.compile(r"https?://(?:www\.)?gmp\.police\.uk/news/[^\s<>\")']+", re.I)
GMP_NEWSROOM = "https://www.gmp.police.uk/news/greater-manchester/news/"


BOROUGH_PLACES = (
    "Rochdale", "Heywood", "Middleton", "Littleborough", "Milnrow", "Newhey", "Wardle", "Smallbridge",
    "Castleton", "Norden", "Bamford", "Kirkholt", "Balderstone", "Spotland", "Hopwood", "Alkrington",
    "Langley", "Darnhill", "Smithy Bridge", "Healey", "Falinge", "Deeplish", "Belfield", "Firgrove",
    "Shawclough", "Wardleworth", "Newbold", "Lowerplace", "Thornham", "Boarshaw", "Hollingworth Lake",
    "Calderbrook", "Summit, Littleborough",
)
BOROUGH_POSTCODE = re.compile(r"\b(OL1[0-2]|OL1[56]|M24)\s*\d[A-Z]{2}\b|\b(OL1[0-2]|OL1[56]|M24)\b")
BOROUGH_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in BOROUGH_PLACES) + r")\b")


def concerns_borough(text: str) -> bool:
    return bool(BOROUGH_RE.search(text or "") or BOROUGH_POSTCODE.search(text or ""))


def _domain_in(domain: str, domains: tuple[str, ...]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in domains)


def via_onclusive(record: dict[str, Any]) -> bool:
    domain = str(record.get("sender_domain") or "").lower()
    text = f"{record.get('subject') or ''}\n{record.get('text') or ''}"
    return _domain_in(domain, ONCLUSIVE_DOMAINS) and bool(ONCLUSIVE_GMP_MARKER.search(text))


def from_gmp(record: dict[str, Any]) -> bool:
    domain = str(record.get("sender_domain") or "").lower()
    return _domain_in(domain, GMP_DOMAINS) or via_onclusive(record)


def is_immediate_release(subject: str, text: str) -> bool:
    head = f"{subject}\n{text[:1500]}"
    return bool(IMMEDIATE.search(head)) and not EMBARGO.search(head)


def clean_release_text(text: str) -> str:
    text = IMMEDIATE.sub("", text or "")
    text = re.sub(r"(?im)^\s*(press release|news release)\s*:?\s*$", "", text)
    text = re.sub(r"(?is)\n\s*(notes to editors?|ends\s*$).*", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean_onclusive_text(text: str) -> str:
    """Drop Onclusive's header, image links and the legal/unsubscribe footer."""
    text = re.split(r"(?m)^\s*Contact Information\s*$|Issued by GMP Press Office|^\s*LEGAL NOTICE\s*$", text, maxsplit=1)[0]
    text = re.sub(r"\[Greater Manchester Police News<[^>]*>\]", "", text)
    text = re.sub(r"(?m)^-{5,}\s*$", "", text)
    text = re.sub(r"<https?://[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def find_releases(root: Path, now: datetime) -> list[dict[str, Any]]:
    """Immediate-release GMP emails from inbox/, newest first."""
    releases = []
    for path in sorted((root / "inbox").glob("*/*/*/message.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not from_gmp(record):
            continue
        subject, text = str(record.get("subject") or ""), str(record.get("text") or "")
        onclusive = via_onclusive(record)
        if onclusive:
            if EMBARGO.search(f"{subject}\n{text[:1500]}"):
                continue
        elif not is_immediate_release(subject, text):
            continue
        sent = _parse_time(record.get("date")) or _parse_time(record.get("received_at"))
        if not sent or now - sent > RELEASE_WINDOW or sent > now + timedelta(minutes=30):
            continue
        title = re.sub(r"^\s*((re|fwd?|fw)\s*:\s*)+", "", subject, flags=re.I)
        title = IMMEDIATE.sub("", title).strip(" -:|")
        link = GMP_NEWS_LINK.search(text) or GMP_NEWSROOM_LINK.search(text)
        body = clean_release_text(text)
        if onclusive:
            body = clean_onclusive_text(body)
        releases.append({
            "id": str(record.get("id") or ""),
            "title": title,
            "text": body,
            "sent_at": sent.strftime("%Y-%m-%dT%H:%M:%SZ"),
            # The release's own page on gmp.police.uk if the email links one;
            # otherwise the GMP newsroom, tagged with the email id so each
            # release stays a separate story.
            "source_url": link.group(0).rstrip(".,") if link else f"{GMP_NEWSROOM}?release={record.get('id')}",
        })
    releases.sort(key=lambda r: r["sent_at"], reverse=True)
    return releases
