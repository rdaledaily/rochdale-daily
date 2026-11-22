import os, sys, unittest
sys.path.insert(0, os.path.dirname(__file__))
from editorial_upgrade import describe_api_error


class Fake(Exception):
    pass


class DescribeApiErrorTest(unittest.TestCase):
    def test_quota_code_named(self):
        e = Fake("x"); e.status_code = 429; e.code = "insufficient_quota"
        self.assertEqual(describe_api_error(e), "Fake: 429 insufficient_quota")

    def test_code_from_body(self):
        e = Fake("x"); e.status_code = 429; e.code = None
        e.body = {"error": {"code": "rate_limit_exceeded"}}
        self.assertEqual(describe_api_error(e), "Fake: 429 rate_limit_exceeded")

    def test_plain_exception_unchanged(self):
        self.assertEqual(describe_api_error(TimeoutError()), "TimeoutError")


if __name__ == "__main__":
    unittest.main()
