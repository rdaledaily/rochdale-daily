#!/usr/bin/env python3
"""Turn death notices emailed to news@ into drafts the editor approves.

Only death notices and obituaries are picked up; every other email is left
exactly as email_intake.py filed it.

    python scraper/notice_intake.py draft     # after email intake: open one
                                              # GitHub issue per new notice
    python scraper/notice_intake.py approve   # on an issue comment: publish

1. DRAFT. email_intake.py files each email as inbox/.../message.json. This
   reads the new ones, recognises death notices (looks_like_notice), pulls
   out the name, age, date of death, funeral details and funeral director,
   and opens a GitHub issue labelled "death-notice" holding the draft as a
   JSON block. The message id goes in notices/intake_ledger.json so a notice
   is drafted once. GitHub emails the editor about each new issue.

2. APPROVE. The editor checks the notice with the funeral director or the
   family, corrects the JSON in the issue if needed, and comments
       /approve funeral director        (or /approve family, etc.)
   Only the repository owner, members and collaborators can approve. The
   words after /approve become "verified_with", which generate_notices.py
   requires: no approval, no publication. The notice is written to
   notices/data/<slug>.json, the notice pages are rebuilt, the commit goes
   to main, and the issue is closed with the link. "/reject" closes it.

Notices never become articles (generate_notices.py), so they stay off the
front page, the newsletter and RSS.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("RD_REPO_ROOT", "."))
INBOX = Path("inbox")
LEDGER = Path("notices/intake_ledger.json")
DATA_DIR = Path("notices/data")
LABEL = "death-notice"
REPO = os.environ.get("GITHUB_REPOSITORY", "rdaledaily/rochdale-daily")
APPROVERS = {"OWNER", "MEMBER", "COLLABORATOR"}

SUBJECT_SIGNALS = re.compile(
    r"\b(death notice|funeral notice|obituary|obituaries|notice of death|passed away|in loving memory|rest in peace|r\.?i\.?p\.?)\b",
    re.I)
BODY_SIGNALS = [
    re.compile(p, re.I) for p in (
        r"\bpassed away\b", r"\bdied peacefully\b", r"\bpeacefully\b.{0,40}\b(at home|in hospital|hospice|care home)\b",
        r"\bfuneral (service|will take place|is to take place|arrangements)\b", r"\bcrematorium\b",
        r"\bfamily flowers only\b", r"\bdonations (in lieu|if desired|to|may be)\b", r"\bdearly (loved|beloved)\b",
        r"\bbeloved (wife|husband|mum|mother|dad|father|nan|nana|grandad|grandma|son|daughter|sister|brother)\b",
        r"\bdeath notice\b", r"\bobituary\b",
    )
]
TOWNS = ("Rochdale", "Heywood", "Middleton", "Littleborough", "Milnrow", "Newhey", "Wardle", "Smallbridge",
         "Castleton", "Norden", "Bamford", "Whitworth", "Shawclough", "Kirkholt", "Balderstone", "Spotland",
         "Hopwood", "Alkrington", "Langley", "Darnhill", "Smithy Bridge", "Healey", "Syke", "Falinge", "Deeplish")
FUNERAL_DIRECTORS = (  # (text to look for, name to show) — the firms in the funerals guide
    ("dixons", "Dixons Funeral Service"), ("rochdale funeralcare", "Rochdale Funeralcare"),
    ("cutgate", "Cutgate Funeralcare"), ("kilpatricks", "Kilpatricks Funeralcare"),
    ("middleton funeralcare", "Middleton Funeralcare"), ("spotland bridge", "Spotland Bridge Funeral Directors"),
    ("robert nuttall", "Robert Nuttall Funeral Service"), ("kavanagh", "Kavanagh & Coates Funeral Services"),
    ("heywood funeral service", "Heywood Funeral Service"), ("mitchell funeral", "Mitchell Funeral Services"),
    ("holdens", "Holdens Funeral Service"), ("middleton's funeral", "Middleton's Funeral Services"),
    ("middletons funeral", "Middleton's Funeral Services"), ("wellens", "S Wellens & Sons"),
    ("co-op funeralcare", "Co-op Funeralcare"),
)
MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"), start=1)}
MONTH_RE = "|".join(list(MONTHS) + [m[:3] for m in MONTHS])
SIGN_OFF = re.compile(r"\n\s*(--\s*$|kind regards|best regards|regards,|many thanks|thanks,|sent from my)", re.I | re.M)


# ------------------------------------------------------------- recognise --

def looks_like_notice(subject: str, text: str) -> bool:
    """A death notice: the subject says so, or the body shows two signals."""
    if SUBJECT_SIGNALS.search(subject or ""):
        return True
    return sum(1 for p in BODY_SIGNALS if p.search(text or "")) >= 2


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _year_for(month: int, day: int, today: date) -> int:
    year = today.year
    try:
        if date(year, month, day) > today:
            year -= 1
    except ValueError:
        pass
    return year


def find_date(text: str, today: date) -> str:
    """First date in the text, as YYYY-MM-DD; '' if none is clear."""
    patterns = [
        (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH_RE})[a-z]*\b,?\s*(\d{{4}})?", "dmy"),
        (rf"\b({MONTH_RE})[a-z]*\s+(\d{{1,2}})(?!\d)(?:st|nd|rd|th)?\b,?\s*(\d{{4}})?", "mdy"),
        (r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4}|\d{2})\b", "num"),
    ]
    best: tuple[int, str] | None = None
    for pattern, kind in patterns:
        for m in re.finditer(pattern, text, re.I):
            try:
                if kind == "num":
                    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    y = y + 2000 if y < 100 else y
                elif kind == "dmy":
                    d, mo = int(m.group(1)), MONTHS[[k for k in MONTHS if k.startswith(m.group(2).lower()[:3])][0]]
                    y = int(m.group(3)) if m.group(3) else _year_for(mo, d, today)
                else:
                    mo, d = MONTHS[[k for k in MONTHS if k.startswith(m.group(1).lower()[:3])][0]], int(m.group(2))
                    y = int(m.group(3)) if m.group(3) else _year_for(mo, d, today)
                found = date(y, mo, d)
            except (ValueError, IndexError):
                continue
            if found > today:
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), found.isoformat())
    return best[1] if best else ""


def find_name(subject: str, text: str) -> str:
    cleaned = re.sub(r"^\s*((re|fwd?|fw)\s*:\s*)+", "", subject or "", flags=re.I)
    cleaned = SUBJECT_SIGNALS.sub("", cleaned)
    cleaned = re.sub(r"\b(for|of|notice|death|funeral|the late|late)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"[^A-Za-z' \-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    words = cleaned.split()
    if 2 <= len(words) <= 5 and all(w[0].isupper() for w in words):
        return " ".join(w if not w.isupper() or len(w) < 2 else w.title() for w in words)
    # Newspaper style: "SMITH Jane (née Brown)" or "SMITH, Jane"
    m = re.search(r"^\s*([A-Z][A-Z'\-]{1,})[,\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", text or "", re.M)
    if m:
        return f"{m.group(2)} {m.group(1).title()}"
    return ""


def sentence_with(text: str, pattern: str) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if re.search(pattern, sentence, re.I):
            return sentence.strip()[:400]
    return ""


def find_town(text: str) -> str:
    """Where the person was from: "of Heywood" / "from Heywood" first, else the
    first town named that is not part of a crematorium, cemetery or hospice name."""
    towns = "|".join(re.escape(t) for t in TOWNS)
    m = re.search(rf"\b(?:of|from|late of)\s+(?:[A-Z][a-z]+\s+){{0,3}}?({towns})\b", text or "")
    if m:
        return m.group(1)
    for m in re.finditer(rf"\b({towns})\b(?!\s+(Crematorium|Cemetery|Infirmary|Hospice|Funeral|Funeralcare|Road|Street))", text or ""):
        return m.group(1)
    return ""


def notice_text(text: str) -> str:
    body = text or ""
    cut = SIGN_OFF.search(body)
    if cut and cut.start() > 80:
        body = body[:cut.start()]
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def draft_from_message(record: dict[str, Any], today: date) -> dict[str, Any]:
    subject, text = str(record.get("subject") or ""), str(record.get("text") or "")
    body = notice_text(text)
    name = find_name(subject, text)
    died = find_date(body, today)
    age = re.search(r"\baged\s+(\d{1,3})\b", body, re.I)
    town = find_town(body)
    director = next((shown for needle, shown in FUNERAL_DIRECTORS if needle in body.lower()), "")
    photo = next((a.get("saved_to") for a in record.get("attachments") or [] if a.get("role") == "card-photo"), "")
    kind = "obituary" if re.search(r"\bobituar", subject, re.I) else "death_notice"
    slug_base = slugify(name) or f"notice-{record.get('id', 'unknown')}"
    draft = {
        "slug": f"{slug_base}-{died or today.isoformat()}",
        "kind": kind,
        "name": name,
        "age": int(age.group(1)) if age else None,
        "town": town,
        "died": died,
        "published": "",
        "text": body,
        "funeral": sentence_with(body, r"\b(funeral|service|crematorium|cemetery|church)\b"),
        "funeral_director": director,
        "donations": sentence_with(body, r"\bdonations?\b"),
        "photo": photo or "",
        "verified_with": "",
        "source_message": record.get("id"),
    }
    return {k: v for k, v in draft.items() if v is not None}


def missing_fields(draft: dict[str, Any]) -> list[str]:
    return [label for key, label in (("name", "name"), ("died", "date of death"), ("text", "notice text"))
            if not draft.get(key)]


# ------------------------------------------------------------- GitHub API --

def github(method: str, path: str, body: dict | None = None) -> Any:
    token = os.environ["GITHUB_TOKEN"]
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "rochdale-daily-notice-intake", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


ISSUE_HELP = """A death notice arrived at news@. **Nothing is published yet.**

