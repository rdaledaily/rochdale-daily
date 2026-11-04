"""A taken-down story must not stay listed in a stored briefing (4 Nov 2026)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import manual_articles  # noqa: E402

BODY = (
    '<p>Intro.</p><ul>'
    '<li><a href="/articles/keep-me"><strong>Keep</strong></a> <span class="brief-area">Rochdale</span><br/>Kept.</li>'
    '<li><a href="/articles/gone-story"><strong>Gone</strong></a> <span class="brief-area">Rochdale</span><br/>Removed.</li>'
    '</ul>'
)


def test_taken_down_item_removed_others_kept():
    out = manual_articles._drop_taken_down_items(BODY, {"gone-story"})
    assert "gone-story" not in out and "Removed." not in out
    assert "/articles/keep-me" in out and "Kept." in out and out.startswith("<p>Intro.</p><ul>")


def test_no_takedowns_leaves_body_untouched():
    assert manual_articles._drop_taken_down_items(BODY, set()) == BODY


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
