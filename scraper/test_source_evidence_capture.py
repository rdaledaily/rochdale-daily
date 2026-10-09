import unittest
from source_evidence_capture import suggest_claim_support
class CaptureTests(unittest.TestCase):
    def test_suggestions_do_not_attest(self):
        source={"captured_text":"The council approved a school expansion on Monday. Local roads are being resurfaced this week."}
        self.assertIn("The council approved a school expansion on Monday.",suggest_claim_support("Council approves school expansion",source))
if __name__=="__main__":unittest.main()
