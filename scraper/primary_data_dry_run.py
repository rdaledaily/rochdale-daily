#!/usr/bin/env python3
"""Read-only measurement of candidate primary-data sources from a GitHub runner.

Prints one block per source: HTTP status, how many items the endpoint carries,
how many are about the borough, and the date span. Saves the raw response of
each endpoint under dry_run_samples/ so parsers are written against real data,
not a guess at the format. Publishes nothing and writes no state.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import primary_data  # noqa: E402

UA = "RochdaleDailyBot/1.0 (+https://rochdaledaily.co.uk/about.html)"
S = requests.Session()
S.headers["User-Agent"] = UA
OUT = Path("dry_run_samples")
OUT.mkdir(exist_ok=True)
NOW = datetime.now(timezone.utc)
ONLY = {k.strip() for k in os.getenv("PROBE_ONLY", "").split(",") if k.strip()}
BOROUGH = re.compile(r"\b(rochdale|heywood|middleton|littleborough|milnrow|newhey|wardle|"
                     r"castleton|smithy bridge|norden|bamford|kirkholt|alkrington|hopwood)\b", re.I)


def save(name: str, text: str) -> None:
    (OUT / name).write_text(text[:2_000_000], encoding="utf-8")


def get(name: str, url: str, **kw):
    try:
        r = S.get(url, timeout=25, **kw)
    except Exception as exc:  # noqa: BLE001
        print(f"  {name}: FETCH FAILED {type(exc).__name__}: {exc}"[:300])
        return None
    print(f"  {name}: HTTP {r.status_code} {r.headers.get('content-type','')} {len(r.content)} bytes")
    save(name, r.text)
    return r


def section(key: str) -> bool:
    if ONLY and key not in ONLY:
        return False
    print(f"\n=== {key} ===")
    return True


def find_tender() -> None:
    """Full 72-hour crawl, paced, comparing the loose regex with the postcode rule."""
    if not section("find_tender"):
        return
    import time
    frm = (NOW - timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%S")
    params = {"updatedFrom": frm, "updatedTo": NOW.strftime("%Y-%m-%dT%H:%M:%S"), "limit": "100"}
    url, total, pages, loose, strict, full = primary_data.FTS_API, 0, 0, [], [], []
    while url and pages < 60:
        if pages:
            time.sleep(2.5)
        r = S.get(url, params=params, timeout=30) if params else S.get(url, timeout=30)
        if r.status_code != 200:
            print(f"  page {pages}: HTTP {r.status_code}")
            break
        d = r.json()
        pages += 1
        rels = d.get("releases") or []
        if pages == 1 or not d.get("links", {}).get("next"):
            print(f"  page {pages}: {rels[0].get('date') if rels else None} .. {rels[-1].get('date') if rels else None}")
        for rel in rels:
            total += 1
            blob = json.dumps(rel.get("parties") or []) + str((rel.get("buyer") or {}).get("name"))
            a, b = bool(BOROUGH.search(blob)), primary_data.is_borough_buyer(rel)
            if a or b:
                (strict if b else loose).append(rel)
                if b:
                    full.append(rel)
        nxt = (d.get("links") or {}).get("next")
        url, params = (nxt, None) if nxt else (None, None)
    print(f"  pages={pages} releases={total} complete={url is None} postcode_rule={len(strict)} regex_only={len(loose)}")
    for rel in strict:
        dsc = primary_data.describe_release(rel)
        print("   KEEP", rel.get("id"), rel.get("tag"), "|", (rel.get("buyer") or {}).get("name"), "|", dsc[1][:110] if dsc else "(not a story type)")
    for rel in loose:
        bp = primary_data._buyer_party(rel)
        print("   DROP", rel.get("id"), rel.get("tag"), "|", (rel.get("buyer") or {}).get("name"), "| buyer pc", (bp.get("address") or {}).get("postalCode"))
    save("fts_borough_releases.json", json.dumps(full, indent=1))


def contracts_finder() -> None:
    if not section("contracts_finder"):
        return
    url = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
    params = {"publishedFrom": (NOW - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S"),
              "publishedTo": NOW.strftime("%Y-%m-%dT%H:%M:%S"), "size": "100"}
    total = local = pages = 0
    hits = []
    cursor_url, cursor_params = url, params
    while cursor_url and pages < 40:
        if pages:
            __import__("time").sleep(3)
        r = get(f"cf_page{pages}.json" if pages < 2 else "cf_last.json", cursor_url, params=cursor_params)
        if r is None or r.status_code != 200:
            break
        d = r.json()
        pages += 1
        for pkg in d.get("releases") or []:
            total += 1
            buyer = str((pkg.get("buyer") or {}).get("name") or "")
            addr = json.dumps([p.get("address") for p in pkg.get("parties") or []])
            if BOROUGH.search(buyer) or BOROUGH.search(addr):
                local += 1
                hits.append({"id": pkg.get("id"), "date": pkg.get("date"), "tag": pkg.get("tag"), "buyer": buyer,
                             "title": (pkg.get("tender") or {}).get("title"),
                             "awards": [((a.get("value") or {}).get("amount"), [s.get("name") for s in a.get("suppliers") or []])
                                        for a in pkg.get("awards") or []]})
        nxt = (d.get("links") or {}).get("next")
        cursor_url, cursor_params = (nxt, None) if nxt else (None, None)
    print(f"  pages={pages} releases={total} naming-borough={local}")
    save("cf_hits.json", json.dumps(hits, indent=1, default=str))
    for h in hits[:40]:
        print("   ", h["date"], h["tag"], "|", h["buyer"], "|", (h["title"] or "")[:90], "|", h["awards"][:2])


def met_office() -> None:
    if not section("met_office_warnings"):
        return
    for name, url in (("mo_nw.xml", "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/nw"),
                      ("mo_uk.xml", "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK")):
        r = get(name, url)
        if r is not None:
            items = re.findall(r"<item>.*?</item>", r.text, re.S)
            print(f"   items={len(items)}")
            for it in items[:10]:
                t = re.search(r"<title>(.*?)</title>", it, re.S)
                print("    -", (t.group(1) if t else "")[:160])


def gazette_all() -> None:
    if not section("gazette_all"):
        return
    today = NOW.date()
    counts: dict[str, list] = {}
    page = 1
    while page <= 12:
        r = get(f"gazette_p{page}.json" if page < 3 else "gazette_last.json",
                "https://www.thegazette.co.uk/all-notices/notice/data.json",
                params={"location-local-authority-1": "rochdale",
                        "start-publish-date": str(today - timedelta(days=30)),
                        "end-publish-date": str(today), "results-page-size": "100",
                        "results-page": str(page), "sort-by": "latest-date"})
        if r is None or r.status_code != 200:
            break
        entries = r.json().get("entry") or []
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            code = str(e.get("f:notice-code") or "")
            counts.setdefault(code, [0, e.get("category", ""), []])
            counts[code][0] += 1
            if len(counts[code][2]) < 4:
                counts[code][2].append(str(e.get("title"))[:80])
        if len(entries) < 100:
            break
        page += 1
    for code, (n, cat, ex) in sorted(counts.items(), key=lambda kv: -kv[1][0]):
        print(f"   code {code:>5} x{n:<4} {json.dumps(cat)[:60]} e.g. {ex}")


def nomis() -> None:
    if not section("nomis"):
        return
    r = get("nomis_geo.json", "https://www.nomisweb.co.uk/api/v01/dataset/NM_162_1/geography/TYPE424.def.sdmx.json",
            params={"search": "rochdale"})
    if r is not None and r.ok:
        print("   ", r.text[:600].replace("\n", " "))
    r = get("nomis_cc.csv", "https://www.nomisweb.co.uk/api/v01/dataset/NM_162_1.data.csv",
            params={"geography": "1778385128", "date": "latestMINUS2-latest", "gender": "0", "age": "0",
                    "measure": "1,2", "measures": "20100",
                    "select": "date_name,geography_name,geography_code,measure_name,obs_value"})
    if r is not None:
        print("   ", r.text[:900])
    r = get("nomis_lmp.html", "https://www.nomisweb.co.uk/reports/lmp/la/1946157091/report.aspx")
    if r is not None:
        h = re.search(r"<h1[^>]*>(.*?)</h1>", r.text, re.S)
        print("    lmp h1:", re.sub(r"<[^>]+>", " ", h.group(1)).strip()[:120] if h else None)
        print("    lmp mentions Rochdale:", "Rochdale" in r.text, "| 'claimant' count:", r.text.lower().count("claimant"))
    if r is not None:
        t = re.search(r"<title>(.*?)</title>", r.text, re.S)
        print("    lmp title:", t.group(1).strip() if t else None)
        m = re.search(r"Claimant count[^<]{0,200}", r.text)
        print("    claimant mention:", m.group(0)[:200] if m else None)


def petitions() -> None:
    if not section("petitions"):
        return
    for state in ("open", "closed"):
        r = get(f"pet_{state}.json", "https://petition.parliament.uk/petitions.json", params={"q": "rochdale", "state": state})
        if r is not None and r.ok:
            d = r.json().get("data") or []
            print(f"   q=rochdale state={state}: {len(d)}")
            for p in d[:8]:
                a = p.get("attributes") or {}
                print("    -", p.get("id"), a.get("created_at", "")[:10], a.get("signature_count"), a.get("action", "")[:90])


def case_law() -> None:
    if not section("case_law"):
        return
    r = get("caselaw.xml", "https://caselaw.nationalarchives.gov.uk/atom.xml", params={"query": "Rochdale", "order": "-date"})
    if r is not None and r.ok:
        entries = re.findall(r"<entry>.*?</entry>", r.text, re.S)
        print(f"   entries={len(entries)}")
        for e in entries[:15]:
            t = re.search(r"<title>(.*?)</title>", e, re.S)
            d = re.search(r"<published>(.*?)</published>", e) or re.search(r"<updated>(.*?)</updated>", e)
            print("    -", (d.group(1) if d else "")[:10], (t.group(1) if t else "")[:110])


def leads() -> None:
    if not section("leads"):
        return
    for name, url in (("fms.xml", "https://www.fixmystreet.com/rss/reports/Rochdale"),
                      ("wdtk_council.xml", "https://www.whatdotheyknow.com/feed/body/rochdale_metropolitan_borough_council"),
                      ("wdtk_council_alt.xml", "https://www.whatdotheyknow.com/body/rochdale_metropolitan_borough_council/feed")):
        r = get(name, url)
        if r is not None and r.ok:
            items = re.findall(r"<(?:item|entry)>.*?</(?:item|entry)>", r.text, re.S)
            dates = re.findall(r"<(?:pubDate|updated|published)>(.*?)</", r.text)
            print(f"   items={len(items)} first/last dates={dates[1:2]} / {dates[-1:]}")
            for it in items[:5]:
                t = re.search(r"<title[^>]*>(.*?)</title>", it, re.S)
                print("    -", (t.group(1) if t else "")[:120])


def existing_rota() -> None:
    """Dry run the sources already on the rota, with a throwaway state."""
    if not section("existing_rota"):
        return
    state: dict = {"sources": {}}
    records, report = primary_data.collect(S.get, state, NOW)
    print(json.dumps(report, indent=1)[:3000])
    for rec in records:
        print("   offer:", rec["source_key"], "|", rec["source_title"][:110], "|", rec["source_url"])


ROCHDALE_LAT, ROCHDALE_LNG = 53.6136, -2.1610


def keyed() -> None:
    """Sources that need a free key. Each says plainly when its key is missing."""
    if not section("keyed"):
        return
    ch = os.getenv("COMPANIES_HOUSE_API_KEY", "").strip()
    if not ch:
        print("  companies_house: no key (COMPANIES_HOUSE_API_KEY secret not set)")
    else:
        since = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
        r = S.get("https://api.company-information.service.gov.uk/advanced-search/companies",
                  params={"location": "Rochdale", "incorporated_from": since, "size": "100"},
                  auth=(ch, ""), timeout=25)
        print(f"  companies_house new incorporations since {since}: HTTP {r.status_code}")
        if r.ok:
            d = r.json()
            items = d.get("items") or []
            print(f"   hits={d.get('hits')} returned={len(items)}")
            save("ch_new.json", r.text)
            for it in items[:10]:
                print("    -", it.get("date_of_creation"), it.get("company_name"), "|",
                      (it.get("registered_office_address") or {}).get("postal_code"), "|", it.get("sic_codes"))
    sk = os.getenv("SKIDDLE_API_KEY", "").strip()
    if not sk:
        print("  skiddle: no key (SKIDDLE_API_KEY secret not set)")
    else:
        r = S.get("https://www.skiddle.com/api/v1/events/search/",
                  params={"api_key": sk, "latitude": ROCHDALE_LAT, "longitude": ROCHDALE_LNG, "radius": "5",
                          "minDate": NOW.strftime("%Y-%m-%d"), "maxDate": (NOW + timedelta(days=30)).strftime("%Y-%m-%d"),
                          "limit": "100", "order": "date", "description": "1"}, timeout=25)
        print(f"  skiddle events within 5 miles, next 30 days: HTTP {r.status_code}")
        if r.ok:
            d = r.json()
            res = d.get("results") or []
            print(f"   totalcount={d.get('totalcount')} returned={len(res)}")
            save("skiddle.json", r.text)
            towns: dict[str, int] = {}
            for e in res:
                town = str((e.get("venue") or {}).get("town") or "?")
                towns[town] = towns.get(town, 0) + 1
            print("   by town:", towns)
            for e in res[:12]:
                print("    -", e.get("date"), "|", (e.get("venue") or {}).get("name"), "|", (e.get("eventname") or "")[:80])
    tm = os.getenv("TICKETMASTER_API_KEY", "").strip()
    if not tm:
        print("  ticketmaster: no key (TICKETMASTER_API_KEY secret not set)")
    else:
        r = S.get("https://app.ticketmaster.com/discovery/v2/events.json",
                  params={"apikey": tm, "latlong": f"{ROCHDALE_LAT},{ROCHDALE_LNG}", "radius": "5", "unit": "miles",
                          "countryCode": "GB", "size": "100", "sort": "date,asc"}, timeout=25)
        print(f"  ticketmaster events within 5 miles: HTTP {r.status_code}")
        if r.ok:
            d = r.json()
            ev = (d.get("_embedded") or {}).get("events") or []
            print(f"   total={(d.get('page') or {}).get('totalElements')} returned={len(ev)}")
            save("ticketmaster.json", r.text)
            for e in ev[:12]:
                v = ((e.get("_embedded") or {}).get("venues") or [{}])[0]
                print("    -", (e.get("dates") or {}).get("start", {}).get("localDate"), "|", v.get("name"), "|", (v.get("city") or {}).get("name"), "|", e.get("name", "")[:70])
    print("  cqc:", "key present (collector in register_watch.py will run)" if os.getenv("CQC_SUBSCRIPTION_KEY", "").strip()
          else "no key (CQC_SUBSCRIPTION_KEY secret not set)")


def contracts_finder_full() -> None:
    """Full 14-day crawl, paced, with the same postcode rule as Find a Tender."""
    if not section("contracts_finder_full"):
        return
    import time
    url = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
    params = {"publishedFrom": (NOW - timedelta(days=14)).strftime("%Y-%m-%d"), "publishedTo": NOW.strftime("%Y-%m-%d"), "limit": "100"}
    pages = total = 0
    keep, loose = [], []
    while url and pages < 80:
        if pages:
            time.sleep(2.5)
        r = S.get(url, params=params, timeout=30) if params else S.get(url, timeout=30)
        if r.status_code != 200:
            print(f"  page {pages}: HTTP {r.status_code}")
            break
        d = r.json()
        pages += 1
        for rel in d.get("releases") or []:
            total += 1
            if primary_data.is_borough_buyer(rel):
                keep.append(rel)
            elif BOROUGH.search(json.dumps(rel.get("parties") or [])):
                loose.append(rel)
        nxt = (d.get("links") or {}).get("next")
        url, params = (nxt, None) if nxt else (None, None)
    print(f"  pages={pages} releases={total} complete={url is None} postcode_rule={len(keep)} regex_only={len(loose)}")
    for rel in keep:
        dsc = primary_data.describe_release(rel)
        docs = [d.get("url") for d in ((rel.get("tender") or {}).get("documents") or []) + [x for a in rel.get("awards") or [] for x in a.get("documents") or []]][:2]
        print("   KEEP", rel.get("id"), rel.get("tag"), rel.get("date"), "|", (rel.get("buyer") or {}).get("name"), "|", dsc[1][:100] if dsc else "(not story type)", "|", docs)
    for rel in loose[:15]:
        bp = primary_data._buyer_party(rel)
        print("   DROP", rel.get("tag"), "|", (rel.get("buyer") or {}).get("name"), "| buyer pc", (bp.get("address") or {}).get("postalCode"))
    save("cf_borough.json", json.dumps(keep[:20], indent=1))


def contracts_finder_retry() -> None:
    """Round 2 returned 0 releases with publishedFrom dropped; try the documented parameter set."""
    if not section("contracts_finder_retry"):
        return
    for params in ({"publishedFrom": (NOW - timedelta(days=7)).strftime("%Y-%m-%d"), "publishedTo": NOW.strftime("%Y-%m-%d"), "limit": "100"},
                   {"publishedFrom": (NOW - timedelta(days=7)).strftime("%Y-%m-%d"), "limit": "100", "stages": "award"}):
        r = S.get("https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search", params=params, timeout=25)
        try:
            d = r.json()
        except ValueError:
            d = {}
        rels = d.get("releases") or []
        local = [x for x in rels if BOROUGH.search(json.dumps(x.get("parties") or []) + str((x.get("buyer") or {}).get("name")))]
        print(f"  {params}: HTTP {r.status_code} releases={len(rels)} naming-borough={len(local)} next={bool((d.get('links') or {}).get('next'))} uri={d.get('uri')}")
        __import__("time").sleep(3)


if __name__ == "__main__":
    for fn in (contracts_finder_full,):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {fn.__name__} crashed: {type(exc).__name__}: {exc}"[:400])
