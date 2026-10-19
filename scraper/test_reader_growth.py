import unittest
from datetime import datetime,timezone
from reader_relevance import relevance
from readership_desk import draft,build

class ReaderGrowthTests(unittest.TestCase):
 def test_school_subject_beats_unrelated_same_area(self):
  current={'title':'Secondary school application deadline','category':'education','area':'Rochdale'}
  education={'title':'School admissions preferences explained','category':'education','area':'Heywood'}
  unrelated={'title':'New community fund opens','category':'community','area':'Rochdale'}
  self.assertGreater(relevance(current,education),relevance(current,unrelated))
 def test_locality_is_not_an_entity_match(self):
  current={'title':'Rochdale council proposal','category':'news','area':'Rochdale'}
  self.assertEqual(relevance(current,{'title':'Rochdale council update','category':'sport','area':'Middleton'}),0)
 def test_drafts_preserve_qualified_copy_and_use_direct_links(self):
  item=draft({'slug':'school-proposal','title':'School could change','excerpt':'A proposal, not a decision.'})
  self.assertIn('A proposal, not a decision.',item['social_draft']);self.assertIn('/articles/school-proposal?',item['social_draft'])
  self.assertFalse('send' in item)
 def test_drafts_reject_unpublished_and_unsafe_routes(self):
  for item in [{'slug':'../../private','title':'Bad'},{'slug':'test','title':'Draft','status':'draft'},{'slug':'test','title':'Paid','paid_submission':True}]:self.assertIsNone(draft(item))
 def test_queue_does_not_repackage_archive_or_future_as_recent(self):
  rows=[{'slug':'old','title':'Old','published_at':'2020-01-01T00:00:00Z'},{'slug':'future','title':'Future','published_at':'2099-01-01T00:00:00Z'},{'slug':'current','title':'Current','published_at':'2026-10-19T08:00:00Z'}]
  result=build(rows,datetime(2026,10,19,12,tzinfo=timezone.utc));self.assertEqual(len(result['items']),1);self.assertTrue(result['drafts_only'])
if __name__=='__main__':unittest.main()
