"""Township weather pages, bare banned URLs and nofollow on competitor links (18 Nov 2026)."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_weather_pages as wp  # noqa: E402
import link_ban  # noqa: E402
import manual_articles  # noqa: E402
import weather_forecast as wf  # noqa: E402


def _payload(days):
    return {"features": [{"properties": {"modelRunDate": "2026-11-18T20:00Z", "timeSeries": days}}]}


NOW = datetime(2026, 11, 18, 21, 0, tzinfo=timezone.utc)
FULL_DAY = {
    "time": "2026-11-19T00:00Z", "daySignificantWeatherCode": 12, "dayMaxScreenTemperature": 7.4,
    "nightMinScreenTemperature": 2.6, "dayProbabilityOfPrecipitation": 71,
    "midday10MWindSpeed": 6.2, "midday10MWindGust": 11.0, "maxUvIndex": 1,
}


class ParseTests(unittest.TestCase):
    def test_optional_fields_converted(self):
        _, ok, rec = wf.parse_entry(FULL_DAY)
        self.assertTrue(ok)
        self.assertEqual(rec["temperature_c"], 7)
        self.assertEqual(rec["min_temperature_c"], 3)
        self.assertEqual(rec["rain_chance_pct"], 71)
        self.assertEqual(rec["wind_mph"], 14)   # 6.2 m/s
        self.assertEqual(rec["gust_mph"], 25)   # 11 m/s
        self.assertEqual(rec["uv_index"], 1)

    def test_missing_optional_fields_left_out_not_guessed(self):
        _, ok, rec = wf.parse_entry({"time": "2026-11-19T00:00Z", "daySignificantWeatherCode": 7,
                                     "dayMaxScreenTemperature": 8})
        self.assertTrue(ok)
        for key in ("min_temperature_c", "rain_chance_pct", "wind_mph", "gust_mph", "uv_index"):
            self.assertNotIn(key, rec)

    def test_rochdale_schema_unchanged_for_homepage(self):
        _, _, rec = wf.parse_entry(FULL_DAY)
        for key in ("date", "weekday", "temperature_c", "condition", "icon"):
            self.assertIn(key, rec)


class TownRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = wf.TOWNS_PATH
        wf.TOWNS_PATH = Path(self.tmp.name) / "weather_towns.json"

    def tearDown(self):
        wf.TOWNS_PATH = self.old
        self.tmp.cleanup()

    def test_fresh_towns_not_fetched_stale_ones_are(self):
        fresh = {"generated_at": "2026-11-18T20:00:00+00:00", "days": []}
        stale = {"generated_at": "2026-11-18T10:00:00+00:00", "days": []}
        wf.TOWNS_PATH.write_text(json.dumps({"heywood": fresh, "milnrow": stale}))
        calls = []

        def fetch(key, lat, lon):
            calls.append((lat, lon))
            return _payload([FULL_DAY])

        with unittest.mock.patch.object(wf, "datetime") as fake:
            fake.now.side_effect = lambda tz=None: NOW
            fake.fromisoformat = datetime.fromisoformat
            fake.strptime = datetime.strptime
            wf.refresh_towns("k", now=NOW, fetch=fetch)
        self.assertEqual(len(calls), 3)  # littleborough, middleton, milnrow - not heywood
        saved = json.loads(wf.TOWNS_PATH.read_text())
        self.assertEqual(saved["heywood"], fresh)
        self.assertEqual(saved["milnrow"]["location"], "Milnrow")

    def test_failed_town_keeps_previous_forecast(self):
        old = {"generated_at": "2026-11-18T10:00:00+00:00", "days": [{"date": "2026-11-19"}]}
        wf.TOWNS_PATH.write_text(json.dumps({"heywood": old}))

        def fetch(key, lat, lon):
            raise RuntimeError("HTTP 429")

        report = wf.refresh_towns("k", now=NOW, fetch=fetch)
        self.assertEqual(json.loads(wf.TOWNS_PATH.read_text())["heywood"], old)
        self.assertTrue(any("FAILED" in line for line in report))


class PageTests(unittest.TestCase):
    def feed(self, location):
        return {"generated_at": "2026-11-18T21:11:38+00:00", "source": "Met Office", "location": location,
                "days": [
                    {"date": "2026-11-17", "weekday": "Tue", "temperature_c": 4, "condition": "Sunny", "icon": "x"},
                    {"date": "2026-11-18", "weekday": "Wed", "temperature_c": 8, "condition": "Light rain",
                     "icon": "y", "min_temperature_c": 3, "rain_chance_pct": 80, "wind_mph": 14},
                    {"date": "2026-11-19", "weekday": "Thu", "temperature_c": 7, "condition": "Cloudy", "icon": "z"},
                ]}

    def test_page_drops_past_days_and_shows_detail(self):
        html = wp.render("heywood", "Heywood", "heywood.html", "Heywood", self.feed("Heywood"),
                         NOW.astimezone(wp.LONDON).date())
        self.assertIn("<title>Heywood weather: 7-day Met Office forecast | Rochdale Daily</title>", html)
        self.assertIn('rel="canonical" href="https://rochdaledaily.co.uk/weather/heywood.html"', html)
        self.assertNotIn("Sunny", html)            # 17 Nov is in the past
        self.assertIn("80% chance of rain", html)
        self.assertIn("8°C / 3°C", html)
        self.assertIn(">Tomorrow<", html)
        self.assertIn("Source: Met Office", html)
        self.assertIn('aria-current="page"', html)

    def test_no_current_days_says_so_instead_of_old_weather(self):
        feed = self.feed("Milnrow")
        feed["days"] = feed["days"][:1]
        html = wp.render("milnrow", "Milnrow", "milnrow.html", "Milnrow", feed,
                         NOW.astimezone(wp.LONDON).date())
        self.assertIn("being updated", html)
        self.assertNotIn("Sunny", html)

    def test_rochdale_page_is_the_index(self):
        self.assertEqual(wp.page_url("index.html"), "https://rochdaledaily.co.uk/weather/")

    def test_titles_fit_seventy_characters(self):
        for slug, name, file_name, search_name in wp.PAGES:
            title = f"{wp.page_title(search_name)} | Rochdale Daily"
            self.assertLessEqual(len(title), 70, title)


class BareUrlTests(unittest.TestCase):
    def test_bare_banned_url_removed_with_its_label_colon(self):
        out = link_ban.strip_html("<p>Earlier concerns: https://www.rochdaleonline.co.uk/news/1</p>")
        self.assertEqual(out, "<p>Earlier concerns</p>")

    def test_other_bare_urls_and_attributes_untouched(self):
        text = '<p>See https://www.gov.uk/x.</p><a href="/a" data-x="https://www.rochdaleonline.co.uk/">k</a>'
        self.assertEqual(link_ban.strip_html(text), text)

    def test_bare_url_reported(self):
        self.assertEqual(link_ban.banned_links_in_html("<p>x https://rochdaleonline.co.uk/a.</p>"),
                         ["https://rochdaleonline.co.uk/a"])


class CompetitorNofollowTests(unittest.TestCase):
    def test_competitor_source_is_nofollow_others_are_not(self):
        html = manual_articles._content_html({"body": "Rochdale Times: https://www.rochdaletimes.co.uk/a/\n\n"
                                                     "Council: https://www.rochdale.gov.uk/b"})
        self.assertIn('<a href="https://www.rochdaletimes.co.uk/a/" rel="nofollow noopener">', html)
        self.assertIn('<a href="https://www.rochdale.gov.uk/b" rel="noopener">', html)


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
