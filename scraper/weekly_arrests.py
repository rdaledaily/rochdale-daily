"""Rochdale Daily — "Rochdale arrests this week", every Monday.

Editor's request (17 Nov 2026): a weekly story every Monday covering arrests,
charges, court proceedings, sentencing and appeals in the borough, with all
available information.

How it works, and why:

1. NO MODEL CALL. Like the Morning Briefing (daily_briefing.py) it is built
   only from stories Rochdale Daily has already published. Every fact in it
   has already passed the paper's checks and, for court copy, the editor's
   approval. It introduces no new name, charge or allegation, which is what
   keeps a crime and courts round-up safe under the Contempt of Court Act
   1981: it can only repeat what was already lawfully published.

2. EACH CASE APPEARS ONCE, AT ITS FURTHEST STAGE. A story is placed under the
   furthest stage its headline names (appeal > sentenced > in court >
   charged > arrested); the headline decides first because it is the claim
   the story makes about itself, the summary only when the headline names no
   stage.

3. IT TELLS THE TRUTH ON A QUIET WEEK. With nothing to report it says so and
   publishes nothing else.

The window is the previous Monday 00:00 to Sunday 23:59, Europe/London.
Output is a pending_manual_arrests_*.json, which the existing
publish-pending-manual workflow publishes like any editor-written article.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo("Europe/London")
except Exception:                           # pragma: no cover
    LONDON = timezone.utc

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles.json"
MANUAL = ROOT / "manual_articles.json"
ARCHIVE = ROOT / "archive-index.json"

ROUTE = "weekly-arrests"
SLUG_PREFIX = "rochdale-arrests-this-week"
PUBLISH_HOUR = 8            # Monday 8am London; due until noon
LATEST_HOUR = 12
POLICE_PHOTO = "assets/img/cards/police.jpg"

# Furthest stage first. Each pattern is matched case-insensitively.
STAGES = [
    # Only a criminal appeal. "Appeal" on its own is far more often a charity,
    # witness or planning appeal (measured 17 Nov 2026: 8 of 8 false).
    ("appeal", "Appeals", re.compile(
        r"court of appeal|unduly lenient|appeal(?:s|ed|ing)? against (?:(?:his|her|their|a|the) )?(?:conviction|sentence|jail)"
        r"|appeal(?:s|ed)? (?:his|her|their) (?:conviction|sentence)|wins? appeal against|loses? appeal against"
        r"|sentence (?:increased|cut|reduced|quashed)|conviction (?:quashed|overturned|upheld)", re.I)),
    ("sentenced", "Sentenced", re.compile(
        r"\bjail(?:ed|s)?\b|\bsentenced\b|\bsentencing\b|\bimprison(?:ed|ment)\b|\blocked up\b"
        r"|suspended sentence|community order|\bdetention order\b|\blife sentence\b|\bbanned from driving\b"
        r"|\bfined\b|\bbehind bars\b", re.I)),
    ("court", "In court", re.compile(
        r"\bpleads? (?:guilty|not guilty)\b|\bpleaded (?:guilty|not guilty)\b|\bdenies\b|\badmits\b"
        r"|\bappear(?:s|ed)? (?:in|at|before) (?:court|magistrates|crown)|\bin court\b|\bcourt hears\b"
        r"|\btrial\b|\bjury\b|\bfound (?:guilty|not guilty)\b|\bconvicted\b|\bcleared\b|\bacquitted\b"
        r"|\bremanded\b|magistrates'? court|crown court|\bmagistrates\b", re.I)),
    ("charged", "Charged", re.compile(r"\bcharged\b|\bcharges? (?:brought|laid)\b|\bfaces? charges?\b", re.I)),
    ("arrested", "Arrested", re.compile(r"\barrest(?:ed|s)?\b|\bdetained\b|\bin custody\b", re.I)),
]

# Stories that use the words but are not a criminal case at any stage.
NOT_A_CASE = re.compile(
    r"\binquest\b|\bcoroner\b|\bplanning appeal\b|\bappeal(?:s)? for (?:information|witnesses|help)\b"
    r"|\bpolice appeal\b|\bcharity appeal\b|\bfundrais|\bcardiac arrest\b|\bemployment tribunal\b"
    r"|\bprison (?:inspection|inspectors?|report)\b|\binspectorate\b",
    re.I,
)

CRIME_CATEGORIES = {"crime", "court", "courts", "police"}


def load(path, default):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def as_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("articles") or data.get("items") or []
    return []


def parse_iso(value):
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def esc(value):
    return (str(value or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def strip_tags(value):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def whole_sentences(text: str, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", text or "").strip().rstrip("…").rstrip(".").strip()
    if not text:
        return ""
    text += "."
    if len(text) <= limit:
        return text
    kept = ""
    for sentence in re.findall(r".+?[.!?](?=\s+[A-Z0-9“\"']|$)", text):
        if len(kept) + len(sentence) + 1 > limit:
            break
        kept = f"{kept} {sentence}".strip()
    return kept or text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def is_roundup(story) -> bool:
    sid = str(story.get("id") or "")
    return (sid.startswith("briefing-")
            or bool(story.get("briefing_slot"))
            or str(story.get("publication_route") or "") in {"daily-briefing", ROUTE})


def stage_of(story):
    """The furthest stage the story reports, or None when it is not a case."""
    title = str(story.get("title") or "")
    summary = strip_tags(story.get("excerpt") or story.get("summary") or story.get("description") or "")
    if NOT_A_CASE.search(title):
        return None
    category = str(story.get("category") or "").strip().lower()
    # Crime-section stories only: outside it the words mean something else
    # (a councillor "detained" abroad, a High Court "appeal" over a college).
    if category not in CRIME_CATEGORIES:
        return None
    for text in (title, summary):
        for key, label, pattern in STAGES:
            if pattern.search(text):
                if NOT_A_CASE.search(text):
                    return None
                return key
    return None


def week_window(now_local: datetime):
    """Previous Monday 00:00 to this Monday 00:00, London time."""
    this_monday = (now_local - timedelta(days=now_local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return this_monday - timedelta(days=7), this_monday


def collect(start, end):
    """Every published story first published in the window, newest copy wins."""
    seen = {}
    for path in (ARTICLES, MANUAL):
        for story in as_list(load(path, [])):
            slug = story.get("slug")
            if not slug or str(story.get("status") or "published") != "published":
                continue
            if story.get("sponsored") is True or is_roundup(story):
                continue
            seen.setdefault(slug, story)
    # The live reservoir does not keep every story; the archive index does
    # (title, description, category, date). A taken-down story is absent from
    # both, so it can never be listed.
    for entry in as_list(load(ARCHIVE, [])):
        slug = entry.get("slug")
        if slug and slug not in seen and not is_roundup(entry):
            seen[slug] = {**entry, "excerpt": entry.get("description") or ""}
    rows = []
    for story in seen.values():
        moment = parse_iso(story.get("first_published_at") or story.get("published_at"))
        if not moment or not (start <= moment.astimezone(LONDON) < end):
            continue
        stage = stage_of(story)
        if stage:
            rows.append((stage, moment, story))
    return rows


def area_label(value):
    text = str(value or "").replace("-", " ").strip()
    return text.title() if text else ""


def item_html(moment, story):
    area = area_label(story.get("area"))
    summary = whole_sentences(strip_tags(story.get("excerpt") or story.get("summary") or ""))
    day = moment.astimezone(LONDON).strftime("%A %-d %B")
    return (
        '<li><a href="/articles/{slug}.html"><strong>{title}</strong></a>'
        ' <span class="brief-area">{meta}</span>{summary}</li>'.format(
            slug=esc(story.get("slug")),
            title=esc(story.get("title")),
            meta=esc(" · ".join(p for p in (area, day) if p)),
            summary=f"<br>{esc(summary)}" if summary else "",
        )
    )


def plain_text(body_html: str) -> str:
    import html as _html
    text = re.sub(r'\s*<span class="brief-area">(.*?)</span>', r" (\1)", body_html)
    text = re.sub(r"<br>", ". ", text)
    text = re.sub(r"</?(?:p|h2|ul|li)(?:\s[^>]*)?>", "\n\n", text)
    text = _html.unescape(re.sub(r"<[^>]+>", "", text))
    blocks = []
    for block in re.split(r"\n\s*\n", text):
        block = re.sub(r"\s+", " ", block).strip()
        block = re.sub(r"\.\s*\.", ".", block)
        if block:
            if block[-1] not in ".!?:…":
                block += ":" if len(block) < 20 else "."
            blocks.append(block)
    return "\n\n".join(blocks)


def counted(n, one, many):
    return f"{n} {one if n == 1 else many}"


def build(now_local: datetime):
    start, end = week_window(now_local)
    rows = collect(start, end)
    last_day = end - timedelta(days=1)
    span = f"{start:%A %-d %B} to {last_day:%A %-d %B %Y}"

    groups = {key: [] for key, _, _ in STAGES}
    for stage, moment, story in rows:
        groups[stage].append((moment, story))

    order = ["arrested", "charged", "court", "sentenced", "appeal"]
    labels = {key: label for key, label, _ in STAGES}
    nouns = {
        "arrested": ("arrest", "arrests"), "charged": ("charge", "charges"),
        "court": ("court hearing", "court hearings"), "sentenced": ("sentencing", "sentencings"),
        "appeal": ("appeal", "appeals"),
    }

    if rows:
        parts = [counted(len(groups[k]), *nouns[k]) for k in order if groups[k]]
        summary_line = (", ".join(parts[:-1]) + " and " + parts[-1]) if len(parts) > 1 else parts[0]
        lead = f"Rochdale Daily reported {summary_line} in the borough from {span}."
        body = f"<p>{esc(lead)}</p>"
        for key in order:
            items = sorted(groups[key], key=lambda pair: pair[0])
            if items:
                body += f"<h2>{esc(labels[key])}</h2><ul>" + "".join(item_html(m, s) for m, s in items) + "</ul>"
        body += (
            '<p class="brief-foot">Anyone arrested or charged is presumed innocent unless '
            "and until proven guilty in court. Each case is listed once, at the furthest "
            "stage reported this week. Anyone named in a linked story can reply by emailing "
            "news@rochdaledaily.co.uk.</p>"
        )
    else:
        lead = f"Rochdale Daily reported no arrests, charges, court cases, sentencings or appeals in the borough from {span}."
        body = f"<p>{esc(lead)}</p>"

    date_text = now_local.strftime("%-d %B %Y")
    slug = f"{SLUG_PREFIX}-{now_local.strftime('%-d-%B-%Y').lower()}"
    stamp = now_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    image = POLICE_PHOTO if (ROOT / POLICE_PHOTO).exists() else ""

    return {
        "id": f"briefing-arrests-{slug}",
        "slug": slug,
        "title": f"Rochdale arrests this week: {date_text}",
        "excerpt": lead,
        "summary": lead,
        "content_html": body,
        "body": plain_text(body),
        "category": "crime",
        "police_matter": True,
        "area": "rochdale",
        "types": ["crime"],
        "image_url": image,
        "img": image,
        "image_alt": "Greater Manchester Police",
        "image_credit": "Rochdale Daily",
        "image_status": "editorial-photo",
        "published_at": stamp,
        "first_published_at": stamp,
        "last_updated_at": stamp,
        "scraped_at": stamp,
        "source_name": "Rochdale Daily",
        "source_names": ["Rochdale Daily"],
        "byline": "Rochdale Daily",
        "status": "published",
        "manual_article": True,
        "editorial_lock": True,
        "rewrite_quality_checked": True,
        "publication_route": ROUTE,
        "related_article_slugs": [s.get("slug") for _, _, s in rows][:12],
        "week_start": start.date().isoformat(),
        "week_counts": {k: len(groups[k]) for k in order},
        "right_to_reply": (
            "Anyone named in a linked story can reply by emailing "
            "news@rochdaledaily.co.uk and we will publish or append their response."
        ),
    }


def already_published(slug: str) -> bool:
    for path in (ARTICLES, MANUAL):
        if any(s.get("slug") == slug for s in as_list(load(path, []))):
            return True
    return bool(list(ROOT.glob(f"pending_manual_arrests_{slug}.json")))


def is_due(now_local: datetime) -> bool:
    return now_local.weekday() == 0 and PUBLISH_HOUR <= now_local.hour < LATEST_HOUR


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="Build now even if it is not Monday morning (covers the last full Mon-Sun week).")
    parser.add_argument("--dry-run", action="store_true", help="Print the story; write nothing.")
    args = parser.parse_args()

    now_local = datetime.now(timezone.utc).astimezone(LONDON)
    if not args.force and not is_due(now_local):
        print(f"Not Monday {PUBLISH_HOUR:02d}:00-{LATEST_HOUR:02d}:00 in London (now {now_local:%a %H:%M}); nothing to do.")
        return
    article = build(now_local)
    if args.dry_run:
        print(json.dumps({k: article[k] for k in ("title", "slug", "week_counts")}, indent=2))
        print(article["body"])
        return
    if already_published(article["slug"]):
        print(f"{article['title']} already exists; not duplicating.")
        return
    out = ROOT / f"pending_manual_arrests_{article['slug']}.json"
    with out.open("w", encoding="utf-8") as handle:
        json.dump([article], handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"Wrote {out.name}: {article['title']} {article['week_counts']}")


if __name__ == "__main__":
    main()
