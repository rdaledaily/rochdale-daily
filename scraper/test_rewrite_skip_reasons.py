from __future__ import annotations

import threading

import scraper


def reset() -> None:
    scraper.REWRITE_SKIP_REASONS.clear()


def test_identical_reasons_collapse_despite_whitespace() -> None:
    reset()
    scraper.note_rewrite_skip("  quality:   body   too short ")
    scraper.note_rewrite_skip("quality: body too short")
    assert dict(scraper.REWRITE_SKIP_REASONS) == {"quality: body too short": 2}


def test_urls_are_redacted_so_reasons_group_rather_than_fragment() -> None:
    reset()
    scraper.note_rewrite_skip("model call failed for https://example.com/a?b=c")
    scraper.note_rewrite_skip("model call failed for https://other.example/x")
    assert dict(scraper.REWRITE_SKIP_REASONS) == {"model call failed for <url>": 2}


def test_empty_reasons_are_still_counted() -> None:
    reset()
    scraper.note_rewrite_skip("")
    scraper.note_rewrite_skip(None)
    assert dict(scraper.REWRITE_SKIP_REASONS) == {"unspecified": 2}


def test_long_reasons_are_capped() -> None:
    reset()
    scraper.note_rewrite_skip("x" * 500)
    key = next(iter(scraper.REWRITE_SKIP_REASONS))
    assert len(key) == 120


def test_counting_is_safe_across_rewrite_workers() -> None:
    """Rewrites run in a thread pool, so the tally must not lose increments."""
    reset()

    def bump() -> None:
        for _ in range(200):
            scraper.note_rewrite_skip("quality: unsupported claim")

    threads = [threading.Thread(target=bump) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert scraper.REWRITE_SKIP_REASONS["quality: unsupported claim"] == 1600


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    reset()
    print(f"Rewrite skip reason checks passed ({len(tests)} tests).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
