from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def main() -> int:
    # Every workflow that can write canonical newsroom/source state must use the
    # same serial lane. This prevents stale generated snapshots being replayed.
    for name in (
        "scrape-fast.yml",
        "scrape-kick.yml",
        "publish.yml",
        "remove-story.yml",
        "council-minutes.yml",
        "democracy.yml",
        "publish-pending-manual.yml",
        "preserve-article-archive.yml",
        "scrub-personal-name.yml",
        "article-image-integrity.yml",
        "clean-public-article-content.yml",
    ):
        assert "group: rd-site-writer" in text(name), name

    # Council/democracy are source-data producers; only the canonical publisher
    # may own public index/ward regeneration.
    for name in ("council-minutes.yml", "democracy.yml"):
        body = text(name)
        assert "generate_ward_pages.py" not in body, name
        assert "git add" not in body or "index.html" not in body, name
        assert "gh workflow run publish.yml" in body, name

    # Emergency removals must explicitly deploy the scrubbed latest main.
    takedown = text("remove-story.yml")
    assert "gh workflow run deploy-pages.yml --ref main" in takedown
    assert "git merge" not in takedown

    # The old 5-minute empty queue poll and scheduled archive/image writers are gone.
    assert "schedule:" not in text("publish-pending-manual.yml")
    assert "schedule:" not in text("article-image-integrity.yml")
    assert "schedule:" not in text("archive-refresh.yml")

    # Production now permits only explicitly whitelisted source-photo reuse,
    # instead of globally disabling source imagery.
    for name in ("scrape-fast.yml", "scrape-kick.yml", "publish.yml"):
        assert 'USE_SOURCE_IMAGES: "true"' in text(name), name

    print("Workflow architecture checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
