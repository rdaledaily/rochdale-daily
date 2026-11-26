#!/usr/bin/env python3
"""No public page links to a story page that does not exist (dead_links.py).

Ahrefs, 26 Nov 2026: 12 Morning Briefing entries linked to stories since taken
down; the takedown sweep had removed them once but the briefing rebuilt them.

Run:  PYTHONPATH=scraper python scraper/test_dead_links.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dead_links  # noqa: E402

LIVE = "fire-at-lonsdale-court"
GONE = "council-warns-of-measles"
MOVED = "spudbros-opens-new-location"

BRIEFING = f"""<html><head>
<meta name="description" content="2 new stories in the Rochdale borough since yesterday evening.">
<script type="application/ld+json">{{"description": "2 new stories in the Rochdale borough since yesterday evening."}}</script>
</head><body><div class="article-copy"><p>2 new stories in the Rochdale borough since yesterday evening.</p><h2>The stories</h2><ul><li><a href="/articles/{LIVE}"><strong>Fire at Lonsdale Court</strong></a> <span class="brief-area">Middleton</span><br/>A fire.</li><li><a href="/articles/{GONE}.html"><strong>Council warns of measles</strong></a> <span class="brief-area">Rochdale</span><br/>Families urged.</li></ul></div></body></html>"""

STORY = f"""<html><head></head><body><div class="article-copy">
<p>As we <a href="/articles/{GONE}">reported last week</a>, cases were confirmed.</p>
<ul><li>Symptoms include a rash; <a href="https://rochdaledaily.co.uk/articles/{GONE}">see our earlier report</a> for advice.</li></ul>
<p>Also see <a href="/articles/{MOVED}">the opening</a> and <a href="{LIVE}">the fire</a>.</p>
<aside><ul class="related"><li><a href="/articles/{GONE}">Council warns of measles</a></li></ul></aside>
<article class="card"><a href="/articles/{GONE}"><img src="x.jpg"></a><h3><a href="/articles/{GONE}">Council warns</a></h3></article>
</div></body></html>"""


class DeadLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "articles").mkdir()
        (self.root / "articles" / f"{LIVE}.html").write_text("live", encoding="utf-8")
        (self.root / "_redirects").write_text(f"/articles/{MOVED} /articles/spudbros-express 301\n", encoding="utf-8")
        (self.root / "articles" / "morning-briefing-6-november-2026.html").write_text(BRIEFING, encoding="utf-8")
        (self.root / "articles" / "measles-advice.html").write_text(STORY, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, name):
        return (self.root / "articles" / name).read_text(encoding="utf-8")

    def test_finds_only_links_with_no_page_and_no_redirect(self):
        found = dead_links.find_dead(self.root)
        self.assertEqual(found, {
            "articles/measles-advice.html": [GONE],
            "articles/morning-briefing-6-november-2026.html": [GONE],
        })

    def test_briefing_entry_removed_and_count_kept_true_everywhere(self):
        dead_links.sweep(self.root)
        out = self.read("morning-briefing-6-november-2026.html")
        self.assertNotIn(GONE, out)
        self.assertNotIn("Families urged", out)
        self.assertIn(f'/articles/{LIVE}"', out)
        self.assertEqual(out.count("1 new story in the Rochdale borough"), 3)
        self.assertNotIn("2 new stories", out)

    def test_prose_mentions_keep_their_words_entries_and_cards_go(self):
        dead_links.sweep(self.root)
        out = self.read("measles-advice.html")
        self.assertNotIn(GONE, out)
        self.assertIn("As we reported last week, cases were confirmed.", out)
        self.assertIn("Symptoms include a rash; see our earlier report for advice.", out)
        self.assertNotIn('class="card"', out)
        self.assertNotIn('class="related"><li>', out)
        # Redirected and live (relative) links are untouched.
        self.assertIn(f'href="/articles/{MOVED}"', out)
        self.assertIn(f'href="{LIVE}"', out)

    def test_second_run_changes_nothing_and_check_passes(self):
        dead_links.sweep(self.root)
        before = {p: p.read_text(encoding="utf-8") for p in (self.root / "articles").glob("*.html")}
        self.assertEqual(dead_links.sweep(self.root), [])
        self.assertEqual(before, {p: p.read_text(encoding="utf-8") for p in (self.root / "articles").glob("*.html")})
        self.assertEqual(dead_links.find_dead(self.root), {})


class BriefingCount(unittest.TestCase):
    def test_capped_list_count_falls_by_the_number_removed(self):
        # daily_briefing lists at most 12 of the stories it counts.
        items = "".join(f'<li><a href="/articles/s{i}"><strong>S{i}</strong></a></li>' for i in range(11))
        items += f'<li><a href="/articles/{GONE}"><strong>Gone</strong></a></li>'
        text = f"<p>15 new stories in the Rochdale borough since yesterday morning.</p><h2>The stories</h2><ul>{items}</ul>"
        out, removed, _ = dead_links.fix_text(text, [GONE], in_articles=False)
        self.assertEqual(removed, 1)
        self.assertIn("14 new stories in the Rochdale borough", out)

    def test_count_left_alone_when_it_disagrees_with_itself(self):
        text = (f"<p>3 new stories in the Rochdale borough since x.</p><meta content=\"4 new stories in the Rochdale borough since x\">"
                f"<h2>The stories</h2><ul><li><a href=\"/articles/a\">A</a></li><li><a href=\"/articles/{GONE}\">G</a></li></ul>")
        out, _, _ = dead_links.fix_text(text, [GONE], in_articles=False)
        self.assertIn("3 new stories", out)
        self.assertIn("4 new stories", out)


if __name__ == "__main__":
    unittest.main()
