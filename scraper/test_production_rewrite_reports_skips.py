"""The production wrapper in run_newspaper_pipeline must pass on_skip, or
scraper_status.json cannot say why rewrites fail (rewrite_skips_unattributed)."""
import unittest
from unittest import mock

import scraper as core
import run_newspaper_pipeline as rnp


class ProductionRewriteReportsSkips(unittest.TestCase):
    def test_wrapper_passes_on_skip(self):
        seen = {}

        def fake_request_article(**kwargs):
            seen.update(kwargs)
            return None

        with mock.patch.object(core, "editorial_request_article", fake_request_article):
            rnp.configure_adaptive_editorial_length()
            core.request_grounded_draft(
                candidate=object(), client=object(), source_records=[], social_context=[],
                source_text="x", sensitive=False,
            )
        self.assertIs(seen.get("on_skip"), core.note_rewrite_skip)


if __name__ == "__main__":
    unittest.main()
