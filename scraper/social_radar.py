"""Rochdale Daily Social Radar lead processor.

This module does NOT log into Facebook, crawl groups, or publish user posts.
It accepts notification-like records delivered through an authorised transport
(e.g. an email/notification bridge), turns them into structured newsroom leads,
deduplicates repeated chatter, and deliberately keeps unverified claims out of
the publication feed.

Expected input is a JSON array (or object containing ``records``) of mappings
with some of these fields:

    sender, subject, snippet, body, received_at, source_context, source_url

The output is a JSON document with ``leads`` plus diagnostics. Social Radar is
therefore isolated from the canonical scraper: a community post can raise a
lead, but it cannot become a published article without a later verification/
editorial step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

BOROUGH_TERMS = (
    "rochdale", "heywood", "middleton", "littleborough", "milnrow", "newhey",
    "norden", "bamford", "wardle", "castleton", "spotland", "falinge",
    "deeplish", "smallbridge", "firgrove", "kirkholt", "balderstone",
    "healey", "hopwood", "alkrington", "smithy bridge",
)

SYSTEM_NOISE = (
    "you're now a member", "your request to join", "friend suggestion",
    "confirmation code", "confirm your email", "security alert",
    "password", "login alert", "business account", "meta for business",
)

TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("traffic", (
        "crash", "accident", "collision", "road closed", "road closure",
        "traffic", "blocked road", "car overturned", "vehicle overturned",
        "police everywhere", "ambulance", "rtc",
    )),
    ("emergency", (
        "fire", "smoke", "fire engine", "police cordon", "police incident",
        "armed police", "helicopter", "ambulance", "evacuated",
    )),
    ("bins", (
        "bin", "bins", "missed collection", "not collected", "wheelie bin",
        "rubbish", "recycling", "fly tipping", "fly-tipping", "dumped waste",
    )),
    ("utilities", (
        "power cut", "electricity off", "water off", "no water", "burst main",
        "gas leak", "internet down", "outage", "flood", "flooding",
    )),
    ("events", (
        "event", "tonight", "this evening", "live music", "quiz night",
        "family day", "festival", "tickets", "book now", "opening night",
    )),
    ("food", (
        "restaurant", "cafe", "coffee shop", "menu", "two for one", "2 for 1",
        "offer", "deal", "bottomless", "brunch", "takeaway", "new opening",
    )),
    ("community", (
        "lost dog", "lost cat", "found dog", "found cat", "missing dog",
        "missing cat", "does anyone know", "anyone know", "what happened",
        "what's happened", "whats happened",
    )),
)

LEGAL_RISK_TERMS = (
    "thief", "thieves", "stole", "stolen by", "scammer", "scam by",
    "fraudster", "paedophile", "pedophile", "rapist", "assaulted me",
    "attacked me", "drug dealer", "dealer lives", "criminal",
)

URGENT_TERMS = (
    "crash", "collision", "fire", "police cordon", "armed police",
    "road closed", "road closure", "ambulance", "gas leak", "flooding",
    "power cut", "burst main", "missing child",
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _combined(record: dict[str, Any]) -> str:
    return " ".join(
        _clean(record.get(key))
        for key in ("subject", "snippet", "body", "source_context")
        if _clean(record.get(key))
    )


def _looks_facebook(record: dict[str, Any]) -> bool:
    sender = _clean(record.get("sender") or record.get("from")).lower()
    url = _clean(record.get("source_url") or record.get("url")).lower()
    text = _combined(record).lower()
    return (
        "facebookmail.com" in sender
        or "facebook.com" in sender
        or "facebook.com/" in url
        or "facebook group" in text
    )


def _is_system_noise(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in SYSTEM_NOISE)


def _borough_relevant(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in BOROUGH_TERMS)


def _topics(text: str) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    for topic, terms in TOPIC_RULES:
        if any(term in lower for term in terms):
            found.append(topic)
    return found or ["community"]


def _extract_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>()\]\[\"']+", text or "", flags=re.I)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        url = raw.rstrip(".,;:!?")
        if url not in seen:
            seen.add(url)
            cleaned.append(url)
    return cleaned


def _best_source_url(record: dict[str, Any], text: str) -> str:
    explicit = _clean(record.get("source_url") or record.get("url"))
    urls = [explicit] if explicit else []
    urls.extend(_extract_urls(text))
    for url in urls:
        host = urlparse(url).netloc.lower()
        if "facebook.com" in host or "fb.com" in host:
            return url
    return urls[0] if urls else ""


def _fingerprint_text(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on",
        "at", "and", "or", "for", "with", "this", "that", "anyone", "know",
        "does", "what", "whats", "happened", "happening",
    }
    useful = [word for word in words if word not in stop]
    return " ".join(useful[:36])


def _stable_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:18]


@dataclass
class Lead:
    id: str
    received_at: str
    source: str
    source_context: str
    source_url: str
    summary: str
    topics: list[str]
    priority: int
    status: str
    verification_required: bool
    legal_risk: bool
    signals: int
    duplicate_count: int
    corroborating_snippets: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "received_at": self.received_at,
            "source": self.source,
            "source_context": self.source_context,
            "source_url": self.source_url,
            "summary": self.summary,
            "topics": self.topics,
            "priority": self.priority,
            "status": self.status,
            "verification_required": self.verification_required,
            "legal_risk": self.legal_risk,
            "signals": self.signals,
            "duplicate_count": self.duplicate_count,
            "corroborating_snippets": self.corroborating_snippets,
        }


def classify_record(record: dict[str, Any]) -> Lead | None:
    if not isinstance(record, dict):
        return None

    text = _combined(record)
    if not text or _is_system_noise(text):
        return None

    source_context = _clean(
        record.get("source_context")
        or record.get("group_name")
        or record.get("channel")
    )
    locality_text = f"{text} {source_context}"
    if not _borough_relevant(locality_text):
        return None

    topics = _topics(text)
    lower = text.lower()
    legal_risk = any(term in lower for term in LEGAL_RISK_TERMS)
    urgent = any(term in lower for term in URGENT_TERMS)

    priority = 35
    if "traffic" in topics or "emergency" in topics:
        priority += 25
    if "utilities" in topics:
        priority += 15
    if "bins" in topics:
        priority += 10
    if urgent:
        priority += 20
    if legal_risk:
        priority += 5
    priority = min(priority, 100)

    if legal_risk:
        status = "legal_hold"
    elif urgent:
        status = "verify_now"
    elif "events" in topics or "food" in topics:
        status = "event_candidate"
    else:
        status = "review"

    summary = _clean(record.get("snippet") or record.get("body") or record.get("subject"))
    summary = summary[:500]
    source_url = _best_source_url(record, text)
    received_at = _clean(record.get("received_at") or record.get("email_ts"))
    source = "facebook_notification" if _looks_facebook(record) else "community_notification"

    identity = "|".join(
        (
            _fingerprint_text(text),
            source_context.lower(),
            ",".join(topics),
        )
    )
    return Lead(
        id=_stable_id(identity),
        received_at=received_at,
        source=source,
        source_context=source_context,
        source_url=source_url,
        summary=summary,
        topics=topics,
        priority=priority,
        status=status,
        verification_required=True,
        legal_risk=legal_risk,
        signals=1,
        duplicate_count=0,
        corroborating_snippets=[summary] if summary else [],
    )


def _same_lead(a: Lead, b: Lead) -> bool:
    if a.source_url and b.source_url and a.source_url == b.source_url:
        return True
    if not set(a.topics).intersection(b.topics):
        return False
    if a.source_context and b.source_context and a.source_context.lower() != b.source_context.lower():
        return False
    ratio = SequenceMatcher(None, _fingerprint_text(a.summary), _fingerprint_text(b.summary)).ratio()
    return ratio >= 0.72


def deduplicate(leads: Iterable[Lead]) -> list[Lead]:
    clusters: list[Lead] = []
    for lead in leads:
        match = next((existing for existing in clusters if _same_lead(existing, lead)), None)
        if match is None:
            clusters.append(lead)
            continue

        match.signals += 1
        match.duplicate_count += 1
        match.priority = min(100, max(match.priority, lead.priority) + 5)
        match.topics = sorted(set(match.topics).union(lead.topics))
        if lead.summary and lead.summary not in match.corroborating_snippets:
            match.corroborating_snippets.append(lead.summary)
            match.corroborating_snippets = match.corroborating_snippets[:5]
        if not match.source_url and lead.source_url:
            match.source_url = lead.source_url
        if lead.legal_risk:
            match.legal_risk = True
            match.status = "legal_hold"
        elif match.status not in {"legal_hold", "verify_now"} and lead.status == "verify_now":
            match.status = "verify_now"
    return clusters


def process_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    raw = list(records)
    classified = [lead for record in raw if (lead := classify_record(record)) is not None]
    leads = deduplicate(classified)
    leads.sort(key=lambda lead: (lead.priority, lead.signals), reverse=True)

    return {
        "schema_version": 1,
        "publication_policy": "lead_only_never_auto_publish",
        "input_records": len(raw),
        "accepted_signals": len(classified),
        "lead_count": len(leads),
        "discarded_records": len(raw) - len(classified),
        "leads": [lead.as_dict() for lead in leads],
    }


def _load_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        records = payload.get("records")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
        return [payload]
    raise ValueError("Social Radar input must be a JSON object or array")


def main() -> int:
    parser = argparse.ArgumentParser(description="Turn community notifications into newsroom leads.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", default=Path("social_radar_leads.json"), type=Path)
    args = parser.parse_args()

    result = process_records(_load_records(args.input))
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Social Radar: {result['accepted_signals']} signals -> "
        f"{result['lead_count']} leads; {result['discarded_records']} discarded"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
