#!/usr/bin/env python3
"""Prepare evidence for new automated drafts before the publication gate.

Fail closed on unverified claims. Capture source material only for recent
automated drafts, never rewrite source copy or mint a verification attestation.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from claim_evidence import is_primary, evidence_issues
from source_evidence_capture import prepare

CUTOFF=datetime.fromisoformat("2026-10-09T16:00:00+00:00")
def recent(value):
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d.tzinfo is not None and d>=CUTOFF
    except (TypeError,ValueError):
        return False

def enrich(rows, capture=prepare):
    updated=0
    for row in rows:
        if not isinstance(row,dict) or row.get("manual_article") or row.get("sponsored"):
            continue
        if not (recent(row.get("first_published_at") or row.get("published_at")) and recent(row.get("ingested_at"))):
            continue
        if row.get("evidence_sources") or not is_primary(row.get("source_url")):
            continue
        try:
            captured=capture(row)
            row["evidence_sources"]=captured["evidence_sources"]
            row["evidence_candidates"]=captured["evidence_candidates"]
            row["primary_source_verified"]=False
            updated+=1
        except Exception as exc:
            # Fail closed later; do not expose arbitrary source response data.
            row["evidence_capture_error"]=type(exc).__name__
    return updated

def main():
    path=Path("articles.json")
    rows=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows,list):
        raise ValueError("articles.json must be a list")
    count=enrich(rows)
    if count:
        temp=path.with_suffix(".json.evidence-tmp")
        temp.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        temp.replace(path)
    print(f"Prepared source evidence for {count} recent articles; claims still require verification.")

if __name__=="__main__":main()
