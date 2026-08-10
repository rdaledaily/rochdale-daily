#!/usr/bin/env python3
"""Generate a permanent searchable public archive from retained article HTML pages.

The homepage/latest feeds are intentionally freshness-led. This archive is not.
Every published article page that still exists under articles/ is indexed here,
so stories remain findable after they age out of the live feed.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

PAGES_DIR = Path("articles")
INDEX_PATH = Path("archive-index.json")
ARCHIVE_PATH = Path("archive.html")


def _meta(source: str, prop: str) -> str:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)',
        rf'<meta[^>]+name=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)',
    ]
    for pattern in patterns:
        m = re.search(pattern, source, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def _text(source: str, pattern: str) -> str:
    m = re.search(pattern, source, re.I | re.S)
    if not m:
        return ""
    value = re.sub(r"<[^>]+>", " ", m.group(1))
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def read_article(path: Path) -> dict[str, str] | None:
    source = path.read_text(encoding="utf-8", errors="ignore")
    title = _meta(source, "og:title") or _text(source, r"<h1[^>]*>(.*?)</h1>") or _text(source, r"<title>(.*?)</title>")
    title = re.sub(r"\s*[|–-]\s*Rochdale Daily\s*$", "", title, flags=re.I).strip()
    if not title:
        return None
    published = _meta(source, "article:published_time") or _meta(source, "date")
    section = _meta(source, "article:section") or _text(source, r'<span[^>]+class=["\'][^"\']*story-kicker[^"\']*["\'][^>]*>(.*?)</span>')
    description = _meta(source, "description") or _meta(source, "og:description")
    return {
        "title": title,
        "url": f"/articles/{path.name}",
        "slug": path.stem,
        "published_at": published,
        "category": section,
        "description": description,
    }


def build_index() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if PAGES_DIR.exists():
        for path in PAGES_DIR.glob("*.html"):
            item = read_article(path)
            if item:
                records.append(item)
    records.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return records


def render(records: list[dict[str, str]]) -> str:
    count = len(records)
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>News Archive | Rochdale Daily</title>
<meta name="description" content="Search the permanent Rochdale Daily news archive.">
<link rel="stylesheet" href="/assets/css/site.css">
<style>
.archive-wrap{{max-width:1050px;margin:0 auto;padding:24px 18px 60px}}
.archive-head{{margin:18px 0 22px}}
.archive-search{{width:100%;box-sizing:border-box;font:inherit;font-size:18px;padding:14px 16px;border:2px solid #111;border-radius:4px;background:#fff}}
.archive-meta{{margin:10px 0 24px;color:#555}}
.archive-results{{display:grid;gap:12px}}
.archive-item{{border-top:1px solid #ddd;padding:16px 0}}
.archive-item a{{font-size:20px;font-weight:800;color:#111;text-decoration:none}}
.archive-item a:hover{{text-decoration:underline}}
.archive-item .meta{{font-size:13px;text-transform:uppercase;letter-spacing:.04em;margin:5px 0;color:#666}}
.archive-item p{{margin:6px 0 0;color:#333}}
.archive-empty{{padding:30px 0;font-weight:700}}
</style>
</head>
<body>
<header class="site-header"><div class="archive-wrap" style="padding-top:12px;padding-bottom:12px"><a class="brand" href="/" aria-label="Rochdale Daily home"><img class="brand-logo" src="/assets/img/logo.png" alt="Rochdale Daily"></a></div></header>
<main class="archive-wrap">
<div class="archive-head"><h1>Rochdale Daily archive</h1><p>Stories leave the latest-news feed as they age, but published articles remain here permanently unless they are formally removed or corrected.</p></div>
<label for="archive-search"><strong>Search every published story</strong></label>
<input id="archive-search" class="archive-search" type="search" placeholder="Search a person, place, business, road, club or headline…" autocomplete="off">
<div class="archive-meta"><span id="archive-count">{count:,}</span> archived stories</div>
<div id="archive-results" class="archive-results"></div>
</main>
<script>
const DATA={json.dumps(records, ensure_ascii=False)};
const input=document.getElementById('archive-search');
const results=document.getElementById('archive-results');
const count=document.getElementById('archive-count');
function esc(s){{return String(s||'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c]));}}
function dateLabel(v){{if(!v)return ''; const d=new Date(v); return isNaN(d)?v:d.toLocaleDateString('en-GB',{{day:'numeric',month:'long',year:'numeric'}});}}
function render(){{
 const q=input.value.trim().toLowerCase();
 const words=q.split(/\s+/).filter(Boolean);
 const found=DATA.filter(x=>!words.length||words.every(w=>(x.title+' '+x.description+' '+x.category+' '+x.slug).toLowerCase().includes(w)));
 count.textContent=found.length.toLocaleString('en-GB');
 if(!found.length){{results.innerHTML='<div class="archive-empty">No archived stories match that search.</div>';return;}}
 results.innerHTML=found.slice(0,250).map(x=>`<article class="archive-item"><a href="${{x.url}}">${{esc(x.title)}}</a><div class="meta">${{esc(x.category||'News')}}${{x.published_at?' · '+esc(dateLabel(x.published_at)):''}}</div>${{x.description?'<p>'+esc(x.description)+'</p>':''}}</article>`).join('');
}}
input.addEventListener('input',render); render();
</script>
</body>
</html>'''


def main() -> int:
    records = build_index()
    INDEX_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ARCHIVE_PATH.write_text(render(records), encoding="utf-8")
    print(f"Archive indexed {len(records)} retained article pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
