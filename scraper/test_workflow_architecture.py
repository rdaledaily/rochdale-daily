from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def main() -> int:
    # Only workflows that render/push the complete public newspaper share the
    # single site-writer lane. Scheduled/manual editions serialize normally,
    # while a code/config push supersedes an obsolete render already in flight.
    for name in ("scrape-fast.yml", "scrape-kick.yml", "publish.yml"):
        assert "group: rd-site-writer" in text(name), name
    assert "cancel-in-progress: true" in text("scrape-kick.yml")
    assert "cancel-in-progress: false" in text("scrape-fast.yml")
    assert "cancel-in-progress: false" in text("publish.yml")

    expected_source_lanes = {
        "council-minutes.yml": "rd-council-source",
        "democracy.yml": "rd-democracy-source",
        "publish-pending-manual.yml": "rd-manual-queue",
        "preserve-article-archive.yml": "rd-archive-ledger",
        "scrub-personal-name.yml": "rd-privacy-scrub",
        "article-image-integrity.yml": "rd-image-maintenance",
        "clean-public-article-content.yml": "rd-content-hygiene",
        "dual-agent-bridge.yml": "rd-dual-agent-bridge",
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
    # and always deploy latest main even when the story was already blocklisted.
    takedown = text("remove-story.yml")
    assert "group: rd-emergency-takedown" in takedown
    assert "gh workflow run deploy-pages.yml --ref main" in takedown
    assert "git merge" not in takedown
    deploy_step = takedown.split("- name: Deploy takedown immediately", 1)[1]
    assert "if: steps.commit" not in deploy_step

    # The old empty polling/scheduled maintenance writers are gone.
    assert "schedule:" not in text("publish-pending-manual.yml")
    assert "schedule:" not in text("article-image-integrity.yml")
    assert "schedule:" not in text("archive-refresh.yml")

    # Production permits source photos only through the runtime allowlist policy,
    # rather than globally disabling source-image discovery.
    for name in ("scrape-fast.yml", "scrape-kick.yml", "publish.yml"):
        assert 'USE_SOURCE_IMAGES: "true"' in text(name), name
    for name in ("scrape-fast.yml", "scrape-kick.yml"):
        assert "python scraper/run_newsroom_policy.py" in text(name), name

    # The dual-agent bridge is deliberately comment only and cannot mutate the
    # repository or bypass normal review lanes.
    bridge = text("dual-agent-bridge.yml")
    assert "contents: read" in bridge
    assert "issues: write" in bridge
    assert "pull-requests: read" in bridge
    assert "persist-credentials: false" in bridge
    assert "contents: write" not in bridge
    assert "pull-requests: write" not in bridge
    assert "git push" not in bridge
    assert "gh pr merge" not in bridge

    print("Workflow architecture checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
