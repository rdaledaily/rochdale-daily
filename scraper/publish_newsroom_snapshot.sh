#!/usr/bin/env bash
set -euo pipefail

branch="${GITHUB_REF_NAME:-main}"
message="${COMMIT_MESSAGE:-Update Rochdale Daily newsroom}"

mark_published() {
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "published=true" >> "${GITHUB_OUTPUT}"
  fi
}

git_push() {
  timeout --signal=TERM 90s git push origin "HEAD:${branch}"
}

git_fetch() {
  timeout --signal=TERM 60s git fetch origin "${branch}"
}

stage_newsroom() {
  git add articles.json manual_articles.json manual_articles.d slow_domains.json scraper_status.json scraper_health.json event_dates.json \
    newsroom_candidates.json google_news_resolution_report.json google_news_resolutions.json live_source_state.json \
    image_coverage_report.json image_repair_report.json commons_image_repair_report.json cards_image_policy_report.json assets/img/cards \
    articles sitemap.xml news-sitemap.xml image-sitemap.xml wards/ ward_areas.json council_votes.json councillor_photos.json weather.json \
    archive.html search.html archive-index.json rss.xml index.html 2>/dev/null || true
}

finalise_cards_policy() {
  python scraper/enforce_cards_only_images.py --articles articles.json
  python scraper/compact_live_updates.py --articles articles.json
  python scraper/generate_ward_pages.py
  python scraper/generate_newspaper_pages.py
  python scraper/enforce_frontpage_freshness.py
  python scraper/frontpage_source_quality.py
  python scraper/enforce_live_homepage_window.py
  python scraper/ensure_manual_frontpage.py
  python scraper/generate_news_sitemap.py
  python scraper/generate_archive.py
  cp archive.html search.html
  python scraper/update_homepage_static_latest.py
  python scraper/update_homepage_weekly_news.py
  python scraper/sync_homepage_top_story.py
  python scraper/homepage_discovery_metadata.py
  python scraper/generate_rss.py
  python scraper/generate_image_sitemap.py
  python scraper/enforce_cards_only_images.py --articles articles.json --check
}

# Race recovery must be local and bounded. The expensive network image-repair
# passes already ran before the first commit; repeating them after every push
# race is what allowed one writer to occupy the queue for tens of minutes.
# Restore the first build's card assets, merge with latest main, inject any
# manual stories added while this run was working, and regenerate derived pages.
rebuild_from_merged_feed() {
  python -m json.tool articles.json > /dev/null
  python scraper/frontpage_manual_publish.py
  python scraper/article_gate.py articles.json
  python scraper/content_hygiene.py --fix
  python scraper/enforce_cards_only_images.py --articles articles.json
  python scraper/compact_live_updates.py --articles articles.json
  python scraper/repair_merged_bodies.py
  python scraper/councillor_photos.py
  python scraper/patch_democracy_portraits.py
  python scraper/generate_ward_pages.py
  python scraper/generate_newspaper_pages.py
  python scraper/enforce_frontpage_freshness.py
  python scraper/frontpage_source_quality.py
  PYTHONPATH=scraper python scraper/test_frontpage_source_quality.py
  python scraper/enforce_live_homepage_window.py
  python scraper/ensure_manual_frontpage.py
  python scraper/generate_news_sitemap.py
  python scraper/generate_archive.py
  cp archive.html search.html
  python scraper/update_homepage_static_latest.py
  python scraper/update_homepage_weekly_news.py
  python scraper/sync_homepage_top_story.py
  python scraper/homepage_discovery_metadata.py
  python scraper/generate_rss.py
  python scraper/generate_image_sitemap.py
  python scraper/content_hygiene.py --fix
  python scraper/content_hygiene.py
  python scraper/enforce_cards_only_images.py --articles articles.json --check
  python scraper/verify_manual_publication.py
  python scraper/check_scraper_health.py
}

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

finalise_cards_policy
stage_newsroom
if git diff --cached --quiet; then
  echo "Pipeline completed with no file changes."
  exit 0
fi

git commit -m "${message}"
local_snapshot_commit="$(git rev-parse HEAD)"
if git_push; then
  mark_published
  exit 0
fi

recovery_dir="$(mktemp -d)"
trap 'rm -rf "${recovery_dir}"' EXIT

git show "${local_snapshot_commit}:articles.json" > "${recovery_dir}/local_articles.json"
for optional in weather.json event_dates.json scraper_status.json newsroom_candidates.json live_source_state.json google_news_resolutions.json; do
  if git cat-file -e "${local_snapshot_commit}:${optional}" 2>/dev/null; then
    git show "${local_snapshot_commit}:${optional}" > "${recovery_dir}/${optional}"
  fi
done

for attempt in 1 2; do
  echo "main moved during newsroom run; rebuilding on latest main (recovery ${attempt}/2)."
  if ! git_fetch; then
    echo "Timed out or failed fetching latest main during recovery ${attempt}/2." >&2
    continue
  fi
  git reset --hard "origin/${branch}"
  git clean -fd

  # Bring forward cards produced by the first completed build. Latest main keeps
  # its own cards too; checkout overlays only paths that existed in this run.
  git checkout "${local_snapshot_commit}" -- assets/img/cards 2>/dev/null || true

  cp articles.json "${recovery_dir}/remote_articles.json"
  python scraper/merge_feeds.py "${recovery_dir}/remote_articles.json" "${recovery_dir}/local_articles.json" articles.json
  for optional in weather.json event_dates.json scraper_status.json newsroom_candidates.json live_source_state.json google_news_resolutions.json; do
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
  local_snapshot_commit="$(git rev-parse HEAD)"
  if git_push; then
    mark_published
    exit 0
  fi

  git show "${local_snapshot_commit}:articles.json" > "${recovery_dir}/local_articles.json"
done

echo "Could not publish after two bounded race-safe rebuild attempts." >&2
exit 1
