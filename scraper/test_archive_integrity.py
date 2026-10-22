#!/usr/bin/env python3
"""Duplicated or mislabelled archive pages are taken out of the index, never deleted."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_integrity as ai  # noqa: E402
from clean_urls import clean_sitemap_text  # noqa: E402

BODY = "Council confirms the Seven Sisters tower blocks in College Bank will be refurbished rather than demolished, " * 4


def page(slug, h1, body, date="2025-01-01"):
    return (f'<html><head><link rel="canonical" href="https://rochdaledaily.co.uk/articles/{slug}">'
            f'<meta property="og:url" content="https://rochdaledaily.co.uk/articles/{slug}">'
            '<meta name="robots" content="index,follow,max-image-preview:large">'
            f'<script type="application/ld+json">{{"datePublished": "{date}"}}</script></head>'
            f'<body><h1>{h1}</h1><div class="article-body"><p>{body}</p></div></body></html>')


class ArchiveIntegrityTests(unittest.TestCase):
    def test_duplicates_point_at_the_live_story(self):
        pages = {"old-copy": page("old-copy", "Seven Sisters blocks saved", BODY),
                 "live-story": page("live-story", "Seven Sisters tower blocks to be refurbished", BODY)}
        plan = ai.plan(pages, {"live-story"})
        self.assertEqual(plan, {"old-copy": {"canonical": "live-story"}})

    def test_without_a_live_member_the_matching_headline_wins(self):
        pages = {"a-wrong": page("a-wrong", "Rochdale AFC announces new signings", BODY, "2024-01-01"),
                 "b-right": page("b-right", "Seven Sisters tower blocks refurbished", BODY, "2025-01-01")}
        plan = ai.plan(pages, {"unrelated"})
        self.assertEqual(plan["a-wrong"], {"canonical": "b-right"})
        self.assertNotIn("b-right", plan)

    def test_mismatched_headline_is_noindexed_but_live_pages_never_touched(self):
        pages = {"arch": page("arch", "Rochdale AFC announces new signings", BODY),
                 "live": page("live", "Pickleball gains popularity", "Council tax bills are rising this April " * 5)}
        plan = ai.plan(pages, {"live"})
        self.assertEqual(plan, {"arch": {"noindex": True}})
        html = ai.apply(pages["arch"], plan["arch"])
        self.assertIn('content="noindex,follow"', html)

    def test_apply_rewrites_canonical_and_og_url(self):
        html = ai.apply(page("x", "h", BODY), {"canonical": "y"})
        self.assertIn('rel="canonical" href="https://rochdaledaily.co.uk/articles/y"', html)
        self.assertIn('og:url" content="https://rochdaledaily.co.uk/articles/y"', html)

    def test_sitemap_lists_only_indexable_self_canonical_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "articles").mkdir()
            (root / "articles" / "keep.html").write_text(page("keep", "Seven Sisters", BODY))
            (root / "articles" / "dupe.html").write_text(ai.apply(page("dupe", "S", BODY), {"canonical": "keep"}))
            (root / "articles" / "bad.html").write_text(ai.apply(page("bad", "S", BODY), {"noindex": True}))
            xml = "<urlset>" + "".join(
                f"<url><loc>https://rochdaledaily.co.uk/articles/{s}</loc></url>" for s in ("keep", "dupe", "bad")) + "</urlset>"
            cleaned, dropped = clean_sitemap_text(xml, root)
            self.assertEqual(dropped, 2)
            self.assertIn("/articles/keep<", cleaned)

    def test_run_does_nothing_without_the_live_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "articles").mkdir()
            (root / "articles" / "arch.html").write_text(page("arch", "Rochdale AFC signings", BODY))
            self.assertEqual(ai.run(root), [])

    def test_shared_titles_get_their_dates(self):
        def titled(slug, date, body):
            return page(slug, "Service changes", body, date).replace("<head>", "<head><title>Service changes | Rochdale Daily</title>")
        pages = {"a": titled("a", "2026-09-05T10:00:00Z", BODY), "b": titled("b", "2026-10-03T10:00:00Z", "Different weekend works " * 20)}
        titles = ai.title_plan(pages)
        self.assertEqual(titles["a"], "Service changes \u00b7 5 Sep 2026 | Rochdale Daily")
        self.assertEqual(titles["b"], "Service changes \u00b7 3 Oct 2026 | Rochdale Daily")
        dated = {k: ai.apply_title(v, titles[k]) for k, v in pages.items()}
        self.assertEqual(ai.title_plan(dated), {})

    def test_same_headline_same_day_does_not_merge_different_events(self):
        pages = {"copy": page("copy", "Fire festival returns", "Fireworks in the park " * 30, "2026-09-18T09:00:00Z"),
                 "live": page("live", "Fire festival returns", "Organisers confirm three nights " * 20, "2026-09-18T15:00:00Z")}
        self.assertEqual(ai.same_day_duplicates(pages, {"live"}), {})
        pages["copy"]=page("copy", "Fire festival returns", "Organisers confirm three nights " * 20, "2026-09-18T09:00:00Z")
        self.assertEqual(ai.same_day_duplicates(pages, {"live"}), {"copy": {"canonical": "live"}})


if __name__ == "__main__":
    unittest.main()
