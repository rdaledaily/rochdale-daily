#!/usr/bin/env python3
"""Store rejected drafts outside public site output.

No sensitive story contents are committed: use a private runtime directory
(RD_REVIEW_DIR) excluded from Git. Atomic replace, restricted permissions.
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone

def record(article, reasons):
    target=Path(os.environ.get("RD_REVIEW_DIR","/tmp/rochdale-daily-editorial-review"))
    target.mkdir(mode=0o700,parents=True,exist_ok=True)
    slug=str(article.get("slug") or article.get("id") or "unknown")
    import re
    slug=re.sub(r"[^a-zA-Z0-9_-]","-",slug)[:100]
    path=target/(slug+".json")
    data={"status":"needs_review","recorded_at":datetime.now(timezone.utc).isoformat(),
          "reasons":list(reasons),"article":article}
    temp=target/(slug+".tmp")
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
    os.replace(temp,path)
    return str(path)
