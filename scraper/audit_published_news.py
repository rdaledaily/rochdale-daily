"""Set honest newsroom metrics from the final article feed and generated pages.

Usage: python scraper/audit_published_news.py
The scraper's drafts are NOT publications. Count a newly generated item only
when it survives final editorial gating AND has a generated public article page.
This script is safe to rerun during conflict-recovery rebuilds.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

STATUS=Path("scraper_status.json")
FEED=Path("articles.json")
PAGES=Path("articles")


def source_identity(url: str) -> str:
    try:
        u=urlsplit(str(url or "").strip())
        # Keep hash fragments on live records: distinct alerts share a source URL.
        return urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path.rstrip("/"),u.query,u.fragment))
    except ValueError:
        return ""


def audit(status: dict, records: list, pages: Path) -> dict:
    drafts=status.get("drafted_articles") or []
    if not isinstance(drafts,list):
        drafts=[]
    by_slug={str(x.get("slug") or ""): x for x in records if isinstance(x,dict)}
    by_source={}
    for row in records:
        if not isinstance(row,dict):
            continue
        for link in [row.get("source_url"), *(row.get("source_urls") or [])]:
            identity=source_identity(link)
            if identity:
                by_source[identity]=row
    passed=[]
    missing=[]
    seen=set()
    for item in drafts:
        if not isinstance(item,dict):
            continue
        slug=str(item.get("slug") or "")
        src=source_identity(item.get("source_url") or "")
        row=by_slug.get(slug) or by_source.get(src)
        actual_slug=str((row or {}).get("slug") or "")
        if row and actual_slug and (pages / (actual_slug+".html")).is_file() and actual_slug not in seen:
            passed.append(actual_slug)
            seen.add(actual_slug)
        else:
            # Several drafts can legitimately merge into a single published
            # story, but the extras are not separate published articles.
            missing.append({"slug":slug,"source_url":str(item.get("source_url") or ""),
                            "merged_into_existing_page": actual_slug in seen})
    status["draft_rewrites_created"]=len(drafts)
    status["new_articles"]=len(passed)
    status["published_after_editorial_gate"]=len(passed)
    status["published_new_slugs"]=passed
    status["drafts_not_published"]=len(missing)
    # No unsupported assertion that a technically successful rewrite is public.
    status["publication_health"]="ready" if not missing else ("blocked" if not passed else "partial")
    status["publication_audit"]="counted only in final feed AND generated article pages"
    status["live_articles"]=len(records)
    return status


def main() -> None:
    if not STATUS.exists() or not FEED.exists():
        raise SystemExit("Missing scraper status or articles feed")
    status=json.loads(STATUS.read_text(encoding="utf-8"))
    feed=json.loads(FEED.read_text(encoding="utf-8"))
    if not isinstance(status,dict) or not isinstance(feed,list):
        raise SystemExit("Invalid status or articles feed")
    audit(status,feed,PAGES)
    STATUS.write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(
        "PUBLICATION AUDIT: "+
        f"{status['draft_rewrites_created']} rewritten drafts, "+
        f"{status['new_articles']} actually published, "+
        f"{status['drafts_not_published']} not in public article feed/pages"
    )


if __name__=="__main__":
    main()
