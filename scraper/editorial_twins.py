"""One story, one page: the editor's version wins.

Why (editor, 10 Nov 2026: "Why have you repeated this story ... remove
duplicates as a rule"): the front page carried two pairs of the same story
side by side. In each pair the editor had published the story first, by hand,
with the right photo, and the automated lane published its own rewrite of a
secondary source 20-45 minutes later:

  * Haider Ali / 'Adam' drug line (editor 13:50) and "Man jailed for over a
    decade ..." (pipeline 14:02, Rochdale place card, written from a
    headline-only source - it said 12 years and invented a quote);
  * the family-gold burglary warning (editor 12:25, police photo) and the
    Yahoo-sourced rewrite (13:07, place card).

Both pairs score under the general match bar (0.64 and 0.66 against 0.72),
which stays where it is. story_identity.editorial_twin() applies the narrower
measured rule; this module applies it where every lane builds the feed
(frontpage_pipeline.main, just before articles.json is written):

  1. the automated twin leaves the feed, so it reaches no front page, section,
     ward page, briefing or Facebook post;
  2. its page (if one was written) is replaced by a 301 to the editor's page,
     so a link already shared lands on the same story, told properly;
  3. its rewrite-ledger entry is marked "editorial_twin", so the same source
     is not rewritten and published again on the next run.

The editor's record is never edited here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from story_identity import (
    canonicalise_url,
    editorial_twin_of,
    headline_entities,
    is_editor_record,
    story_facts,
    syndicated_twin,
)

TWIN_HEADER = "# Editorial twins: pipeline copies of the editor's own story (scraper/editorial_twins.py)"
LEDGER_OUTCOME = "editorial_twin"


def split_editorial_twins(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]]]:
    """Return (kept records, [(twin, editor record)])."""
    editors = [record for record in records if is_editor_record(record)]
    if not editors:
        return _split_syndicated_twins(list(records))
    kept: list[dict[str, Any]] = []
    twins: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for record in records:
        if is_editor_record(record):
            kept.append(record)
            continue
        editor = editorial_twin_of(record, editors)
        if editor is None or not editor.get("slug") or editor.get("slug") == record.get("slug"):
            kept.append(record)
        else:
            twins.append((record, editor))
    kept, syndicated = _split_syndicated_twins(kept)
    return kept, twins + syndicated


def _first_published(record: dict[str, Any]) -> str:
    return str(record.get("first_published_at") or record.get("published_at") or "")


def _split_syndicated_twins(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]]]:
    """One release, one page (story_identity.syndicated_twin).

    The editor's version is kept; with no editor version, the first one
    published is kept, because that is the address already shared and indexed.
    Returns (kept records in their original order, [(twin, kept record)]).
    """
    signature = {
        id(record): (headline_entities(record), story_facts(record)) for record in records
    }
    keepers: list[dict[str, Any]] = [record for record in records if is_editor_record(record)]
    retired: dict[int, dict[str, Any]] = {}
    automated = sorted(
        (record for record in records if not is_editor_record(record)), key=_first_published
    )
    for record in automated:
        entities, facts = signature[id(record)]
        keeper = None
        if entities and facts and record.get("slug"):
            for candidate in keepers:
                other_entities, other_facts = signature[id(candidate)]
                if not (entities & other_entities and facts & other_facts):
                    continue
                if candidate.get("slug") and candidate.get("slug") != record.get("slug") and syndicated_twin(candidate, record):
                    keeper = candidate
                    break
        if keeper is None:
            keepers.append(record)
        else:
            retired[id(record)] = keeper
    kept = [record for record in records if id(record) not in retired]
    twins = [(record, retired[id(record)]) for record in records if id(record) in retired]
    return kept, twins


def _rule_sources(redirects_path: Path) -> set[str]:
    try:
        lines = redirects_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {
        line.split()[0] for line in lines
        if line.strip() and not line.lstrip().startswith("#") and len(line.split()) >= 2
    }


def record_twin_redirect(redirects_path: Path, twin_slug: str, editor_slug: str) -> bool:
    """Append 301s from the twin's URL to the editor's page. An existing rule wins."""
    twin_slug = str(twin_slug or "").strip().lower()
    editor_slug = str(editor_slug or "").strip().lower()
    if not twin_slug or not editor_slug or twin_slug == editor_slug:
        return False
    sources = _rule_sources(redirects_path)
    if f"/articles/{twin_slug}" in sources or f"/articles/{twin_slug}.html" in sources:
        return False
    try:
        existing = redirects_path.read_text(encoding="utf-8")
    except OSError:
        existing = ""
    text = existing if existing.endswith("\n") or not existing else existing + "\n"
    lines: list[str] = []
    if TWIN_HEADER not in existing:
        if text:
            lines.append("")
        lines.append(TWIN_HEADER)
    destination = f"/articles/{editor_slug}"
    lines.append(f"/articles/{twin_slug} {destination} 301")
    lines.append(f"/articles/{twin_slug}.html {destination} 301")
    redirects_path.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")
    return True


def _identity(url: str) -> str:
    return canonicalise_url(str(url or "").strip()).rstrip("/")


def mark_ledger(ledger_path: Path, twins: list[tuple[dict[str, Any], dict[str, Any]]]) -> int:
    """Stop the twin's source material being rewritten again."""
    if not twins:
        return 0
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return 0
    wanted: dict[str, str] = {}
    for twin, editor in twins:
        for url in [twin.get("source_url"), *(twin.get("source_urls") or [])]:
            if url:
                wanted[_identity(str(url))] = str(editor.get("slug") or "")
    marked = 0
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        urls = {_identity(key), *(_identity(u) for u in entry.get("urls") or [])}
        hit = next((wanted[u] for u in urls if u in wanted), None)
        if hit is None or entry.get("outcome") == LEDGER_OUTCOME:
            continue
        entry["outcome"] = LEDGER_OUTCOME
        entry["reason"] = f"covered by the editor's story /articles/{hit}"[:160]
        marked += 1
    if marked:
        ledger_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return marked


def retire_twins(
    twins: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    pages_dir: Path,
    redirects_path: Path,
    ledger_path: Path,
) -> dict[str, Any]:
    redirected = 0
    pages_removed = 0
    for twin, editor in twins:
        twin_slug = str(twin.get("slug") or "")
        if record_twin_redirect(redirects_path, twin_slug, str(editor.get("slug") or "")):
            redirected += 1
        page = pages_dir / f"{twin_slug}.html"
        if twin_slug and page.exists():
            page.unlink()
            pages_removed += 1
    return {
        "twins": [
            {"twin": twin.get("slug"), "editor": editor.get("slug")} for twin, editor in twins
        ],
        "redirects_written": redirected,
        "pages_removed": pages_removed,
        "ledger_entries_marked": mark_ledger(ledger_path, twins),
    }
