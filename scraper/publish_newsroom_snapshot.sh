#!/usr/bin/env bash
set -euo pipefail

branch="${GITHUB_REF_NAME:-main}"
message="${COMMIT_MESSAGE:-Update Rochdale Daily newsroom}"

# Scheduled fast, immediate and deep discovery workflows are serialized by the
# shared rd-fast-news-writer Actions concurrency lane before they reach this
# publisher. This script still retains full race recovery because unrelated
# editorial/manual/site-maintenance commits may legitimately move main.
#
# When a newsroom snapshot actually reaches main, expose that fact as a step
# output. Scheduled commits made with GITHUB_TOKEN do not reliably trigger a
# separate push-based Pages workflow, so callers can dispatch deployment only
# after a real publish rather than creating redundant deploy runs on no-op scans.
mark_published() {
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "published=true" >> "${GITHUB_OUTPUT}"
  fi
}

stage_newsroom() {
  git add articles.json manual_articles.json manual_articles.d slow_domains.json scraper_status.json scraper_health.json event_dates.json \
    google_news_resolution_report.json google_news_resolutions.json \
    image_coverage_report.json image_repair_report.json commons_image_repair_report.json assets/img/cards \
    articles sitemap.xml news-sitemap.xml wards/ ward_areas.json council_votes.json weather.json index.html 2>/dev/null || true
}

rebuild_from_merged_feed() {
  python -m json.tool articles.json > /dev/null
  python scraper/article_gate.py articles.json
  python scraper/content_hygiene.py --fix
  python scraper/ensure_article_images.py
  python scraper/repair_generated_article_images.py
  python scraper/repair_generated_with_commons.py
  python scraper/repair_merged_bodies.py
  python scraper/generate_ward_pages.py
  python scraper/generate_newspaper_pages.py
  # Page generation rebuilds frontpage.json, so final freshness ordering and the
  # hard live-homepage window must be asserted AFTER generation. Running these
  # only before generation allows a race-safe recovery to reintroduce a stale
  # top-three ordering even when the feed itself is healthy.
  python scraper/enforce_frontpage_freshness.py
  python scraper/enforce_live_homepage_window.py
  python scraper/generate_news_sitemap.py
  python scraper/content_hygiene.py --fix
  python scraper/content_hygiene.py
  python scraper/check_scraper_health.py
}

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

stage_newsroom
if git diff --cached --quiet; then
  echo "Pipeline completed with no file changes."
  exit 0
fi

git commit -m "${message}"
if git push origin "HEAD:${branch}"; then
  mark_published
  exit 0
fi

# Never rebase independently generated newspaper snapshots. If main moved while
# this run was working, preserve the canonical article feed, reset to the new
# head, merge article records deliberately, and regenerate every derived page.
# This turns a repository race into a deterministic rebuild instead of dozens
# of JSON/HTML merge conflicts.
#
# scraper_status.json is part of the validated newsroom snapshot too. Preserve
# the originating run's discovery counters across recovery: resetting to a
# concurrently-written main can otherwise import another workflow's smaller
# status file and make the rebuilt snapshot fail health despite the originating
# run having already passed its live-story gate. The rebuilt articles/frontpage
# are still checked afresh below, so freshness and content safeguards remain in
# force; only the run-specific discovery counters stay attached to their run.
recovery_dir="$(mktemp -d)"
trap 'rm -rf "${recovery_dir}"' EXIT

git show HEAD:articles.json > "${recovery_dir}/local_articles.json"
for optional in weather.json event_dates.json scraper_status.json; do
  if git cat-file -e "HEAD:${optional}" 2>/dev/null; then
    git show "HEAD:${optional}" > "${recovery_dir}/${optional}"
  fi
done

for attempt in 1 2 3; do
  echo "main moved during newsroom run; rebuilding on latest main (recovery ${attempt}/3)."
  git fetch origin "${branch}"
  git reset --hard "origin/${branch}"
  git clean -fd

  cp articles.json "${recovery_dir}/remote_articles.json"
  python scraper/merge_feeds.py "${recovery_dir}/remote_articles.json" "${recovery_dir}/local_articles.json" articles.json
  for optional in weather.json event_dates.json scraper_status.json; do
    if [ -f "${recovery_dir}/${optional}" ]; then
      cp "${recovery_dir}/${optional}" "${optional}"
    fi
  done

  rebuild_from_merged_feed
  stage_newsroom
  if git diff --cached --quiet; then
    echo "Latest main already contains the recovered newsroom state."
    exit 0
  fi
  git commit -m "${message} (race-safe rebuild)"
  if git push origin "HEAD:${branch}"; then
    mark_published
    exit 0
  fi

  # Carry the now-merged feed into the next recovery attempt if main moved yet again.
  git show HEAD:articles.json > "${recovery_dir}/local_articles.json"
done

echo "Could not publish after three race-safe rebuild attempts." >&2
exit 1
