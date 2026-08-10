#!/usr/bin/env python3
"""Turn readable Rochdale Council meeting documents into sourced news stories.

Safety rules:
- only works from documents already discovered in council_documents.json;
- must successfully fetch and extract substantial source text;
- requires explicit decision language (resolved/agreed/approved/decided);
- asks OpenAI to use only the supplied document text and return strict JSON;
- skips anything already published from the same source URL;
- writes individual manual article files, preserving the permanent archive model.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DOC_INDEX = ROOT / "council_documents.json"
STATE = ROOT / "council_story_sources.json"
MANUAL_DIR = ROOT / "manual_articles.d"
UA = "RochdaleDaily-council-minutes/1.0 (news@rochdaledaily.co.uk)"
MAX_NEW_STORIES = int(os.getenv("COUNCIL_MAX_NEW_STORIES", "3"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DECISION_RE = re.compile(r"\b(resolved|agreed|approved|decided|recommended|authorised)\b", re.I)


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


def main() -> int:
    docs = load_json(DOC_INDEX, [])
    if not isinstance(docs, list) or not docs:
        print("No council documents indexed yet.")
        return 0
    done = set(load_json(STATE, []))
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY unavailable; discovery retained but no stories generated.")
        return 0
    client = OpenAI()
    now = datetime.now(timezone.utc)
    out_dir = MANUAL_DIR / now.strftime("%Y") / now.strftime("%m")
    out_dir.mkdir(parents=True, exist_ok=True)
    published = 0

    # Prefer records that search engines describe as minutes/decisions and that
    # have not already generated a story.
    docs = sorted(docs, key=lambda d: str(d.get("discovered_at") or ""), reverse=True)
    for doc in docs:
        if published >= MAX_NEW_STORIES:
            break
        url = str(doc.get("url") or "").strip()
        if not url or url in done:
            continue
        title_blob = f"{doc.get('title','')} {doc.get('search_snippet','')}".lower()
        if not any(word in title_blob for word in ("minute", "decision", "cabinet", "committee", "council", "agenda")):
            continue
        text = extract_text(url)
        if len(text) < 1500 or not DECISION_RE.search(text):
            continue
        story = make_story(client, doc, text)
        # Mark a readable but non-newsworthy source as processed as well, to avoid
        # paying to reassess it every six hours.
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

    STATE.write_text(json.dumps(sorted(done), indent=2) + "\n", encoding="utf-8")
    print(f"Council minutes publisher created {published} new story/stories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
