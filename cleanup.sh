#!/usr/bin/env bash
# Rochdale Daily repo cleanup — removes dead code, one-shot workflows and junk.
#
# Run from the repository root:   bash cleanup.sh
# Review with `git status` and `git diff --cached`, then commit and push.
#
# What this does NOT touch (verified live in the pipeline):
#   frontpage_pipeline.py + test_frontpage_pipeline.py  (called by generate_pages.py)
#   locations.py, location_discovery.py                 (used by scraper / search_queries)
#   source_presentation.py, house_style.py, editorial_upgrade.py
#   scrape.yml                                          (the real scheduled workflow)

set -euo pipefail

echo "== 1. Dead pipeline modules (only reachable from deleted one-shot workflows) =="
git rm -f \
  scraper/elevate_existing_articles.py \
  scraper/apply_subtle_source_attribution.py \
  scraper/source_grounded_copydesk.py \
  scraper/repair_cross_story_merges.py \
  scraper/additional_sources.py

echo "== 2. One-shot 'install X' workflows (all workflow_dispatch, all done or superseded) =="
git rm -f \
  ".github/workflows/apply-rochdale-upgrade-fixed.yml" \
  ".github/workflows/apply-rochdale-upgrade.yml" \
  ".github/workflows/apply-subtle-source-attribution.yml" \
  ".github/workflows/elevate-rochdale-editorial-tone-V5.yml" \
  ".github/workflows/fix-over-strict-rewrite-rejection.yml" \
  ".github/workflows/fix_story_merging.yml" \
  ".github/workflows/install-longform-multisource-articles.yml" \
  ".github/workflows/install-quality-journalism-reader-features-V3.yml" \
  ".github/workflows/install-source-grounded-lexical-precision-V8.yml" \
  ".github/workflows/publish-elevated-editorial-tone-V6.yml" \
  ".github/workflows/repair-15-minute-scraper-query-volume-V2.yml" \
  ".github/workflows/repair-15-minute-scraper-query-volume.yml" \
  ".github/workflows/repair-200-word-publication-floor-V4.yml" \
  ".github/workflows/repair-rochdale-article-rewriting.yml" \
  ".github/workflows/stop-unrelated-story-merging-V11.yml" \
  ".github/workflows/stop-unrelated-story-merging-V12.yml" \
  ".github/workflows/stop-unrelated-story-merging-V13 (2).yml"

echo "== 3. Junk and stray files =="
git rm -rf --ignore-unmatch scraper/__pycache__
git rm -f  --ignore-unmatch scraper/_pycache__
git rm -f  --ignore-unmatch scraper/scraper_status
git rm -f  --ignore-unmatch "rochdale-daily-site(3).zip"

echo "== 4. session.json (Facebook login session — must not be in the repo) =="
git rm -f --ignore-unmatch scraper/session.json

echo "== 5. .gitignore =="
# Expects the .gitignore file delivered alongside this script at repo root.
git add .gitignore

echo
echo "Staged. Review with: git status && git diff --cached --stat"
echo "Then: git commit -m 'Remove dead modules, one-shot workflows and junk; add .gitignore' && git push"

# ============================================================================
# STEP 6 — REQUIRED FOLLOW-UP, done manually AFTER the commit above:
# purge session.json from the ENTIRE git history.
#
# The commit above removes the file from the current tree only. All ~10 months
# of history still contain the full Facebook session cookies and remain
# clonable by anyone. Only do this AFTER you have:
#   (a) logged out all Facebook sessions and changed the password, and
#   (b) merged/closed any open branches or PRs (history rewrite invalidates them).
#
#   pip install git-filter-repo
#   git filter-repo --invert-paths --path scraper/session.json --force
#   git remote add origin https://github.com/rdaledaily/rochdale-daily.git
#   git push origin --force --all
#
# (git filter-repo removes the remote as a safety measure; re-add it before
# pushing. Anyone else with a clone must re-clone afterwards.)
#
# Verified safe to delete: the live Facebook Events collector launches an
# anonymous Playwright context and never reads this file. Nothing in the
# scheduled pipeline references it. It is a leftover from an earlier
# logged-in scraping experiment.
# ============================================================================
