"""Restore article pages that were wrongly deleted from articles/.

Between the site launch and July 2026, frontpage_pipeline deleted every
article page whose slug fell out of the live articles.json, so roughly half
of everything ever published was removed (median lifespan 4.3 hours). Every
deleted page still exists in git history. This script restores the most
recent version of each deleted page, except:

  * pages that already exist in articles/ (never overwritten),
  * pages whose slug is blocklisted in story_blocklist.json,
  * pages whose title matches a blocklist title pattern,
  * job adverts and classified listings (the retroactive junk filters that
    deleted these were correct, so they stay deleted).

Restored pages are static archive: they are NOT re-added to articles.json,
so they never re-enter the homepage or the rewrite pipeline. The updated
generate_pages.py automatically includes every on-disk page in sitemap.xml
on the next scheduled run, so restored URLs become indexable again without
any further action.

Run from the repository root:  python scraper/restore_archive.py
Preview without writing:       python scraper/restore_archive.py --dry-run

The script prints a per-page decision log and writes restore_report.csv
next to articles/ so every decision is auditable. Pages flagged SIBLING in
the report are old-slug versions of stories that were later republished
under a new slug (headline drift); they are restored so old links keep
working, but you may prune any you consider redundant.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from html import unescape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTICLES_DIR = REPO_ROOT / "articles"
BLOCKLIST_PATH = REPO_ROOT / "story_blocklist.json"
REPORT_PATH = REPO_ROOT / "restore_report.csv"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from selection_policy import is_classified_listing_post, is_job_or_career_post  # noqa: E402

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
DESCRIPTION_RE = re.compile(
    r'<meta\s+name="description"\s+content="([^"]*)"', re.I
)


def run_git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def load_blocklist() -> dict[str, list[str]]:
    try:
        payload = json.loads(BLOCKLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"slugs": [], "title_patterns": [], "source_urls": []}
    return {
        "slugs": [str(v).lower() for v in payload.get("slugs", []) if v],
        "title_patterns": [str(v).lower() for v in payload.get("title_patterns", []) if v],
    }


def deleted_pages() -> dict[str, str]:
    """Map each deleted articles/*.html path to its most recent deleting commit."""
    log = run_git(
        "log", "--pretty=%H", "--diff-filter=D", "--name-only", "--", "articles/"
    ).splitlines()
    deletions: dict[str, str] = {}
    current = ""
    for line in log:
        line = line.strip()
        if re.fullmatch(r"[0-9a-f]{40}", line):
            current = line
        elif line.startswith("articles/") and line.endswith(".html"):
            # git log is newest-first; keep the FIRST (most recent) deletion.
            deletions.setdefault(line, current)
    return deletions


def page_from_history(commit: str, path: str) -> str:
    return run_git("show", f"{commit}^:{path}")


def extract_title(page_html: str) -> str:
    match = TITLE_RE.search(page_html)
    title = unescape(match.group(1)).strip() if match else ""
    # Page titles carry the site suffix: "Headline | Rochdale Daily".
    return re.sub(r"\s*\|\s*Rochdale Daily\s*$", "", title, flags=re.I)


def extract_description(page_html: str) -> str:
    match = DESCRIPTION_RE.search(page_html)
    return unescape(match.group(1)).strip() if match else ""


def slug_tokens(slug: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", slug.lower()))


def likely_sibling(slug: str, current_slugs: list[str]) -> str:
    tokens = slug_tokens(slug)
    best, best_score = "", 0.0
    for other in current_slugs:
        other_tokens = slug_tokens(other)
        union = tokens | other_tokens
        score = len(tokens & other_tokens) / len(union) if union else 0.0
        if score > best_score:
            best, best_score = other, score
    return best if best_score >= 0.5 else ""


def main(dry_run: bool = False) -> int:
    blocklist = load_blocklist()
    blocked_slugs = set(blocklist["slugs"])
    title_patterns = blocklist["title_patterns"]
    deletions = deleted_pages()
    current_slugs = [p.stem for p in ARTICLES_DIR.glob("*.html")]

    rows: list[dict[str, str]] = []
    restored = 0
    for path, commit in sorted(deletions.items()):
        slug = Path(path).stem
        decision, detail = "", ""
        if (ARTICLES_DIR / f"{slug}.html").exists():
            decision = "skip-exists"
        elif slug.lower() in blocked_slugs:
            decision = "skip-blocklisted-slug"
        else:
            try:
                page_html = page_from_history(commit, path)
            except subprocess.CalledProcessError:
                decision, detail = "skip-unrecoverable", "not present in parent commit"
                rows.append({"slug": slug, "decision": decision, "detail": detail})
                continue
            title = extract_title(page_html)
            description = extract_description(page_html)
            text = f"{title} {description}"
            if any(pattern in title.lower() for pattern in title_patterns):
                decision = "skip-blocklisted-title"
            elif is_job_or_career_post(text) or is_classified_listing_post(text):
                decision, detail = "skip-junk", title[:80]
            else:
                sibling = likely_sibling(slug, current_slugs)
                decision = "restore"
                detail = f"SIBLING:{sibling}" if sibling else ""
                if not dry_run:
                    (ARTICLES_DIR / f"{slug}.html").write_text(
                        page_html, encoding="utf-8"
                    )
                restored += 1
        rows.append({"slug": slug, "decision": decision, "detail": detail})
        print(f"{decision:24s} {slug}" + (f"  [{detail}]" if detail else ""))

    if not dry_run:
        with REPORT_PATH.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["slug", "decision", "detail"])
            writer.writeheader()
            writer.writerows(rows)

    mode = "DRY RUN — nothing written" if dry_run else f"report: {REPORT_PATH.name}"
    print(
        f"\n{restored} page(s) restored, "
        f"{sum(1 for r in rows if r['decision'].startswith('skip'))} skipped "
        f"({mode})."
    )
    print(
        "Commit the restored pages; the next scheduled run's sitemap will "
        "include them automatically."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(dry_run="--dry-run" in sys.argv[1:]))
