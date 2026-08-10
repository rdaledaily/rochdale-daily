#!/usr/bin/env python3
"""Replace fallback cards with genuinely relevant Wikimedia Commons photography.

The matcher is deliberately strict: a candidate must match a named subject/place
or multiple distinctive headline terms, with local corroboration where needed.
Generic single-word overlaps are not enough. Crime/allegation stories remain
excluded from automatic Commons matching.
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
UA = "RochdaleDailyImageRepair/2.0 (news@rochdaledaily.co.uk)"
MIN_WIDTH = 700
MIN_HEIGHT = 400
MAX_BYTES = 15 * 1024 * 1024
MIN_SCORE = 10

STOP = {
    "about","after","again","against","ahead","amid","and","are","around","at",
    "back","before","being","for","from","has","have","into","its","new","news",
    "of","on","over","the","this","to","with","will","in","a","an","is","our",
    "their","they","more","than","following","latest","today","week","weeks",
    "calls","plans","urges","backs","returns","raises","could","would","people",
    "local","residents","community","service","services","update","updates",
}
LOCAL_TERMS = {
    "rochdale","heywood","middleton","littleborough","milnrow","newhey","norden",
    "healey","wardle","smallbridge","smithy","bridge","castleton","spotland",
    "falinge","deeplish","balderstone","firgrove","kirkholt","bamford","shawclough",
    "syke","wardleworth","sudden","lowerplace","meanwood","cutgate","darnhill",
    "hopwood","alkrington","boarshaw","whitworth",
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


def words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def placeholder(a: dict[str, Any]) -> bool:
    image = clean(a.get("image_url") or a.get("img")).lower()
    status = clean(a.get("image_status")).lower()
    reuse = clean(a.get("source_image_reuse_status")).lower()
    return (not image or "area-category-card" in image or "img/generated" in image or
            "placeholder" in image or status in {"area-category-card","generated-placeholder"} or
            reuse == "category-fallback")


def sensitive(a: dict[str, Any]) -> bool:
    if clean(a.get("category")).lower() == "crime" or a.get("police_matter"):
        return True
    title = clean(a.get("title")).lower()
    return bool(re.search(r"\b(alleged|allegation|accused|arrested|charged|rape|kidnap|fraud|abuse|wanted)\b", title))


def subject_tokens(a: dict[str, Any]) -> list[str]:
    toks = [w for w in words(clean(a.get("title"))) if len(w) >= 4 and w not in STOP and not w.isdigit()]
    return list(dict.fromkeys(toks))[:12]


def proper_phrases(title: str) -> list[str]:
    chunks = re.findall(r"\b(?:[A-Z][A-Za-z'’-]+(?:\s+|$)){1,6}", title)
    out = []
    for chunk in chunks:
        phrase = re.sub(r"\s+", " ", chunk).strip(" -–—:'")
        low = phrase.lower()
        if len(phrase.split()) >= 2 and low not in {"rochdale daily","greater manchester"}:
            out.append(phrase)
    return list(dict.fromkeys(out))[:6]


def named_place_phrases(title: str) -> list[str]:
    raw = words(title)
    out = []
    for i, w in enumerate(raw):
        if w in PLACE_TYPES:
            start = max(0, i - 4)
            phrase = " ".join(raw[start:i+1])
            phrase = " ".join(x for x in phrase.split() if x not in STOP)
            if len(phrase.split()) >= 2:
                out.append(phrase)
    return list(dict.fromkeys(out))[:6]


def queries(a: dict[str, Any]) -> list[str]:
    title = clean(a.get("title"))
    area = clean(a.get("area"))
    toks = subject_tokens(a)
    qs = []
    for phrase in proper_phrases(title) + named_place_phrases(title):
        qs.append(phrase)
        if area and area.lower() not in phrase.lower():
            qs.append(f"{phrase} {area}")
        qs.append(f"{phrase} Rochdale")
    if len(toks) >= 2:
        qs.append(" ".join(toks[:5]))
        if area:
            qs.append(f"{area} {' '.join(toks[:4])}")
    return list(dict.fromkeys(q.strip() for q in qs if q.strip()))[:12]


def get_json(params: dict[str, str], timeout: int) -> dict[str, Any]:
    req = Request(API + "?" + urlencode(params), headers={"User-Agent":UA,"Accept":"application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def license_ok(meta: dict[str, Any]) -> bool:
    combined = " ".join([text(meta.get("LicenseShortName")), text(meta.get("UsageTerms")),
                         text(meta.get("License")), text(meta.get("Copyrighted"))]).lower()
    return any(bit in combined for bit in ALLOWED_LICENSE_BITS)


def evidence(a: dict[str, Any], file_title: str, meta: dict[str, Any]) -> tuple[int, int, bool, bool]:
    hay = " ".join([file_title, text(meta.get("ObjectName")), text(meta.get("ImageDescription")),
                    text(meta.get("Categories")), text(meta.get("Credit"))]).lower()
    toks = subject_tokens(a)
    matched = [t for t in toks if re.search(rf"\b{re.escape(t)}\b", hay)]
    exact_phrase = any(p.lower() in hay for p in proper_phrases(clean(a.get("title"))) + named_place_phrases(clean(a.get("title"))) if len(p) >= 6)
    area = clean(a.get("area")).lower()
    local = (bool(area and re.search(rf"\b{re.escape(area)}\b", hay)) or
             "rochdale" in hay or any(re.search(rf"\b{re.escape(t)}\b", hay) for t in LOCAL_TERMS & set(words(clean(a.get("title"))))))
    score = len(matched) * 3 + sum(2 for t in matched if len(t) >= 8)
    if exact_phrase:
        score += 10
    if local:
        score += 4
    return score, len(matched), exact_phrase, local


def acceptable(a: dict[str, Any], file_title: str, meta: dict[str, Any]) -> tuple[bool, int]:
    score, matched, exact_phrase, local = evidence(a, file_title, meta)
    # Named subject/place is strongest. Otherwise require at least two distinctive
    # headline tokens plus local corroboration. A lone generic word never passes.
    ok = (exact_phrase and score >= MIN_SCORE) or (matched >= 2 and local and score >= MIN_SCORE)
    return ok, score


def search_one(a: dict[str, Any], timeout: int) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    seen = set()
    for q in queries(a):
        try:
            data = get_json({"action":"query","format":"json","formatversion":"2","list":"search",
                             "srnamespace":"6","srlimit":"12","srsearch":q,"origin":"*"}, timeout)
        except Exception:
            continue
        titles = [clean(r.get("title")) for r in data.get("query",{}).get("search",[]) if isinstance(r,dict) and clean(r.get("title"))]
        titles = [t for t in titles if t not in seen][:10]
        seen.update(titles)
        if not titles:
            continue
        try:
            info_data = get_json({"action":"query","format":"json","formatversion":"2","titles":"|".join(titles),
                                  "prop":"imageinfo","iiprop":"url|size|mime|extmetadata","iiurlwidth":"1600","origin":"*"}, timeout)
        except Exception:
            continue
        for page in info_data.get("query",{}).get("pages",[]):
            if not isinstance(page,dict):
                continue
            infos = page.get("imageinfo") or []
            if not infos or not isinstance(infos[0],dict):
                continue
            info = infos[0]
            if clean(info.get("mime")).lower() not in {"image/jpeg","image/png","image/webp"}:
                continue
            if int(info.get("width") or 0) < MIN_WIDTH or int(info.get("height") or 0) < MIN_HEIGHT:
                continue
            meta = info.get("extmetadata") or {}
            if not license_ok(meta):
                continue
            ok, sc = acceptable(a, clean(page.get("title")), meta)
            if not ok:
                continue
            candidate = {"score":sc,"title":clean(page.get("title")),"info":info,"meta":meta}
            if best is None or sc > best[0]:
                best = (sc, candidate)
        if best and best[0] >= 16:
            break
    return best[1] if best else None


def download(url: str, timeout: int) -> tuple[bytes, str] | None:
    try:
        req = Request(url, headers={"User-Agent":UA,"Accept":"image/webp,image/jpeg,image/png,*/*;q=0.2"})
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


def slug(a: dict[str, Any]) -> str:
    raw = clean(a.get("slug") or a.get("id") or a.get("title"))
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:80] or "story"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--articles", type=Path, default=Path("articles.json"))
    ap.add_argument("--output-dir", type=Path, default=Path("assets/article-images"))
    ap.add_argument("--timeout", type=int, default=15)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    data = json.loads(args.articles.read_text(encoding="utf-8"))
    if not isinstance(data,list):
        raise SystemExit("articles.json must contain a list")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tried = replaced = 0
    report = []

    for a in data:
        if not isinstance(a,dict) or clean(a.get("status") or "published").lower() != "published":
            continue
        if not placeholder(a) or sensitive(a):
            continue
        if args.limit and tried >= args.limit:
            break
        tried += 1
        found = search_one(a, args.timeout)
        if not found:
            report.append({"slug":slug(a),"result":"no-strict-relevant-commons"})
            continue
        info, meta = found["info"], found["meta"]
        image_url = clean(info.get("thumburl") or info.get("url"))
        fetched = download(image_url, args.timeout)
        if not fetched:
            report.append({"slug":slug(a),"result":"download-failed","commons":found["title"]})
            continue
        payload, ext = fetched
        digest = hashlib.sha256(payload).hexdigest()[:12]
        path = args.output_dir / f"{slug(a)}-commons-{digest}{ext}"
        if not path.exists():
            path.write_bytes(payload)
        artist = text(meta.get("Artist")) or text(meta.get("Credit"))
        a["image_url"] = path.as_posix(); a["img"] = path.as_posix()
        a["image_credit"] = f"{artist} / Wikimedia Commons" if artist else "Wikimedia Commons"
        a["image_credit_url"] = "https://commons.wikimedia.org/wiki/" + quote(found["title"].replace(" ","_"), safe=":_/()")
        a["source_image_candidate_url"] = image_url
        a["source_image_reuse_status"] = "wikimedia-commons-reusable"
        a["image_status"] = "wikimedia-commons"
        a["image_backfill_method"] = "wikimedia-commons-strict-subject-repair"
        a.pop("image_placeholder_reason", None)
        replaced += 1
        report.append({"slug":slug(a),"result":"replaced","commons":found["title"],"score":found["score"]})
        print(f"commons-replaced {slug(a)} <- {found['title']} ({found['score']})")

    args.articles.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path("commons_image_repair_report.json").write_text(json.dumps({"tried":tried,"replaced":replaced,"items":report}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tried":tried,"replaced":replaced}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
