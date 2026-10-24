"""Selected source discovery and attributable organisational evidence regressions."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import scraper as core
from claim_evidence import approved_evidence_source, evidence_issues, is_primary, ORGANISATION_SOURCES
from prepare_publication_evidence import enrich


class ExpandedSources(unittest.TestCase):
    def setUp(self):
        self.pages = {s['name']: s for s in core.DISCOVERY_PAGES}

    def test_selected_sources_are_wired(self):
        names = {
            'Rochdale Borough Council News', 'Greater Manchester Police News Pages',
            'Rochdale Development Agency', 'Healthwatch Rochdale',
            'Northern Care Alliance Rochdale', 'Rochdale Boroughwide Housing',
            'Action Together Rochdale Articles', 'Your Trust Rochdale Articles', 'TfGM Newsroom',
        }
        self.assertTrue(names <= self.pages.keys())
        self.assertEqual(self.pages['Rochdale Boroughwide Housing']['url'], 'https://www.rbh.org.uk/news/')

    def test_heading_discovery_excludes_navigation_and_external_links(self):
        source = self.pages['Action Together Rochdale Articles']
        html = '''<nav><a href="/user">Log in</a></nav>
            <h3><a href="/pride-place-smallbridge-hurstead-and-belfield">Pride in Place</a></h3>
            <h3><a href="/pride-place-smallbridge-hurstead-and-belfield">Repeated</a></h3>
            <h3><a href="https://example.org/other">External</a></h3>'''
        with patch.object(core, 'fetch_markup', return_value=(source['url'], html)):
            self.assertEqual(core.discovery_links(source),
                ['https://www.actiontogether.org.uk/pride-place-smallbridge-hurstead-and-belfield'])

    def test_tfgm_has_indexed_discovery_without_browser(self):
        source = next(s for s in core.google_news_sources() if s.get('query_label') == 'TfGM borough updates')
        self.assertEqual(source['aggregator'], 'google')
        query = parse_qs(urlparse(source['url']).query)['q'][0]
        self.assertIn('site:news.tfgm.com', query)
        self.assertIn('Rochdale', query)
        self.assertIn('when:2d', query)

    def test_healthwatch_dated_reports_and_news_are_discovered(self):
        source = self.pages['Healthwatch Rochdale']
        path = '/report/2026-09-06/digital-access-barriers-nhs-services-rochdale'
        html = f'<a href="{path}">Report</a><a href="/news-and-reports">All reports</a><a href="/contact-us">Contact</a>'
        with patch.object(core, 'fetch_markup', return_value=(source['url'], html)):
            self.assertEqual(core.discovery_links(source), ['https://www.healthwatchrochdale.org.uk' + path])

    def test_regional_organisation_needs_local_article_text(self):
        for name in ('Action Together Rochdale Articles', 'Northern Care Alliance Rochdale', 'Northern Care Alliance News'):
            source = self.pages[name]
            meta = dict(title='New facilities open at Salford Royal', description='Services in Salford.',
                        body_excerpt='Patients in Salford will benefit from the new facilities.',
                        url=source['url'] + '/example', published=datetime.now(timezone.utc).isoformat(), image='')
            with patch.object(core, 'page_metadata', return_value=meta):
                self.assertIsNone(core._discovery_candidate(source, meta['url']), name)
                meta.update(title='New facilities open in Rochdale', body_excerpt='Rochdale patients will benefit.')
                self.assertIsNotNone(core._discovery_candidate(source, meta['url']), name)

    def test_organisation_allowlist_preserves_review_and_host_checks(self):
        text = 'The organisation announced a new community service in Rochdale on Friday. Residents can attend from November.'
        for domain in ORGANISATION_SOURCES:
            url = 'https://www.' + domain + '/news/example'
            self.assertTrue(approved_evidence_source(url))
            self.assertFalse(is_primary(url))
            self.assertFalse(approved_evidence_source('https://' + domain + '.evil.test/news'))
            self.assertFalse(approved_evidence_source('http://' + domain + '/news'))
            row = dict(source_url=url, published_at=datetime.now(timezone.utc).isoformat(), title='New community service')
            def capture(article):
                return {'evidence_sources': [{'url': url, 'captured_text': text}]}
            def reviewer(article):
                return {'approved': True, 'claims': [{'claim': 'The organisation announced a Rochdale community service',
                        'source_url': url, 'supporting_excerpt': text}], 'reasons': []}
            enrich([row], capture, lambda article: {'approved': False, 'reasons': ['unverified']})
            self.assertTrue(evidence_issues(row))
            enrich([row], capture, reviewer)
            self.assertEqual(evidence_issues(row), [])
            self.assertEqual(row['verification_source_type'], 'attributed-organisation')
            self.assertFalse(row['primary_source_verified'])


if __name__ == '__main__':
    unittest.main()