1. Check it with the funeral director or the family.
2. If anything below is wrong or missing, edit this post (the pencil icon) and correct the JSON.
3. To publish, comment `/approve` followed by who confirmed it, for example `/approve funeral director` or `/approve family`.
4. To turn it down, comment `/reject`.

Once approved it goes on rochdaledaily.co.uk/notices/ only: never the front page, the newsletter or RSS.
"""


def issue_body(draft: dict[str, Any], record: dict[str, Any]) -> str:
    gaps = missing_fields(draft)
    warning = (f"\n> **Still needed before approval:** {', '.join(gaps)}.\n" if gaps else "")
    source = f"\nFrom the email \"{record.get('subject', '')}\" (sender domain: {record.get('sender_domain') or 'unknown'}).\n"
    return ISSUE_HELP + warning + source + "\n```json\n" + json.dumps(draft, ensure_ascii=False, indent=2) + "\n```\n"


# ------------------------------------------------------------------ draft --

def load_ledger(root: Path) -> dict[str, Any]:
    path = root / LEDGER
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def new_notices(root: Path, ledger: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for path in sorted((root / INBOX).glob("*/*/*/message.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        message_id = str(record.get("id") or "")
        if not message_id or message_id in ledger:
            continue
        if looks_like_notice(str(record.get("subject") or ""), str(record.get("text") or "")):
            found.append(record)
    return found


def draft(root: Path = ROOT, today: date | None = None, open_issue=None) -> int:
    today = today or datetime.now(timezone.utc).date()
    open_issue = open_issue or (lambda title, body: github(
        "POST", "/issues", {"title": title, "body": body, "labels": [LABEL]})["html_url"])
    ledger = load_ledger(root)
    notices = new_notices(root, ledger)
    for record in notices:
        d = draft_from_message(record, today)
        title = f"Death notice to check: {d.get('name') or record.get('subject') or 'name not found'}"
        url = open_issue(title, issue_body(d, record))
        ledger[str(record["id"])] = {"drafted": today.isoformat(), "issue": url}
        print(f"drafted {record['id']} -> {url}")
    (root / LEDGER).parent.mkdir(parents=True, exist_ok=True)
    (root / LEDGER).write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(notices)} new death notice(s) drafted")
    return 0


# ---------------------------------------------------------------- approve --

def draft_in_issue(body: str) -> dict[str, Any]:
    m = re.search(r"```json\s*(\{.*?\})\s*```", body or "", re.S)
    if not m:
        raise ValueError("no JSON block in the issue")
    return json.loads(m.group(1))


def approve(event: dict[str, Any], root: Path = ROOT, today: date | None = None) -> tuple[str, str]:
    """Return (outcome, message). outcome: published | rejected | ignored | refused."""
    today = today or datetime.now(timezone.utc).date()
    issue, comment = event.get("issue") or {}, event.get("comment") or {}
    labels = {l.get("name") for l in issue.get("labels") or []}
    words = str(comment.get("body") or "").strip()
    if LABEL not in labels or not words.startswith(("/approve", "/reject")):
        return "ignored", ""
    if comment.get("author_association") not in APPROVERS:
        return "ignored", ""
    if words.startswith("/reject"):
        return "rejected", "Turned down: nothing was published."
    verified = words[len("/approve"):].strip().splitlines()[0].strip() if len(words) > len("/approve") else ""
    if not verified:
        return "refused", "Not published: say who confirmed it, for example `/approve funeral director`."
    try:
        notice = draft_in_issue(issue.get("body") or "")
    except ValueError as error:
        return "refused", f"Not published: {error}."
    notice["verified_with"] = verified
    notice["published"] = today.isoformat()
    notice.pop("source_message", None)
    gaps = missing_fields(notice)
    if gaps:
        return "refused", f"Not published: still needed: {', '.join(gaps)}. Edit the JSON in the post, then approve again."
    notice["slug"] = slugify(notice.get("slug") or f"{notice['name']}-{notice['died']}")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import generate_notices
    path = root / DATA_DIR / f"{notice['slug']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    loaded, problems = generate_notices.load_notices(root / DATA_DIR)
    mine = [p for p in problems if p.startswith(path.name)]
    if mine or not any(n["slug"] == notice["slug"] for n in loaded):
        path.unlink(missing_ok=True)
        return "refused", f"Not published: {'; '.join(mine) or 'the notice did not pass the checks'}."
    return "published", f"https://rochdaledaily.co.uk/notices/{notice['slug']}.html"


def approve_from_event(root: Path = ROOT) -> int:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    outcome, message = approve(event, root)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"outcome={outcome}\n")
            fh.write(f"message<<EOF\n{message}\nEOF\n")
    print(outcome, message)
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "draft":
        raise SystemExit(draft())
    if command == "approve":
        raise SystemExit(approve_from_event())
    raise SystemExit("usage: notice_intake.py draft|approve")
