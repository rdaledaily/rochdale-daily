"""Commercial launch checks: customer prices, safe payment flow and editorial separation."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CommercialAdvertisingContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rate_card = (ROOT / "advertise.html").read_text()
        cls.booking = (ROOT / "claim-section.html").read_text()
        cls.home = (ROOT / "index.html").read_text()
        cls.contact = (ROOT / "contact.html").read_text()
        cls.api = (ROOT / "functions/api/banner-claims.js").read_text()
        cls.live = (ROOT / "functions/api/banner-live.js").read_text()
        cls.editor = (ROOT / "editor/banner-bookings.html").read_text()

    def test_rate_card_and_entry_points(self):
        # The four tiers on the rate card since 13 Oct 2026 (the founding £295
        # tier was replaced). The audience caveat must stay on the page.
        for phrase in ("£75", "£175", "£350", "£1,200", "not an independently audited"):
            self.assertIn(phrase, self.rate_card)
        # Clean URLs (clean_urls.py) since Oct 2026: /advertise, not /advertise.html.
        self.assertRegex(self.home, r'href="/advertise(?:\.html)?"')
        self.assertRegex(self.contact, r'href="/advertise(?:\.html)?"')

    def test_checkout_is_not_automatically_assumed_paid(self):
        self.assertNotIn('pay.sumup.com', self.booking)
        self.assertIn('No payment is taken on this page', self.booking)
        self.assertIn('mailto:advertising@rochdaledaily.co.uk', self.booking)
        self.assertIn('paymentStatus:\'unpaid\'', self.api)
        self.assertIn('BANNER_PRICE_GBP=175', self.api)

    def test_paid_and_approved_required_before_display(self):
        self.assertIn("row.paymentStatus!=='paid'", self.api)
        self.assertIn("action==='mark-paid'", self.api)
        self.assertIn("x.status==='approved'&&x.paymentStatus==='paid'", self.live)
        self.assertIn('paymentReference', self.editor)
        self.assertIn('verify', self.editor.lower())

    def test_shared_inventory_still_capped(self):
        self.assertGreaterEqual(self.api.count('length>=8'), 2)
        self.assertIn('future calendar month', self.booking)
        self.assertIn('not a promise of clicks', self.booking)


if __name__ == '__main__':
    unittest.main()
