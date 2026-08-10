#!/usr/bin/env python3
"""Turn readable Rochdale Council meeting documents into sourced news stories
and update each councillor's democracy voting record when a recorded vote is published.

Safety rules:
- only works from documents already discovered in council_documents.json;
- must successfully fetch and extract substantial source text;
- requires explicit decision language for article generation;
- recorded votes are parsed deterministically and matched against council_roster.json;
- ambiguous councillor names are NEVER guessed;
- skips article generation for sources already processed, but vote extraction remains idempotent;
- writes individual manual article files and updates council_votes.json.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from pypdf import PdfReader

from council_votes import build_record, load_roster

ROOT = Path(__file__).resolve().parents[1]
DOC_INDEX = ROOT / "council_documents.json"
STATE = ROOT / "council_story_sources.json"
MANUAL_DIR = ROOT / "manual_articles.d"
VOTES_PATH = ROOT / "council_votes.json"
UA = "RochdaleDaily-council-minutes/1.0 (news@rochdaledaily.co.uk)"
MAX_NEW_STORIES = int(os.getenv("COUNCIL_MAX_NEW_STORIES", "3"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DECISION_RE = re.compile(r"\b(resolved|agreed|approved|decided|recommended|authorised)\b", re.I)
RECORDED_VOTE_RE = re.compile(
    r"\b(recorded vote|voting for (?:the )?(?:motion|recommendation)|"
    r"voting against (?:the )?(?:motion|recommendation)|abstain(?:ed|ing)?)\b",
    re.I,
)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def extract_text(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"}, timeout=30, allow_redirects=True)
    if r.status_code != 200 or len(r.content) < 700:
        return ""
    ctype = (r.headers.get("content-type") or "").lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(r.content))
            text = "\n".join((page.extract_text() or "") for page in reader.pages[:80])
        except Exception:
            return ""
    else:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:70000]


def make_story(client: OpenAI, doc: dict, source_text: str) -> dict | None:
    prompt = f"""You are the local-government reporter for Rochdale Daily.
