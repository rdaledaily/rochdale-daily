"""Historical context stays separate from the incident and needs captured text."""
from unittest.mock import patch
import context_research as context

plans=context.plan_for({'title':'Bellway proposes new homes in Rochdale','area':'rochdale','category':'business'})
assert any(p['role']=='company_track_record' for p in plans)
plans=context.plan_for({'title':'Rochdale suicide prevention discussed','area':'rochdale','category':'health'})
assert any(p['role']=='prevention_context' for p in plans)
assert all('hotspot' not in p.get('query','') for p in plans)
original={'name':'GMP','url':'https://www.gmp.police.uk/news/original','title':'Robbery in Heywood','body_excerpt':'Original incident.'}
article={'title':'Robbery in Heywood','source_title':'Robbery in Heywood','category':'crime','area':'heywood','published_at':'2026-10-22T10:00:00Z'}
with patch.object(context,'discover',return_value=['https://example.org/history']),patch.object(context,'same_story',return_value=False):
    rows,ledger=context.gather(article,[original],lambda url:{'title':'Previous robbery in Heywood','body_excerpt':'A separately dated historical report. '*10,'published':'2025-01-01'},lambda *args:False)
assert len(rows)==2
assert rows[-1]['context_role']=='historical_comparison'
assert rows[-1]['context_is_same_incident'] is False
with patch.object(context,'discover',return_value=['https://example.org/snippet']):
    rows,ledger=context.gather(article,[original],lambda url:{'title':'Short snippet','body_excerpt':'Tiny snippet'},lambda *args:False)
assert len(rows)==1
assert 'denominator' in context.CONTEXT_POLICY
assert 'ethnicity' in context.CONTEXT_POLICY
print('Context research checks passed.')
