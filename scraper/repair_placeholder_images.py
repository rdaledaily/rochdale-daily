#!/usr/bin/env python3
"""Replace generated/place cards with genuinely relevant reusable photography.

This is deliberately conservative for crime/allegation stories, where a loose
place/person match can create a serious accuracy problem. For other published
stories it searches Wikimedia Commons using the actual subject/place terms,
checks licence metadata, scores title+description relevance, downloads a local
copy, and updates articles.json.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

API = "https://commons.wikimedia.org/w/api.php"
UA = "RochdaleDailyImageRepair/1.0 (news@rochdaledaily.co.uk)"
MIN_WIDTH = 700
MIN_HEIGHT = 400
MAX_BYTES = 15 * 1024 * 1024

STOP = {
    "about","after","again","against","ahead","amid","and","are","around","at",
    "back","before","being","for","from","has","have","into","its","new","news",
    "of","on","over","the","this","to","with","will","in","a","an","is","our",
    "their","they","more","than","following","latest","today","week","weeks",
    "rochdale","heywood","middleton","littleborough","milnrow","norden","healey",
}
PLACE_TYPES = {
    "road","street","lane","park","hall","school","church","reservoir","mill",
    "station","hospital","infirmary","canal","bridge","centre","center","arena",
    "stadium","estate","moor","dell","square","museum","library","academy",
}
ALLOWED_LICENSE_BITS = (
    "cc by ", "cc-by-", "cc by-sa", "cc-by-sa", "creative commons attribution",
    "public domain", "pd-", "cc0", "open government licence", "ogl",
)


def clean(v: Any) -> str:
    return str(v or "").strip()


def text(v: Any) -> str:
    if isinstance(v, dict):
        v = v.get("value", "")
    return BeautifulSoup(html.unescape(clean(v)), "html.parser").get_text(" ", strip=True)


def placeholder(article: dict[str, Any]) -> bool:
    image = clean(article.get("image_url") or article.get("img")).lower()
    status = clean(article.get("image_status")).lower()
    reuse = clean(article.get("source_image_reuse_status")).lower()
    return (
        not image
        or "area-category-card" in image
        or "img/generated" in image
        or "placeholder" in image
        or status in {"area-category-card", "generated-placeholder"}
        or reuse == "category-fallback"
    )


def sensitive(article: dict[str, Any]) -> bool:
    if clean(article.get("category")).lower() == "crime" or article.get("police_matter"):
        return True
    title = clean(article.get("title")).lower()
    return bool(re.search(r"\b(alleged|allegation|accused|arrested|charged|rape|kidnap|fraud|abuse|wanted)\b", title))


def words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def subject_tokens(article: dict[str, Any]) -> list[str]:
    title = clean(article.get("title"))
    toks = [w for w in words(title) if len(w) >= 4 and w not in STOP and not w.isdigit()]
    # Prefer distinctive words; generic editorial verbs are poor image subjects.
    weak = {"calls","plans","urges","backs","returns","raises","could","would","people","local","residents","community","service","services","update","updates"}
    toks = [w for w in toks if w not in weak]
    return list(dict.fromkeys(toks))[:10]


def proper_phrases(title: str) -> list[str]:
    # Capture headline names/places before common place-type nouns.
    chunks = re.findall(r"\b(?:[A-Z][A-Za-z'’-]+(?:\s+|$)){1,5}", title)
    out: list[str] = []
    for chunk in chunks:
        phrase = re.sub(r"\s+", " ", chunk).strip(" -–—:'")
        low = phrase.lower()
        if len(phrase.split()) >= 2 and low not in {"rochdale daily", "greater manchester"}:
            out.append(phrase)
    return list(dict.fromkeys(out))[:5]


def queries(article: dict[str, Any]) -> list[str]:
    title = clean(article.get("title"))
    area = clean(article.get("area"))
    toks = subject_tokens(article)
    qs: list[str] = []
    for phrase in proper_phrases(title):
        qs.append(phrase)
        if area and area.lower() not in phrase.lower():
            qs.append(f"{phrase} {area}")
    # Place-type pair, e.g. "Simpson Clough Paper Mill", "Lower Falinge estate".
    raw = words(title)
    for i, w in enumerate(raw):
        if w in PLACE_TYPES:
            start = max(0, i - 4)
            phrase = " ".join(raw[start:i+1])
            if phrase:
                qs.append(phrase)
                if area:
                    qs.append(f"{phrase} {area}")
    if toks:
        qs.append(" ".join(toks[:5]))
        if area:
            qs.append(f"{area} {' '.join(toks[:3])}")
        for token in toks[:4]:
            if area:
                qs.append(f"{area} {token}")
            qs.append(token)
    # Commons often indexes Rochdale landmarks by borough/town even when the
    # news headline uses a neighbourhood.
    if area and area.lower() != "rochdale" and toks:
        qs.append(f"Rochdale {toks[0]}")
    return list(dict.fromkeys(q.strip() for q in qs if q.strip()))[:14]


def get_json(params: dict[str, str], timeout: int) -> dict[str, Any]:
    url = API + "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def license_ok(meta: dict[str, Any]) -> bool:
    combined = " ".join([
        text(meta.get("LicenseShortName")), text(meta.get("UsageTerms")),
        text(meta.get("License")), text(meta.get("Copyrighted")),
    ]).lower()
    return any(bit in combined for bit in ALLOWED_LICENSE_BITS)


def score(article: dict[str, Any], file_title: str, meta: dict[str, Any]) -> int:
    toks = subject_tokens(article)
    area = clean(article.get("area")).lower()
    hay = " ".join([
        file_title, text(meta.get("ObjectName")), text(meta.get("ImageDescription")),
        text(meta.get("Categories")), text(meta.get("Credit")),
    ]).lower()
    s = 0
    matched = 0
    for t in toks:
        if re.search(rf"\b{re.escape(t)}\b", hay):
            matched += 1
            s += 3 if len(t) >= 8 else 2
    if area and re.search(rf"\b{re.escape(area)}\b", hay):
        s += 3
    if "rochdale" in hay:
        s += 2
    for phrase in proper_phrases(clean(article.get("title"))):
        p = phrase.lower()
        if len(p) >= 6 and p in hay:
            s += 8
    # A single distinctive long subject word is enough for generic subjects
    # such as horsetail/calamites; otherwise demand stronger corroboration.
    if matched == 1 and any(len(t) >= 9 and re.search(rf"\b{re.escape(t)}\b", hay) for t in toks):
        s += 2
    return s


def search_one(article: dict[str, Any], timeout: int) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    seen_titles: set[str] = set()
    for q in queries(article):
        try:
            data = get_json({
                "action":"query", "format":"json", "formatversion":"2",
                "list":"search", "srnamespace":"6", "srlimit":"12", "srsearch":q,
                "origin":"*",
            }, timeout)
        except Exception:
            continue
        results = data.get("query", {}).get("search", [])
        titles = [clean(r.get("title")) for r in results if isinstance(r, dict) and clean(r.get("title"))]
        titles = [t for t in titles if t not in seen_titles][:10]
        seen_titles.update(titles)
        if not titles:
            continue
        try:
            info_data = get_json({
                "action":"query", "format":"json", "formatversion":"2",
                "titles":"|".join(titles), "prop":"imageinfo",
                "iiprop":"url|size|mime|extmetadata", "iiurlwidth":"1600", "origin":"*",
            }, timeout)
        except Exception:
            continue
        for page in info_data.get("query", {}).get("pages", []):
            if not isinstance(page, dict):
                continue
            file_title = clean(page.get("title"))
            infos = page.get("imageinfo") or []
            if not infos or not isinstance(infos[0], dict):
                continue
            info = infos[0]
            if clean(info.get("mime")).lower() not in {"image/jpeg","image/png","image/webp"}:
                continue
            if int(info.get("width") or 0) < MIN_WIDTH or int(info.get("height") or 0) < MIN_HEIGHT:
                continue
            meta = info.get("extmetadata") or {}
            if not license_ok(meta):
                continue
            sc = score(article, file_title, meta)
            # 5 = area + one subject, or one exact/distinctive subject. This is
            # intentionally much stricter than simply taking the first result.
            if sc < 5:
                continue
            candidate = {"score":sc, "title":file_title, "info":info, "meta":meta}
            if best is None or sc > best[0]:
                best = (sc, candidate)
        if best and best[0] >= 10:
            break
    return best[1] if best else None


def download(url: str, timeout: int) -> tuple[bytes, str] | None:
    try:
        req = Request(url, headers={"User-Agent":UA, "Accept":"image/webp,image/jpeg,image/png,*/*;q=0.2"})
        with urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get_content_type().lower()
            data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES or len(data) < 7000:
            return None
        ext = {"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}.get(ctype)
        if not ext:
            if data.startswith(b"\xff\xd8\xff"): ext = ".jpg"
            elif data.startswith(b"\x89PNG"): ext = ".png"
            elif data[:4] == b"RIFF" and data[8:12] == b"WEBP": ext = ".webp"
        return (data, ext) if ext else None
    except Exception:
        return None


def slug(article: dict[str, Any]) -> str:
    raw = clean(article.get("slug") or article.get("id") or article.get("title"))
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:80] or "story"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--articles", type=Path, default=Path("articles.json"))
    ap.add_argument("--output-dir", type=Path, default=Path("assets/article-images"))
    ap.add_argument("--timeout", type=int, default=15)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    data = json.loads(args.articles.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("articles.json must contain a list")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tried = replaced = 0
    report: list[dict[str, Any]] = []

    for a in data:
        if not isinstance(a, dict) or clean(a.get("status") or "published").lower() != "published":
            continue
        if not placeholder(a) or sensitive(a):
            continue
        if args.limit and tried >= args.limit:
            break
        tried += 1
        found = search_one(a, args.timeout)
        if not found:
            report.append({"slug":slug(a), "result":"no-relevant-commons"})
            continue
        info, meta = found["info"], found["meta"]
        image_url = clean(info.get("thumburl") or info.get("url"))
        fetched = download(image_url, args.timeout)
        if not fetched:
            report.append({"slug":slug(a), "result":"download-failed", "commons":found["title"]})
            continue
        payload, ext = fetched
        digest = hashlib.sha256(payload).hexdigest()[:12]
        path = args.output_dir / f"{slug(a)}-commons-{digest}{ext}"
        if not path.exists():
            path.write_bytes(payload)
        artist = text(meta.get("Artist")) or text(meta.get("Credit"))
        a["image_url"] = path.as_posix()
        a["img"] = path.as_posix()
        a["image_credit"] = f"{artist} / Wikimedia Commons" if artist else "Wikimedia Commons"
        a["image_credit_url"] = "https://commons.wikimedia.org/wiki/" + quote(found["title"].replace(" ", "_"), safe=":_/()")
        a["source_image_candidate_url"] = image_url
        a["source_image_reuse_status"] = "wikimedia-commons-reusable"
        a["image_status"] = "wikimedia-commons"
        a["image_backfill_method"] = "wikimedia-commons-subject-repair"
        a.pop("image_placeholder_reason", None)
        replaced += 1
        report.append({"slug":slug(a), "result":"replaced", "commons":found["title"], "score":found["score"]})
        print(f"commons-replaced {slug(a)} <- {found['title']} ({found['score']})")

    args.articles.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path("commons_image_repair_report.json").write_text(json.dumps({"tried":tried,"replaced":replaced,"items":report}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tried":tried,"replaced":replaced}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
