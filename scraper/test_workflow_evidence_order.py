"""Regression: publishing must not wait on the retired editorial evidence gate."""
from pathlib import Path
import unittest


WORKFLOWS=(
    ".github/workflows/scrape-fast.yml",
    ".github/workflows/scrape-kick.yml",
    ".github/workflows/publish.yml",
    ".github/workflows/story-integrity-audit.yml",
)
PREPARE="PYTHONPATH=scraper python scraper/prepare_publication_evidence.py"
NORMALISE="python scraper/article_gate.py articles.json"


class PublicationWorkflowEvidenceOrder(unittest.TestCase):
    def test_no_synchronous_final_evidence_gate_remains(self):
        for workflow in WORKFLOWS:
            body=Path(workflow).read_text(encoding="utf-8")
            self.assertNotIn(PREPARE,body,workflow)
            self.assertIn(NORMALISE,body,f"{workflow} must retain archive hygiene and explicit takedowns")


if __name__=="__main__":
    unittest.main()
