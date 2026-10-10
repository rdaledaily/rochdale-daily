#!/usr/bin/env python3
"""Prepare evidence for new automated drafts before the publication gate.

Fail closed on unverified claims. Capture source material only for recent
automated drafts, never rewrite source copy or mint a verification attestation.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from claim_evidence import approved_evidence_source, is_primary, evidence_issues
from source_evidence_capture import prepare
from independent_fact_review import verify
from structured_official_notices import verified_notice

CUTOFF=datetime.fromisoformat("2026-10-09T16:00:00+00:00")
def recent(value):
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d.tzinfo is not None and d>=CUTOFF
    except (TypeError,ValueError):
        return False

def enrich(rows, capture=prepare, reviewer=verify):
    """Capture once, but retry unverified claims against already captured text.

    The previous implementation skipped every article with evidence_sources,
    leaving an unverified draft permanently unable to publish on subsequent runs.
    """
    updated=0
    for row in rows:
        if not isinstance(row,dict) or row.get("manual_article") or row.get("sponsored"):
            continue
        # Newly rewritten drafts do not have ingested_at until article_gate.
        # Set it here, before evidence capture, only on recent automated drafts.
        if not recent(row.get("first_published_at") or row.get("published_at")):
            continue
        if not row.get("ingested_at"):
            row["ingested_at"]=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
            updated+=1
        if not recent(row.get("ingested_at")):
            continue
        if not evidence_issues(row):
            continue
        if not row.get("evidence_sources"):
            if not approved_evidence_source(row.get("source_url")):
                row["verification_reasons"]=["Original URL is not an approved attributable source; editorial review required"]
                updated+=1
                continue
            try:
                captured=capture(row)
                row["evidence_sources"]=captured["evidence_sources"]
                row["evidence_candidates"]=captured.get("evidence_candidates",{})
            except Exception as exc:
                row["evidence_capture_error"]=type(exc).__name__
                row["verification_reasons"]=["Approved source could not be captured"]
                updated+=1
                continue
        # Council's structured roadworks register has explicit facts for a
        # narrower, deterministic evidence-backed notice. Correct unsupported
        # generic AI prose rather than rejecting a valid primary source solely
        # because the AI invented context or changed its evidence quotations.
        if verified_notice(row):
            updated+=1
            continue
        verdict=reviewer(row)
        row["verification_reasons"]=verdict.get("reasons",[])
        if verdict.get("approved"):
            row["verified_claims"]=[{"claim":c["claim"],"source_url":c["source_url"],"supporting_excerpt":c["supporting_excerpt"]} for c in verdict["claims"]]
            row["source_review_verified"]=True
            # Only verified official material may receive a primary-source label.
            row["primary_source_verified"]=all(is_primary(x.get("url")) for x in row["evidence_sources"])
            row["verification_source_type"]="primary" if row["primary_source_verified"] else "attributed-publisher"
        else:
            row["source_review_verified"]=False
            row["primary_source_verified"]=False
        updated+=1
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
    print(f"Prepared or reviewed {count} recent articles; unverified articles fail closed.")

if __name__=="__main__":main()
