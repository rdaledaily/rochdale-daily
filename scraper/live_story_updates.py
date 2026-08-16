"""Keep developing coverage on one URL, but only refresh it for real changes.

A source being re-fetched is not itself a news development.  This module keeps a
small source snapshot ledger for active LIVE stories and only creates a fresh
``live_refresh`` candidate when the authoritative page has materially changed.
The accepted development is then rendered as a timestamped update on the
existing canonical article.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import story_identity

_ORIGINAL = story_identity.merge_article_records
_INSTALLED = False
ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "live_source_state.json"
_AUTHORITATIVE_DOMAINS = {
    "gmp.police.uk",
    "rochdale.gov.uk",
    "manchesterfire.gov.uk",
    "greatermanchester-ca.gov.uk",
    "gmca.gov.uk",
    "tfgm.com",
    "news.tfgm.com",
    "nationalhighways.co.uk",
    "northerncarealliance.nhs.uk",
    "penninecare.nhs.uk",
}
_MATERIAL_RE = re.compile(
    r"\b(?:named|identified|identity|victim|family|tribute|post[- ]mortem|"
    r"cause of death|arrested|charged|bailed|released|remanded|custody|"
    r"murder|manslaughter|fatal|court|hearing|convicted|sentenced|appeal|"
    r"witness|found|missing|located|reopened|closed|closure|cancelled|"
    r"canceled|delayed|suspended|resumed|restored|repaired|evacuated|"
    r"warning|alert|flood|fire|collision|crash|roadworks|works|diversion)\b",
    re.I,
)
_NAME_RE = re.compile(r"\b[A-Z][a-z'’-]{2,}\s+[A-Z][a-z'’-]{2,}\b")
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]{2,}")
_NUMBER_RE = re.compile(r"\b(?:\d{1,2}[:.]\d{2}|\d{1,2}\s+[A-Z][a-z]+|\d{2,})\b")
_STOPWORDS = {
    "about", "after", "again", "also", "been", "being", "between", "could",
    "from", "have", "into", "more", "over", "rochdale", "said", "that",
    "their", "there", "these", "they", "this", "through", "until", "with",
    "would", "your", "www", "https",
}
_PENDING_STATE: dict[str, dict[str, Any]] = {}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return f"{parsed.scheme or 'https'}://{host}{path}"


def _authoritative_url(value: str) -> bool:
    host = (urlparse(str(value or "")).hostname or "").lower().removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in _AUTHORITATIVE_DOMAINS)


def _time(item: dict[str, Any]) -> str:
    for key in (
        "verified_development_at",
        "source_published_at",
        "last_updated_at",
        "scraped_at",
        "published_at",
    ):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return _iso_now()


def _text(item: dict[str, Any]) -> str:
    value = str(item.get("excerpt") or item.get("summary") or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()[:900]


def _updates(item: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    existing = item.get("live_updates")
    if isinstance(existing, list):
        for row in existing:
            if isinstance(row, dict) and row.get("timestamp") and row.get("text"):
                out.append({"timestamp": str(row["timestamp"]), "text": str(row["text"])})
    text = _text(item)
    if text:
        out.append({"timestamp": _time(item), "text": text})
    return out


def _is_developing(item: dict[str, Any]) -> bool:
    kind = str(item.get("source_kind") or "").lower()
    return bool(
        item.get("live_story")
        or item.get("breaking_news")
        or kind in {"live", "live_refresh"}
    )


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = _ORIGINAL(left, right)
    if not (_is_developing(left) or _is_developing(right)):
        return merged

    seen: set[str] = set()
    updates: list[dict[str, str]] = []
    for row in _updates(left) + _updates(right):
        key = re.sub(r"\W+", " ", row["text"].lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        updates.append(row)
    updates.sort(key=lambda row: row["timestamp"], reverse=True)

    merged["live_story"] = True
    merged["live_label"] = "LIVE"
    merged["is_ongoing"] = True
    merged["ongoing_label"] = "LIVE"
    if str(merged.get("category") or "").lower() == "crime" or left.get("breaking_news") or right.get("breaking_news"):
        merged["breaking_news"] = True
        merged["breaking_label"] = "BREAKING NEWS"
    merged["live_updates"] = updates[:30]
    merged["update_count"] = max(int(merged.get("update_count") or 1), len(updates))
    if updates:
        merged["last_updated_at"] = updates[0]["timestamp"]
    return merged


def _load_state() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_state(state: dict[str, dict[str, Any]]) -> None:
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(STATE_FILE)


def _snapshot(meta: dict[str, Any]) -> tuple[str, str, str]:
    title = re.sub(r"\s+", " ", str(meta.get("title") or "")).strip()
    description = re.sub(r"\s+", " ", str(meta.get("description") or "")).strip()
    body = re.sub(r"\s+", " ", str(meta.get("body_excerpt") or "")).strip()
    text = " ".join(part for part in (title, description, body) if part)[:12000]
    return title, description, text


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.casefold().encode("utf-8")).hexdigest()


def _words(text: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _WORD_RE.finditer(text)
        if match.group(0).casefold() not in _STOPWORDS
    }


def materially_changed(previous: str, current: str, previous_title: str = "", current_title: str = "") -> bool:
    """Return True only for a substantive source change, not a routine re-render."""
    previous = re.sub(r"\s+", " ", str(previous or "")).strip()
    current = re.sub(r"\s+", " ", str(current or "")).strip()
    if not previous or not current or previous.casefold() == current.casefold():
        return False

    previous_words = _words(previous)
    current_words = _words(current)
    novel_words = current_words - previous_words

    old_names = {value.casefold() for value in _NAME_RE.findall(previous)}
    new_names = {value.casefold() for value in _NAME_RE.findall(current)} - old_names
    old_material = {value.casefold() for value in _MATERIAL_RE.findall(previous)}
    new_material = {value.casefold() for value in _MATERIAL_RE.findall(current)} - old_material
    old_numbers = {value.casefold() for value in _NUMBER_RE.findall(previous)}
    new_numbers = {value.casefold() for value in _NUMBER_RE.findall(current)} - old_numbers

    if new_names or new_material:
        return True

    title_ratio = SequenceMatcher(None, previous_title.casefold(), current_title.casefold()).ratio() if previous_title and current_title else 1.0
    if title_ratio < 0.88 and len(_words(current_title) - _words(previous_title)) >= 2:
        return True

    ratio = SequenceMatcher(None, previous.casefold(), current.casefold()).ratio()
    if new_numbers and len(novel_words) >= 5 and ratio < 0.97:
        return True
    if len(novel_words) >= 10 and (ratio < 0.95 or abs(len(current) - len(previous)) >= 100):
        return True
    if ratio < 0.90 and min(len(previous), len(current)) >= 180 and len(novel_words) >= 6:
        return True
    return False


def _state_entry(title: str, snapshot: str, *, development_at: str = "", requires_publication: bool = False) -> dict[str, Any]:
    return {
        "fingerprint": _fingerprint(snapshot),
        "title": title,
        "snapshot": snapshot,
        "last_material_change_at": development_at,
        "requires_publication": requires_publication,
    }


def _live_source_candidates(core) -> list[Any]:
    """Revisit explicit LIVE sources and emit candidates only for material changes."""
    global _PENDING_STATE
    _PENDING_STATE = {}
    try:
        if not core.OUTPUT_FILE.exists():
            return []
        articles = json.loads(core.OUTPUT_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        core.log.warning("LIVE source refresh could not read articles.json: %s", exc)
        return []

    state = _load_state()
    candidates: list[Any] = []
    seen_urls: set[str] = set()
    for article in articles:
        if not isinstance(article, dict) or not _is_developing(article):
            continue
        source_url = str(article.get("source_url") or "").strip()
        key = _canonical(source_url)
        if not key or key in seen_urls or not _authoritative_url(source_url):
            continue
        seen_urls.add(key)

        try:
            meta = core.page_metadata(source_url)
        except Exception as exc:
            core.log.info("LIVE source refresh failed for %s: %s", source_url, exc)
            continue

        title, description, snapshot = _snapshot(meta)
        if not title or len(snapshot) < 80:
            continue

        previous = state.get(key) if isinstance(state.get(key), dict) else None
        if previous is None:
            _PENDING_STATE[key] = _state_entry(title, snapshot)
            core.log.info("LIVE source baseline recorded without republishing: %s", source_url)
            continue

        if previous.get("fingerprint") == _fingerprint(snapshot):
            continue

        if not materially_changed(
            str(previous.get("snapshot") or ""),
            snapshot,
            str(previous.get("title") or ""),
            title,
        ):
            _PENDING_STATE[key] = _state_entry(title, snapshot)
            core.log.info("LIVE source changed cosmetically; freshness not renewed: %s", source_url)
            continue

        development_at = _iso_now()
        candidate = core.Candidate(
            source_name=str(article.get("source_name") or "Official source"),
            source_url=str(meta.get("url") or source_url),
            source_title=title,
            source_summary=description or snapshot[:900],
            source_published_at=development_at,
            area=str(article.get("area") or "rochdale"),
            category=str(article.get("category") or "news"),
            image_candidate_url=str(meta.get("image") or ""),
            source_body_excerpt=str(meta.get("body_excerpt") or ""),
            source_kind="live_refresh",
        )
        # Candidate is a normal dataclass (not slotted), so these internal flags
        # are safe and remain out of the public article schema.  The eligibility
        # wrapper below requires this proof before allowing a live_refresh.
        candidate.material_update_verified = True
        candidate.verified_development_at = development_at
        candidates.append(candidate)
        _PENDING_STATE[key] = _state_entry(
            title,
            snapshot,
            development_at=development_at,
            requires_publication=True,
        )
        core.log.info("Verified material LIVE development detected: %s", source_url)
    return candidates


def _article_has_published_development(article: dict[str, Any], key: str, development_at: str) -> bool:
    urls = [article.get("source_url"), *(article.get("source_urls") or [])]
    if key not in {_canonical(value) for value in urls if value}:
        return False
    target = _parse(development_at)
    if target is None:
        return False
    timestamps = [
        article.get("last_updated_at"),
        article.get("published_at"),
        article.get("scraped_at"),
    ]
    for value in timestamps:
        parsed = _parse(value)
        if parsed is not None and parsed >= target - timedelta(minutes=5):
            return True
    for row in article.get("live_updates") or []:
        if not isinstance(row, dict):
            continue
        parsed = _parse(row.get("timestamp"))
        if parsed is not None and parsed >= target - timedelta(minutes=5):
            return True
    return False


def _commit_pending_state(core) -> None:
    if not _PENDING_STATE:
        return
    state = _load_state()
    try:
        published = json.loads(core.OUTPUT_FILE.read_text(encoding="utf-8"))
    except Exception:
        published = []

    changed = False
    for key, entry in _PENDING_STATE.items():
        requires_publication = bool(entry.get("requires_publication"))
        if requires_publication:
            stamp = str(entry.get("last_material_change_at") or "")
            if not any(
                isinstance(article, dict)
                and _article_has_published_development(article, key, stamp)
                for article in published
            ):
                # The rewrite may have failed its quality gate.  Keep the old
                # baseline so the same real development is retried next run.
                continue
        stored = dict(entry)
        stored.pop("requires_publication", None)
        if state.get(key) != stored:
            state[key] = stored
            changed = True
    if changed:
        _save_state(state)


def _normalise_status(core) -> None:
    """Keep diagnostics aligned with the actual discovery/source policy."""
    try:
        status = json.loads(core.STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(status, dict):
        return
    status["prohibited_sources"] = sorted(str(value) for value in core.SOURCE_DENY_DOMAINS)
    status["developing_story_refresh_rule"] = (
        "A developing story only renews freshness after a material change on its "
        "authoritative source; routine re-checks do not change publication freshness."
    )
    temp = core.STATUS_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(core.STATUS_FILE)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    story_identity.merge_article_records = _merge

    import scraper as core
    from render_live_updates import main as render_live_updates

    # The newsroom wrapper has already installed its general eligibility gate by
    # the time this function is called.  Add one final fail-closed rule: no code
    # path may publish a synthetic live_refresh unless this module verified a
    # material source change first.
    original_eligibility = core.candidate_is_rewrite_eligible

    def verified_live_eligibility(candidate, existing_by_story):
        if str(getattr(candidate, "source_kind", "") or "").lower() == "live_refresh":
            if not bool(getattr(candidate, "material_update_verified", False)):
                core.log.info(
                    "Rejected unverified live refresh; re-checking a page is not a development: %s",
                    getattr(candidate, "source_url", ""),
                )
                return False
        return original_eligibility(candidate, existing_by_story)

    core.candidate_is_rewrite_eligible = verified_live_eligibility

    original_collect_discovery = core.collect_discovery_candidates

    def collect_discovery_with_live_refresh():
        candidates = list(original_collect_discovery())
        existing_urls = {str(getattr(item, "source_url", "") or "") for item in candidates}
        for item in _live_source_candidates(core):
            if str(getattr(item, "source_url", "") or "") not in existing_urls:
                candidates.append(item)
        return candidates

    core.collect_discovery_candidates = collect_discovery_with_live_refresh

    original_main = core.main

    def main_with_live_updates():
        result = original_main()
        if result == 0:
            render_live_updates()
            _commit_pending_state(core)
            _normalise_status(core)
        return result

    core.main = main_with_live_updates
    _INSTALLED = True
