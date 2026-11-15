#!/usr/bin/env python3
"""One-off read-only search of Rochdale Borough Council's published spending
over £500 (data.gov.uk dataset b7e5bb16...). Downloads every monthly file,
CSV where published, PDF otherwise, and records every row whose text matches
a search term. Also counts redacted supplier rows in landscaping-type
spending, because payments to individuals and sole traders are often
withheld from the published data."""
import csv, io, json, re, subprocess, sys, time
import requests

DATASET = "b7e5bb16-dc43-44d3-979d-529fd7f5af13"
TERMS = [t.strip() for t in sys.argv[1].split(",")] if len(sys.argv) > 1 else []
PATTERN = re.compile("|".join(re.escape(t) for t in TERMS), re.I)
LANDSCAPE = re.compile(r"TREES|SHRUBS|PLANTS|GROUNDS|LANDSCAP|GARDEN|HORTICULT|BLOOM|FLORAL", re.I)
REDACTED = re.compile(r"REDACT|PERSONAL DATA|WITHHELD", re.I)
UA = {"User-Agent": "Rochdale Daily newsroom research (news@rochdaledaily.co.uk)"}

pkg = requests.get(f"https://www.data.gov.uk/api/action/package_show?id={DATASET}", headers=UA, timeout=60).json()["result"]
by_month: dict[str, dict[str, str]] = {}
for res in pkg["resources"]:
    url = (res.get("url") or "").replace("htts://", "https://").replace("http://", "https://")
    fmt = (res.get("format") or url.rsplit(".", 1)[-1]).lower()
    name = res.get("name") or res.get("description") or url
    by_month.setdefault(name.replace(" (csv)", "").replace(" (pdf)", "").strip(), {})[fmt] = url

out = {"terms": TERMS, "files_total": 0, "files_read": 0, "failed": [], "matches": [],
       "redacted_landscape_rows": 0, "redacted_landscape_total": 0.0, "landscape_examples": []}
for month, files in sorted(by_month.items()):
    url = files.get("csv") or files.get("pdf")
    if not url:
        continue
    out["files_total"] += 1
    try:
        r = requests.get(url, headers=UA, timeout=120)
        r.raise_for_status()
    except Exception as exc:
        out["failed"].append({"month": month, "url": url, "error": str(exc)[:160]})
        continue
    if url.lower().endswith(".pdf"):
        open("/tmp/f.pdf", "wb").write(r.content)
        text = subprocess.run(["pdftotext", "-layout", "/tmp/f.pdf", "-"], capture_output=True, text=True).stdout
        rows = [line for line in text.splitlines() if line.strip()]
    else:
        raw = r.content.decode("utf-8", "replace") if b"\x00" not in r.content[:200] else r.content.decode("utf-16", "replace")
        rows = [" | ".join(row) for row in csv.reader(io.StringIO(raw))]
    out["files_read"] += 1
    for row in rows:
        if TERMS and PATTERN.search(row):
            out["matches"].append({"month": month, "file": url, "row": re.sub(r"\s{2,}", "  ", row)[:400]})
        if LANDSCAPE.search(row) and REDACTED.search(row):
            out["redacted_landscape_rows"] += 1
            amounts = re.findall(r"-?£?\d[\d,]*\.\d{2}", row)
            if amounts:
                try:
                    out["redacted_landscape_total"] += float(amounts[0].replace("£", "").replace(",", ""))
                except ValueError:
                    pass
            if len(out["landscape_examples"]) < 40:
                out["landscape_examples"].append({"month": month, "row": re.sub(r"\s{2,}", "  ", row)[:300]})
    time.sleep(0.5)

json.dump(out, open("spend_search.json", "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k not in ("matches", "landscape_examples")}, indent=1))
print(f"matches: {len(out['matches'])}")
