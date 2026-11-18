"""Tests for scraper/notice_intake.py: death notices emailed to news@ -> approved notices."""
import json
from datetime import date
from pathlib import Path

import notice_intake as ni

TODAY = date(2026, 11, 20)
NOTICE = (
    "SMITH Jane (née Brown)\n\nPassed away peacefully at Springhill Hospice on 15th November, aged 84, "
    "of Heywood. Beloved wife of the late John.\n\nThe funeral service will take place at Rochdale "
    "Crematorium on Monday 1 December at 11am. Family flowers only please; donations if desired to "
    "Springhill Hospice c/o Mitchell Funeral Services.\n\nKind regards,\nGavin"
)


def write_message(root: Path, mid: str, subject: str, text: str, attachments=None) -> None:
    folder = root / "inbox" / "2026" / "11" / f"20261120T090000Z-x-{mid}"
    folder.mkdir(parents=True)
    (folder / "message.json").write_text(json.dumps({
        "id": mid, "subject": subject, "text": text, "sender_domain": "example.co.uk",
        "attachments": attachments or []}), encoding="utf-8")


def test_recognises_notices_and_not_other_news():
    assert ni.looks_like_notice("Death notice - Jane Smith", "")
    assert ni.looks_like_notice("Jane", NOTICE)
    assert not ni.looks_like_notice("Press release: new park opens", "The park opens on Monday at 11am.")
    assert not ni.looks_like_notice("Man died after crash on M62", "Police said a man died after a crash.")


def test_draft_extracts_the_facts():
    d = ni.draft_from_message({"id": "abc123", "subject": "Fwd: Funeral notice", "text": NOTICE}, TODAY)
    assert d["name"] == "Jane Smith"
    assert d["died"] == "2026-11-15" and d["age"] == 84 and d["town"] == "Heywood"
    assert "Rochdale Crematorium" in d["funeral"] and d["funeral_director"] == "Mitchell Funeral Services"
    assert "Kind regards" not in d["text"] and d["verified_with"] == ""
    assert d["slug"] == "jane-smith-2026-11-15"


def test_name_from_subject():
    d = ni.draft_from_message({"id": "x", "subject": "Death notice: Albert Ernest Jones", "text": "Died peacefully."}, TODAY)
    assert d["name"] == "Albert Ernest Jones"


def test_future_dates_ignored_for_date_of_death():
    assert ni.find_date("Funeral on 1 December 2026. Died 3 November 2026.", TODAY) == "2026-11-03"


def test_draft_opens_one_issue_per_notice_once(tmp_path):
    write_message(tmp_path, "aaa111", "Death notice", NOTICE)
    write_message(tmp_path, "bbb222", "Planning meeting agenda", "The committee meets on Tuesday.")
    opened = []
    fake = lambda title, body: opened.append((title, body)) or f"https://x/issues/{len(opened)}"
    ni.draft(tmp_path, TODAY, fake)
    ni.draft(tmp_path, TODAY, fake)
    assert len(opened) == 1 and "Jane Smith" in opened[0][0]
    assert "Nothing is published yet" in opened[0][1] and "```json" in opened[0][1]
    assert set(json.loads((tmp_path / ni.LEDGER).read_text())) == {"aaa111"}


def _event(body: str, comment: str, who: str = "OWNER") -> dict:
    return {"issue": {"labels": [{"name": "death-notice"}], "body": body},
            "comment": {"body": comment, "author_association": who}}


def _issue_body() -> str:
    d = ni.draft_from_message({"id": "aaa111", "subject": "Death notice", "text": NOTICE}, TODAY)
    return ni.issue_body(d, {"subject": "Death notice", "sender_domain": "example.co.uk"})


def test_approve_publishes_with_who_confirmed(tmp_path):
    outcome, msg = ni.approve(_event(_issue_body(), "/approve funeral director"), tmp_path, TODAY)
    assert outcome == "published" and msg.endswith("/notices/jane-smith-2026-11-15.html")
    saved = json.loads((tmp_path / "notices/data/jane-smith-2026-11-15.json").read_text())
    assert saved["verified_with"] == "funeral director" and saved["published"] == "2026-11-20"
    assert "source_message" not in saved


def test_approve_needs_who_confirmed_and_an_approver(tmp_path):
    assert ni.approve(_event(_issue_body(), "/approve"), tmp_path, TODAY)[0] == "refused"
    assert ni.approve(_event(_issue_body(), "/approve family", who="NONE"), tmp_path, TODAY)[0] == "ignored"
    assert ni.approve(_event(_issue_body(), "/reject"), tmp_path, TODAY)[0] == "rejected"
    assert not (tmp_path / "notices/data").exists() or not list((tmp_path / "notices/data").glob("*.json"))


def test_approve_refuses_incomplete_draft(tmp_path):
    body = ni.issue_body({"slug": "x", "kind": "death_notice", "name": "", "died": "", "text": "Died."}, {})
    outcome, msg = ni.approve(_event(body, "/approve family"), tmp_path, TODAY)
    assert outcome == "refused" and "name" in msg and "date of death" in msg
