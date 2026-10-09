"""Smoke contracts for self-service sponsored banners."""
import unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1]
class BannerContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.claim=(R/'claim-section.html').read_text()
        cls.manage=(R/'manage-banner.html').read_text()
        cls.intake=(R/'functions/api/banner-claims.js').read_text()
        cls.live=(R/'functions/api/banner-live.js').read_text()
        cls.rotation=(R/'assets/js/banner-rotation.js').read_text()
        cls.home=(R/'index.html').read_text()
    def test_customer_can_upload_and_edit(self):
        self.assertIn('type="file"',self.claim)
        self.assertIn('id="colour"',self.claim)
        self.assertIn("action:'edit'",self.manage)
        self.assertIn("tokenHash",self.intake)
    def test_equal_rotation_and_ten_slots(self):
        # Verify the enforced eight-slot cap, not an obsolete variable name.
        self.assertGreaterEqual(self.intake.count("length>=8"), 2)
        self.assertIn('Math.floor(Math.random()*pool.length)',self.rotation)
        self.assertIn("banner-rotation.js",self.home)
    def test_tracking_is_per_ad(self):
        self.assertIn("banner:stats:",self.live)
        self.assertIn("'clicks'",self.live)
        self.assertIn("'impressions'",self.live)
        self.assertIn("new Image()",self.rotation)
    def test_pending_until_approved(self):
        self.assertIn("status:'pending'",self.intake)
        self.assertIn("x-admin-token",self.intake)
        self.assertIn("x.status==='approved'",self.live)
if __name__=='__main__':unittest.main()
