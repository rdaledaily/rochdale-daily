from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from frontpage_pipeline import (
    EVENT_DOMAIN,
    extended_incident_match,
    has_physical_local_venue,
    is_online_event,
    merge_group,
    parse_event_detail,
    select_frontpage,
)


class FrontpagePipelineTests(unittest.TestCase):
    def test_online_event_is_rejected(self) -> None:
        article = {
            "category": "events",
            "source_kind": "event",
            "title": "Online webinar for Rochdale residents",
            "event_location": "Zoom",
        }
        self.assertTrue(is_online_event(article))
        self.assertFalse(has_physical_local_venue(article))

    def test_physical_rochdale_event_detail_is_parsed(self) -> None:
        detail_html = """
        <html><head>
          <meta property="og:image" content="https://example.test/event.jpg">
        </head><body>
          <h1>Oktoberfest Rochdale 2026</h1>
          <h2>Time &amp; Location</h2>
          <p>17 Oct 2026, 19:00</p>
          <p>Rochdale Town Hall, The Esplanade, Rochdale OL16 1AZ, UK</p>
          <h2>About the event</h2>
          <p>An authentic Bavarian-themed evening with live music in Rochdale Town Hall.</p>
        </body></html>
        """
        event = parse_event_detail(
            f"https://{EVENT_DOMAIN}/event-details/oktoberfest-rochdale-2026",
            detail_html,
            now=datetime(2026, 7, 9, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["category"], "events")
        self.assertEqual(event["area"], "rochdale")
        self.assertIn("OL16 1AZ", event["event_location"])

    def test_same_incident_can_match_on_location_crime_age_and_gender(self) -> None:
        left = {
            "title": "Police appeal after 34-year-old man attacked on Drake Street",
            "excerpt": "A 34-year-old man was assaulted on Drake Street, Rochdale.",
            "area": "rochdale",
            "category": "crime",
            "published_at": "2026-07-09T09:00:00Z",
        }
        right = {
            "title": "Man aged 34 injured in Drake Street assault",
            "excerpt": "The male victim was hurt in an assault on Drake Street.",
            "area": "rochdale",
            "category": "crime",
            "published_at": "2026-07-09T12:00:00Z",
        }
        self.assertTrue(extended_incident_match(left, right))

    def test_merged_story_has_ongoing_sections_and_timeline(self) -> None:
        first = {
            "id": "one",
            "slug": "test-story",
            "title": "Police launch appeal after Drake Street assault",
            "excerpt": "Police launched an appeal after an assault.",
            "content_html": "<p>Police launched an appeal after a man was injured.</p>",
            "source_name": "Police",
            "source_url": "https://example.test/one",
            "source_names": ["Police"],
            "source_urls": ["https://example.test/one"],
            "area": "rochdale",
            "category": "crime",
            "published_at": "2026-07-09T09:00:00Z",
        }
        second = {
            **first,
            "id": "two",
            "title": "Man arrested after Drake Street assault",
            "content_html": "<p>A man has now been arrested as enquiries continue.</p>",
            "source_name": "Local source",
            "source_url": "https://example.test/two",
            "source_names": ["Local source"],
            "source_urls": ["https://example.test/two"],
            "published_at": "2026-07-09T12:00:00Z",
        }
        merged = merge_group([first, second])
        self.assertTrue(merged["is_ongoing"])
        self.assertIn("ONGOING STORY", merged["content_html"])
        self.assertIn("Latest update", merged["content_html"])
        self.assertIn("Update timeline", merged["content_html"])
        self.assertGreaterEqual(merged["source_count"], 2)

    def test_frontpage_selects_at_least_thirty_when_available(self) -> None:
        now = datetime(2026, 7, 9, 12, tzinfo=timezone.utc)
        categories = [
            "crime", "traffic", "transport", "politics", "education", "sport",
            "business", "community", "health", "environment", "news",
        ]
        areas = [
            "balderstone", "bamford", "castleton", "healey", "hopwood",
            "deeplish", "milnrow", "newhey", "smallbridge", "firgrove",
            "spotland", "falinge", "wardle", "rochdale",
        ]
        articles = []
        for index in range(42):
            category = categories[index % len(categories)]
            area = areas[index % len(areas)]
            articles.append({
                "id": f"article-{index}",
                "title": f"Verified {category} update {index} in {area}",
                "excerpt": f"A local {category} report concerning {area} residents.",
                "content_html": f"<p>Verified local report number {index}.</p>",
                "area": area,
                "category": category,
                "published_at": (now - timedelta(hours=index % 72)).isoformat(),
                "source_name": f"Source {index % 12}",
                "source_url": f"https://source{index % 12}.test/{index}",
                "status": "published",
            })
        selected, diagnostics = select_frontpage(articles, now)
        self.assertGreaterEqual(len(selected), 30)
        self.assertEqual(len({item["id"] for item in selected}), len(selected))
        self.assertGreaterEqual(len(diagnostics["selected_by_category"]), 8)


if __name__ == "__main__":
    unittest.main()
