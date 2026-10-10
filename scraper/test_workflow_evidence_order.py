"""Prevent any future workflow from gating a new draft before evidence review."""
from pathlib import Path
import unittest


WORKFLOWS=(
    ".github/workflows/scrape-fast.yml",
    ".github/workflows/scrape-kick.yml",
    ".github/workflows/publish.yml",
    ".github/workflows/story-integrity-audit.yml",
)
PREPARE="PYTHONPATH=scraper python scraper/prepare_publication_evidence.py"
GATE="python scraper/article_gate.py articles.json"


class PublicationWorkflowEvidenceOrder(unittest.TestCase):
    def test_every_gate_prepares_evidence_first(self):
        for workflow in WORKFLOWS:
            lines=Path(workflow).read_text(encoding="utf-8").splitlines()
            calls=[
                i for i,line in enumerate(lines)
                if GATE in line and not line.lstrip().startswith("#")
            ]
            self.assertTrue(calls, f"{workflow} has no publication gate")
            for pos in calls:
                self.assertGreater(pos,0)
                self.assertEqual(
                    lines[pos-1].strip(), PREPARE,
                    f"{workflow}:{pos+1} skips pre-gate evidence preparation"
                )


if __name__=="__main__":
    unittest.main()