Write ONE newsworthy article from this Rochdale Borough Council meeting document.
Use ONLY facts contained in SOURCE TEXT. Do not infer missing facts, invent quotations, or claim a proposal was approved unless the source explicitly says so.
Focus on the single strongest decision that materially affects residents: money, housing, regeneration, roads, services, planning, schools, social care, environment, public safety, or governance.
If the source contains no clear newsworthy decision, return {{\"publish\": false}}.

Return strict JSON with these keys only:
publish (boolean), title, excerpt, body, category, area.
category must be one of politics, news, community, business, education, environment, health, traffic, transport.
area should be rochdale unless the source clearly concerns one named township/locality.
body should be 5-10 concise paragraphs separated by blank lines and make clear the decision came from council meeting papers/minutes.

DISCOVERED TITLE: {doc.get('title','')}
SOURCE URL: {doc.get('url','')}
SEARCH SNIPPET: {doc.get('search_snippet','')}

SOURCE TEXT:
{source_text}
"""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(response.choices[0].message.content or "{}")
    except Exception as exc:
        print(f"AI extraction failed for {doc.get('url')}: {exc}")
        return None
    if not data.get("publish"):
        return None
    title = str(data.get("title") or "").strip()
    body = str(data.get("body") or "").strip()
    if len(title) < 12 or len(body) < 500:
        return None
    return data


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:90]


def load_vote_store() -> dict:
    payload = load_json(VOTES_PATH, {})
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("source", "Rochdale Borough Council meeting papers; councillor roster from Open Council Data UK")
    payload.setdefault(
        "coverage_note",
        "Only votes taken by name are listed. Other council votes may be minuted as carried or lost without naming individual councillors."
    )
    payload.setdefault("wards", {})
    return payload


def update_councillor_votes(doc: dict, source_text: str, store: dict, roster) -> int:
    """Append one recorded-vote item to every unambiguously matched councillor.

    This deliberately does nothing for ordinary carried/lost votes where councillors
    are not named. A councillor is only shown as voting for/against/abstaining when
    the source text itself contains a recorded name list.
    """
    if not RECORDED_VOTE_RE.search(source_text):
        return 0

    title = str(doc.get("title") or doc.get("page_title") or "Rochdale Council recorded vote").strip()
    url = str(doc.get("url") or "").strip()
    record = build_record(title, url, source_text, roster)
    if not record.votes:
        return 0

    added = 0
    wards = store.setdefault("wards", {})
    for side, people in record.votes.items():
        for person in people:
            ward = person.get("ward") or ""
            name = person.get("name") or ""
            if not ward or not name:
                continue
            ward_people = wards.setdefault(ward, [])
            target = next((p for p in ward_people if str(p.get("name")) == name), None)
            if target is None:
                target = {
                    "name": name,
                    "party": person.get("party") or "",
                    "ward": ward,
                    "votes": [],
                }
                ward_people.append(target)
            vote_item = {
                "side": side,
                "title": title,
                "url": url,
            }
            existing = target.setdefault("votes", [])
            if not any(v.get("url") == url and v.get("side") == side and v.get("title") == title for v in existing):
                existing.insert(0, vote_item)
                added += 1

    if record.unresolved:
        print(f"Recorded vote contained unresolved councillor names (not attributed): {record.unresolved}")
    return added


def main() -> int:
    docs = load_json(DOC_INDEX, [])
    if not isinstance(docs, list) or not docs:
        print("No council documents indexed yet.")
        return 0

    done = set(load_json(STATE, []))
    api_available = bool(os.getenv("OPENAI_API_KEY"))
    client = OpenAI() if api_available else None
    now = datetime.now(timezone.utc)
    out_dir = MANUAL_DIR / now.strftime("%Y") / now.strftime("%m")
    out_dir.mkdir(parents=True, exist_ok=True)
    published = 0
    vote_store = load_vote_store()
    roster = load_roster()
    vote_entries_added = 0

    docs = sorted(docs, key=lambda d: str(d.get("discovered_at") or ""), reverse=True)
    for doc in docs:
        url = str(doc.get("url") or "").strip()
        if not url:
            continue
        title_blob = f"{doc.get('title','')} {doc.get('search_snippet','')}".lower()
        if not any(word in title_blob for word in ("minute", "decision", "cabinet", "committee", "council", "agenda")):
            continue

        text = extract_text(url)
        if len(text) < 1000:
            continue

        # Democracy profile path: independent of article publication state.
        if roster:
            vote_entries_added += update_councillor_votes(doc, text, vote_store, roster)

        # News article path: source URL is processed only once for editorial story generation.
        if published >= MAX_NEW_STORIES or url in done or not DECISION_RE.search(text):
            continue
        if not api_available or client is None:
            continue

        story = make_story(client, doc, text)
        done.add(url)
        if not story:
            continue

        slug = slugify(story["title"])
        digest = hashlib.sha256(url.encode()).hexdigest()[:10]
        payload = {
            "id": f"council-minutes-{digest}",
            "title": story["title"],
            "slug": slug,
            "category": str(story.get("category") or "politics").lower(),
            "area": str(story.get("area") or "rochdale").lower(),
            "byline": "Rochdale Daily",
            "excerpt": story.get("excerpt") or "",
            "img": "assets/img/cards/council.jpg",
            "image_url": "assets/img/cards/council.jpg",
            "image_credit": "Rochdale Daily",
            "body": story["body"],
            "published_at": now.isoformat(),
            "last_updated_at": now.isoformat(),
            "source_name": "Rochdale Borough Council meeting papers",
            "source_url": url,
            "featured": False,
            "right_to_reply": "Rochdale Borough Council and anyone directly affected may provide clarification, corrections or a right of reply by emailing news@rochdaledaily.co.uk."
        }
        path = out_dir / f"{now.strftime('%Y-%m-%d')}-{slug[:70]}-{digest}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Published council decision story: {story['title']}")
        published += 1

    if vote_entries_added:
        vote_store["generated_at"] = now.isoformat()
        VOTES_PATH.write_text(json.dumps(vote_store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Added {vote_entries_added} councillor recorded-vote entries to democracy profiles.")

    STATE.write_text(json.dumps(sorted(done), indent=2) + "\n", encoding="utf-8")
    print(f"Council minutes publisher created {published} new story/stories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
