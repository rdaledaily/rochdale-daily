"""GMP press releases emailed to news@: only immediate-release ones from GMP, about the borough."""
import json
from datetime import datetime, timezone
from pathlib import Path

import gmp_email

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
RELEASE = ("FOR IMMEDIATE RELEASE\n\nMan charged after Heywood burglary\n\nA 34-year-old man has been charged "
           "after a burglary on York Street, Heywood, on Tuesday 18 November.\n\nDetective Constable Smith said: "
           "\"We are grateful to the public.\"\n\nhttps://www.gmp.police.uk/news/greater-manchester/news/news/2026/november/man-charged/\n\n"
           "Notes to editors\nPress office contact details.")


def message(root: Path, mid: str, domain: str, subject: str, text: str, when: str = "2026-11-20T09:00:00Z") -> None:
    folder = root / "inbox" / "2026" / "11" / f"x-{mid}"
    folder.mkdir(parents=True)
    (folder / "message.json").write_text(json.dumps({"id": mid, "sender_domain": domain, "subject": subject,
                                                     "text": text, "date": when}), encoding="utf-8")


def test_picks_immediate_release_from_gmp(tmp_path):
    message(tmp_path, "a1", "gmp.police.uk", "Man charged after Heywood burglary", RELEASE)
    found = gmp_email.find_releases(tmp_path, NOW)
    assert len(found) == 1
    r = found[0]
    assert r["title"] == "Man charged after Heywood burglary"
    assert r["source_url"].startswith("https://www.gmp.police.uk/news/") and "man-charged" in r["source_url"]
    assert "IMMEDIATE RELEASE" not in r["text"] and "Notes to editors" not in r["text"]


def test_skips_other_senders_embargoes_and_old_releases(tmp_path):
    message(tmp_path, "b1", "gmail.com", "Fwd: Man charged", RELEASE)
    message(tmp_path, "b2", "gmp.police.uk", "Embargoed", "EMBARGOED until 00:01 Friday. For immediate release later.")
    message(tmp_path, "b3", "gmp.police.uk", "Appeal", "Officers are appealing for information.")
    message(tmp_path, "b4", "gmp.police.uk", "Old", RELEASE, when="2026-11-10T09:00:00Z")
    message(tmp_path, "b5", "fakegmp.police.uk.evil.com", "Spoof", RELEASE)
    assert gmp_email.find_releases(tmp_path, NOW) == []


def test_release_without_link_gets_a_distinct_url(tmp_path):
    message(tmp_path, "c1", "press.gmp.police.uk", "Appeal in Middleton", "For immediate release\n\nAppeal after Middleton crash.")
    r = gmp_email.find_releases(tmp_path, NOW)[0]
    assert r["source_url"] == "https://www.gmp.police.uk/news/greater-manchester/news/?release=c1"


def test_concerns_borough():
    assert gmp_email.concerns_borough("A burglary on York Street, Heywood.")
    assert gmp_email.concerns_borough("Officers in Middleton arrested a man.")
    assert gmp_email.concerns_borough("The crash happened near OL16 1AA.")
    assert not gmp_email.concerns_borough("A man was charged after a burglary in Bolton.")
    assert not gmp_email.concerns_borough("Stockport and Wigan officers.")
