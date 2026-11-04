"""UK Lawyers for Israel is a discarded source (editor's decision, 4 Nov 2026).

It must be refused at collection (locality_rules, used by every lane) and at
publish (generate_pages), whether a candidate carries the domain or only the
publisher name, as Google News entries often do.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import locality_rules  # noqa: E402

URL = ("https://www.uklfi.com/israeli-man-threatened-with-death-at-rochdale-gym-"
       "but-leisure-centre-threatens-to-ban-him-too")


def test_collection_denies_domain_and_name():
    assert locality_rules.source_is_denied("", URL)
    assert locality_rules.source_is_denied("UK Lawyers for Israel", "https://news.google.com/rss/articles/x")
    assert locality_rules.source_is_denied("UKLFI", "")


def test_ordinary_sources_unaffected():
    assert not locality_rules.source_is_denied("Manchester Evening News", "https://www.manchestereveningnews.co.uk/news")
    assert not locality_rules.source_is_denied("Rochdale Borough Council", "https://www.rochdale.gov.uk/news")


def test_publish_stage_denies():
    import generate_pages
    assert generate_pages.source_is_denied("", URL)
    assert generate_pages.source_is_denied("UK Lawyers for Israel", "")


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
