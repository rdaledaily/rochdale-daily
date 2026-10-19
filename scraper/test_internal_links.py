#!/usr/bin/env python3
"""Story text links its first mention of each place and topic to the hub, and nothing else."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import internal_links as il  # noqa: E402

HUBS = [(h, il._compiled(h)) for h in il.HUBS]


def body(*paras):
    return ('<div class="article-copy">' + "".join(f"<p>{p}</p>" for p in paras)
            + '</div><details class="article-sources"><p>Heywood</p></details>')


class LinkingTests(unittest.TestCase):
    def test_first_mention_only_and_words_unchanged(self):
        out = il.link_article(body("Roadworks in Heywood today.", "More from Heywood later."), HUBS)
        self.assertEqual(out.count('href="/heywood"'), 1)
        self.assertIn("<p>More from Heywood later.</p>", out)
        self.assertEqual(il.unlink(out), body("Roadworks in Heywood today.", "More from Heywood later."))

    def test_people_and_streets_are_not_places(self):
        out = il.link_article(body("Glenn Middleton scored. Heywood Road closed."), HUBS)
        self.assertNotIn("rd-auto-link", out)

    def test_existing_links_headings_and_sources_untouched(self):
        html = '<h1>Heywood</h1>' + body('See <a href="https://x.test">Heywood council</a>.')
        out = il.link_article(html, HUBS)
        self.assertNotIn("rd-auto-link", out)

    def test_no_link_inside_another_link_and_cap(self):
        text = ("Reform UK and Labour councillors in Middleton and Heywood met Rochdale Borough Council "
                "about housing, schools and the police.")
        out = il.link_article(body(text), HUBS)
        self.assertEqual(out.count("rd-auto-link"), il.MAX_LINKS)
        self.assertNotIn('<a class="rd-auto-link" href="/news/topics/housing">housing</a>"', out)
        self.assertEqual(il.link_article(out, HUBS), out)

    def test_parties_share_one_rule(self):
        parties = [h for h in il.HUBS if h["kind"] == "party"]
        self.assertTrue(all(h["page"] is None for h in parties))
        self.assertGreaterEqual(len(parties), 6)

    def test_flooding_not_drug_dealing(self):
        out = il.link_article(body("They were convicted of flooding the streets with cocaine."), HUBS)
        self.assertNotIn("rd-auto-link", out)


class HubTests(unittest.TestCase):
    def test_hub_built_only_with_enough_stories_and_lists_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "articles").mkdir()
            index = []
            for n in range(il.MIN_STORIES):
                slug = f"housing-{n}"
                (root / "articles" / f"{slug}.html").write_text(
                    f'<head><link rel="canonical" href="https://rochdaledaily.co.uk/articles/{slug}"></head>'
                    + body("New housing plans for the town."))
                index.append({"slug": slug, "title": f"Story {n}", "published_at": f"2026-10-0{n + 1}T10:00:00Z"})
            (root / "archive-index.json").write_text(json.dumps(index))
            pages, _ = il.build(root)
            hub = pages[root / "news" / "topics" / "housing.html"]
            self.assertEqual(hub.count('href="/articles/housing-'), il.MIN_STORIES)
            self.assertIn('href="/news/topics/housing"', pages[root / "articles" / "housing-0.html"])
            self.assertNotIn(root / "news" / "topics" / "labour.html", pages)


if __name__ == "__main__":
    unittest.main()
