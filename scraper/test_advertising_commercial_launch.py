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
        for phrase in ("£75", "£175", "£295", "not independently audited"):
            self.assertIn(phrase, self.rate_card)
        self.assertIn('/advertise.html', self.home)
        self.assertIn('/advertise.html', self.contact)

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
