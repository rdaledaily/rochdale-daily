"""Ensure the postcode councillor view never fabricates named council voting."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = re.compile(r"^https://(?:democracy\.rochdale\.gov\.uk|rochdale\.moderngov\.co\.uk)/")

class CouncilVoteIntegrity(unittest.TestCase):
    def test_complete_ward_roster_and_sourced_voting(self):
        data = json.loads((ROOT / "council_votes.json").read_text(encoding="utf-8"))
        roster = json.loads((ROOT / "council_roster.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["wards"]), 20)
        self.assertEqual(len(roster["councillors"]), 60)
        for ward, persons in data["wards"].items():
            self.assertEqual(len(persons), 3, ward)
            seen = set()
            for person in persons:
                identity = person["name"].strip().casefold()
                self.assertNotIn(identity, seen, ward)
                seen.add(identity)
                self.assertIn({"name": person["name"], "party": person["party"], "ward": ward},
                              [{k: p.get(k) for k in ("name", "party", "ward")} for p in roster["councillors"]])
                for vote in person.get("votes", []):
                    self.assertIn(vote["side"], {"for", "against", "abstain"})
                    self.assertTrue(OFFICIAL.match(vote.get("url", "")), (ward, person["name"], vote))
                    self.assertRegex(vote["date"], r"^20\d{2}-\d{2}-\d{2}$")
                    self.assertTrue(vote.get("title", "").strip())
    def test_frontend_does_not_present_council_resolution_as_individual_vote(self):
        script = (ROOT / "assets/js/my-rochdale.js").read_text(encoding="utf-8")
        self.assertIn('["for","against","abstain"]', script)
        self.assertIn('vote-result ', script)
        self.assertIn('/council_votes.json', script)
        self.assertIn('id!==requestId', script)
        html = (ROOT / "my-rochdale.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('id="ward-councillors"'), 1)
        self.assertEqual(html.count('id="councillors"'), 0)

if __name__ == "__main__":
    unittest.main()
