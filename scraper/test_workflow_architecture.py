from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def main() -> int:
    # Automated full-site newsroom writers share one queue so two scraper
    # snapshots cannot push competing editions at once.
    for name in ("scrape-fast.yml", "scrape-kick.yml"):
        assert "group: rd-site-writer" in text(name), name
        assert "cancel-in-progress: false" in text(name), name

    # Manual/editorial publication has its own short lane. It starts from latest
    # main and performs bounded race-safe rebuilds, so a slow automated scrape
    # must never hold editor-written stories off the public site. The lane is
    # latest-wins (cancel-in-progress: true): every run publishes the whole
    # manual_articles.d set, so a superseded run loses nothing and a wedged one
    # cannot block the editor's next story.
    publish = text("publish.yml")
    assert "group: rd-manual-publisher" in publish
    assert "group: rd-site-writer" not in publish
    assert "cancel-in-progress: true" in publish
    assert "frontpage_manual_publish.py" in publish
    assert "verify_manual_publication.py" in publish

    expected_source_lanes = {
        "council-minutes.yml": "rd-council-source",
        "publish-pending-manual.yml": "rd-manual-queue",
        "scrub-personal-name.yml": "rd-privacy-scrub",
    }
    for name, group in expected_source_lanes.items():
        assert f"group: {group}" in text(name), name

    # Council minutes is a source-data producer; only the canonical publisher
    # may own public index/ward regeneration.
    council = text("council-minutes.yml")
    assert "generate_ward_pages.py" not in council
    assert "index.html" not in council
    assert "gh workflow run publish.yml" in council

    # Emergency removals have a separate priority lane, never merge stale pages,
    # and always deploy latest main even when the story was already blocklisted.
    takedown = text("remove-story.yml")
    assert "group: rd-emergency-takedown" in takedown
    assert "gh workflow run deploy-pages.yml --ref main" in takedown
    assert "git merge" not in takedown
    deploy_step = takedown.split("- name: Deploy takedown immediately", 1)[1]
    assert "if: steps.commit" not in deploy_step

    # Manual queue has no polling schedule. One-off diagnostics and repair
    # workflows removed during the Actions cleanup must stay removed rather than
    # creeping back in as permanent workflow entries.
    assert "schedule:" not in text("publish-pending-manual.yml")
    retired = {
        "archive-refresh.yml",
        "article-image-integrity.yml",
        "clean-public-article-content.yml",
        "democracy.yml",
        "measure-street-reports.yml",
        "moderngov-diagnostic.yml",
        "preserve-article-archive.yml",
        "restyle-archive.yml",
        "run-ledger.yml",
        "strip-title-emojis.yml",
        "ward-candidates.yml",
    }
    for name in retired:
        assert not (WORKFLOWS / name).exists(), name

    # Automated collection permits source photos through the runtime allowlist
    # policy. The manual publisher does not discover sources and therefore does
    # not need this scraper-only environment switch.
    for name in ("scrape-fast.yml", "scrape-kick.yml"):
        assert 'USE_SOURCE_IMAGES: "true"' in text(name), name
        assert "python scraper/run_newsroom_policy.py" in text(name), name

    print("Workflow architecture checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
