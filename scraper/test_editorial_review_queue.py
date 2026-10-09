import os
import tempfile
import json
import unittest
from editorial_review_queue import record
class QueueTests(unittest.TestCase):
    def test_record(self):
        with tempfile.TemporaryDirectory() as d:
            old=os.environ.get("RD_REVIEW_DIR")
            os.environ["RD_REVIEW_DIR"]=d
            try:
                p=record({"slug":"draft-a","title":"Test"},["missing evidence"])
                data=json.load(open(p))
                self.assertEqual(data["status"],"needs_review")
                self.assertEqual(data["reasons"],["missing evidence"])
            finally:
                if old is None:os.environ.pop("RD_REVIEW_DIR",None)
                else:os.environ["RD_REVIEW_DIR"]=old
if __name__=="__main__":unittest.main()
