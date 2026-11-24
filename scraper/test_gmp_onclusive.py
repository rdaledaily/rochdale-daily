"""GMP press releases sent through Onclusive (gmp@onclusivenews.com) are picked up."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gmp_email  # noqa: E402

LINK = "https://gmp-newsroom.prgloo.com/news/man-who-played-significant-role-in-class-a-drug-supply-across-rochdale-jailed-for-over-a-decade"
TEXT = f"""[Greater Manchester Police News<http://cdn.prgloo.com/web/GMP/GMPCIIIRHeader.png>]09 Nov 2026

-------------------------------------------------------------------------------
 Man who played significant role in class A drug supply across Rochdale jailed for over a decade <{LINK}>
-------------------------------------------------------------------------------

- A man that played a significant role in the 'Adam' drug line in Rochdale has been jailed for 10-and-a-half years.

An investigation into Haider Ali was launched following information received that a drug deal had taken place from a car parked on Baron Street, in Rochdale town centre.

Contact Information

Press Office
 press.office@gmp.police.uk <mailto://press.office@gmp.police.uk>

Issued by GMP Press Office

LEGAL NOTICE

PLEASE NOTE: as publishers, it is your responsibility to check whether any restrictions have been imposed.

Powered by Onclusive PR Manager © 2026"""


def write(root: Path, name: str, record: dict) -> None:
    folder = root / "inbox" / "2026" / "11" / name
    folder.mkdir(parents=True)
    (folder / "message.json").write_text(json.dumps(record))


class GmpOnclusive(unittest.TestCase):
    now = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)

    def base(self, **over):
        rec = {"id": "m1", "sender_domain": "onclusivenews.com", "date": "2026-11-09T13:46:18Z",
               "subject": "Man who played significant role in class A drug supply across Rochdale jailed for over a decade",
               "text": TEXT}
        rec.update(over)
        return rec

    def run_find(self, *records):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for i, rec in enumerate(records):
                write(root, f"m{i}", rec)
            return gmp_email.find_releases(root, self.now)

    def test_onclusive_gmp_release_is_picked_up_and_cleaned(self):
        [rel] = self.run_find(self.base())
        self.assertEqual(rel["source_url"], LINK)
        self.assertIn("Baron Street", rel["text"])
        self.assertNotIn("LEGAL NOTICE", rel["text"])
        self.assertNotIn("Onclusive", rel["text"])
        self.assertNotIn("prgloo", rel["text"])
        self.assertTrue(gmp_email.concerns_borough(rel["title"] + " " + rel["text"]))

    def test_other_onclusive_clients_ignored(self):
        other = self.base(text="News from Acme Ltd. Something in Rochdale.", subject="Acme news")
        self.assertEqual(self.run_find(other), [])

    def test_embargo_still_honoured(self):
        self.assertEqual(self.run_find(self.base(text="EMBARGOED until 10am\n" + TEXT)), [])

    def test_old_route_unchanged(self):
        old = {"id": "m2", "sender_domain": "gmp.police.uk", "date": "2026-11-09T13:46:18Z",
               "subject": "FOR IMMEDIATE RELEASE: Rochdale appeal", "text": "For immediate release. Police in Rochdale appeal."}
        self.assertEqual(len(self.run_find(old)), 1)
        self.assertEqual(self.run_find(dict(old, subject="Rochdale appeal", text="Police in Rochdale appeal.")), [])


if __name__ == "__main__":
    unittest.main()
