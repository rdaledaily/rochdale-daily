from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def main() -> int:
    # Only workflows that render/push the complete public newspaper share the
    # single site-writer lane. This serializes generated snapshots without
    # causing independent source-data jobs to cancel each other's pending runs.
    for name in ("scrape-fast.yml", "scrape-kick.yml", "publish.yml"):
        assert "group: rd-site-writer" in text(name), name

    expected_source_lanes = {
        "council-minutes.yml": "rd-council-source",
        "democracy.yml": "rd-democracy-source",
        "publish-pending-manual.yml": "rd-manual-queue",
        "preserve-article-archive.yml": "rd-archive-ledger",
        "scrub-personal-name.yml": "rd-privacy-scrub",
        "article-image-integrity.yml": "rd-image-maintenance",
        "clean-public-article-content.yml": "rd-content-hygiene",
    }
    for name, group in expected_source_lanes.items():
        assert f"group: {group}" in text(name), name

    # Council/democracy are source-data producers; only the canonical publisher
    # may own public index/ward regeneration.
    for name in ("council-minutes.yml", "democracy.yml"):
        body = text(name)
        assert "generate_ward_pages.py" not in body, name
        assert "index.html" not in body, name
        assert "gh workflow run publish.yml" in body, name

    # Emergency removals have a separate priority lane, never merge stale pages,
    # and explicitly deploy the scrubbed latest main.
    takedown = text("remove-story.yml")
    assert "group: rd-emergency-takedown" in takedown
    assert "gh workflow run deploy-pages.yml --ref main" in takedown
    assert "git merge" not in takedown

    # The old empty polling/scheduled maintenance writers are gone.
    assert "schedule:" not in text("publish-pending-manual.yml")
    assert "schedule:" not in text("article-image-integrity.yml")
    assert "schedule:" not in text("archive-refresh.yml")

    # Production permits only the existing whitelisted source-photo reuse logic,
    # instead of globally disabling source images.
    for name in ("scrape-fast.yml", "scrape-kick.yml", "publish.yml"):
        assert 'USE_SOURCE_IMAGES: "true"' in text(name), name

    print("Workflow architecture checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
