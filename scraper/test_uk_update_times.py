from uk_update_times import label, normalise

assert label('2026-10-21T18:46:51Z')=='19:46 BST, 21 October 2026'
assert label('2026-12-21T18:46:51Z')=='18:46 GMT, 21 December 2026'
# The repeated autumn hour must keep the correct offset for each instant.
assert label('2026-10-25T00:30:00Z')=='01:30 BST, 25 October 2026'
assert label('2026-10-25T01:30:00Z')=='01:30 GMT, 25 October 2026'
body='<div class="live-update"><h3>19:46, 21 October 2026</h3><p>A confirmed update.</p></div>'
updated=normalise(body)
assert '19:46 BST' in updated
assert normalise(updated)==updated
anchored=normalise(body,[{'timestamp':'2026-10-21T18:46:51Z','text':'A confirmed update.'}])
assert 'datetime="2026-10-21T18:46:51Z"' in anchored
assert '19:46 BST' in anchored
print('UK update time checks passed.')

legacy='<h2>Update timeline</h2><ul><li><strong>21 October 2026, 19:46:</strong>Confirmed update</li><li><strong>21 December 2026, 18:46:</strong>Winter update</li></ul>'
fixed=normalise(legacy)
assert '19:46 BST, 21 October 2026:' in fixed
assert '18:46 GMT, 21 December 2026:' in fixed
assert normalise(fixed)==fixed

ambiguous=normalise('<div class="live-update"><h3>01:30, 25 October 2026</h3><p>Legacy update.</p></div>')
assert 'BST/GMT offset unavailable' in ambiguous
assert '<time datetime=' not in ambiguous
assert normalise(ambiguous)==ambiguous
