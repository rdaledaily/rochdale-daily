#!/usr/bin/env python3
"""Archived pages must not keep "related" cards for pages that no longer exist.

Measured 9 October 2026: 44 related-story cards on 42 archived pages pointed at
twelve article pages that had been removed, each one a headline and thumbnail
leading to a 404.

Run:  PYTHONPATH=scraper python scraper/test_prune_dead_related_links.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_pages as pages  # noqa: E402


def card(slug: str, title: str = "Headline") -> str:
    return (f'<a class="related-story" href="{slug}.html"><img src="https://rochdaledaily.co.uk/assets/img/cards/'
            f'{slug}-generated-card.jpg" alt="" loading="lazy"><span class="related-title">{title}</span></a>')


def page(*cards: str) -> str:
    return ('<html><body><article><p>Body with <a href="gone-story.html">an inline link</a>.</p></article>'
            '<div class="sidebar-box"><h3 class="rail-title">More on this</h3>' + ''.join(cards) + '</div>'
            '<a class="rn-more" href="/news/traffic.html">See all</a></body></html>')


class PruneDeadRelatedLinks(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def write(self, slug: str, html: str) -> Path:
        path = self.root / f"{slug}.html"
        path.write_text(html, encoding="utf-8")
        return path

    def test_card_for_a_removed_page_is_dropped_and_the_rest_is_untouched(self) -> None:
        self.write("still-here", page())
        archived = self.write("archived", page(card("still-here", "Kept"), card("gone-story", "Removed"), card("still-here")))
        self.assertEqual(pages.prune_dead_related_links(self.root, set()), (1, 1))
        html = archived.read_text(encoding="utf-8")
        self.assertNotIn("Removed", html)
        self.assertEqual(html.count('class="related-story"'), 2)
        self.assertIn('<a href="gone-story.html">an inline link</a>', html, "only related cards are pruned")
        self.assertIn('href="/news/traffic.html"', html)

    def test_second_run_changes_nothing(self) -> None:
        self.write("archived", page(card("gone-story")))
        self.assertEqual(pages.prune_dead_related_links(self.root, set()), (1, 1))
        self.assertEqual(pages.prune_dead_related_links(self.root, set()), (0, 0))

    def test_live_pages_are_left_to_the_generator(self) -> None:
        live = self.write("live-story", page(card("gone-story")))
        before = live.read_text(encoding="utf-8")
        self.assertEqual(pages.prune_dead_related_links(self.root, {"live-story"}), (0, 0))
        self.assertEqual(live.read_text(encoding="utf-8"), before)

    def test_links_outside_the_articles_folder_are_never_judged(self) -> None:
        html = page('<a class="related-story" href="/news/crime.html"><span class="related-title">Hub</span></a>',
                    '<a class="related-story" href="https://example.org/story.html"><span class="related-title">Away</span></a>')
        archived = self.write("archived", html)
        self.assertEqual(pages.prune_dead_related_links(self.root, set()), (0, 0))
        self.assertEqual(archived.read_text(encoding="utf-8"), html)


if __name__ == "__main__":
    unittest.main()
