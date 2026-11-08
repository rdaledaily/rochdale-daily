"""Relevant photographs outrank illustrations; Commons needs identity and a licence."""
from pathlib import Path
import tempfile
from unittest.mock import patch
from PIL import Image

import image_hierarchy as images

def page(licence='CC BY-SA 4.0',title='File:Rochdale Town Hall.jpg'):
    return {'title':title,'imageinfo':[{'mime':'image/jpeg','extmetadata':{'LicenseShortName':{'value':licence}}}]}

assert images.acceptable(page(), 'Rochdale Town Hall')
assert not images.acceptable(page(title='File:Oldham Town Hall.jpg'), 'Rochdale Town Hall')
assert not images.acceptable(page('CC BY-NC 4.0'), 'Rochdale Town Hall')
assert images.subject_for({'title':'Rochdale AFC wins away match'}) == 'Rochdale AFC'
assert not images.subject_for({'title':'Missing man in Rochdale'})
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);folder=root/'assets/img/cards';folder.mkdir(parents=True)
    photo=folder/'rochdale_town_hall.jpg'
    Image.new('RGB',(1200,675),'navy').save(photo,quality=95)
    article={'title':'Rochdale Town Hall opens for tours','slug':'town-hall-tours','category':'events','area':'rochdale'}
    with patch.object(images,'commons_search',side_effect=AssertionError('Internal image must come first')):
        assert images.choose_image(article,root)=='internal'
    article={'title':'A local public update','slug':'public-update','category':'news','area':'rochdale'}
    assert images.choose_image(article,root,allow_network=False)=='place-card'
    assert 'illustration' in article['image_alt'].casefold()
    assert (root/article['image_url']).is_file()
print('Image hierarchy checks passed.')


# --- Street photos (8 Nov 2026) -------------------------------------------
# A non-landmark place must be named in the file's own title, and a known
# street is searched around its own postcode. The first three files are the
# real mismatches found in the live cache: description-only mentions.
import geograph_images as _g

def _page(title, description='', categories='Rochdale'):
    return {'title': title, 'imageinfo': [{'mime': 'image/jpeg', 'extmetadata': {
        'LicenseShortName': {'value': 'CC BY-SA 2.0'}, 'ImageDescription': {'value': description},
        'Categories': {'value': categories}}}]}

assert not images.acceptable(_page("File:Rochdale Walton Angling Society's Syke Reservoir - geograph.org.uk - 1098901.jpg",
                                   'A peaceful spot not far away from Syke Road in Rochdale.'), 'Syke Road', {'area': 'syke'})
assert not images.acceptable(_page('File:Little Clegg Road - geograph.org.uk - 1113867.jpg',
                                   'A view of Little Clegg Road taken from Clegg Hall Road, Rochdale.'), 'Clegg Hall Road', {'area': 'rochdale'})
assert not images.acceptable(_page('File:Madginford Library - geograph.org.uk - 1220453.jpg',
                                   'Madginford Library on Egremont Road, Rochdale'), 'Egremont Road', {'area': 'rochdale'})
assert images.acceptable(_page('File:Syke Road, Rochdale - geograph.org.uk - 1.jpg', 'Looking up Syke Road'), 'Syke Road', {'area': 'syke'})
assert images.file_title('File:SD8913 : Baillie Street - geograph.org.uk - 512066.jpg') == 'Baillie Street'

_old = {'area': 'rochdale', 'commons_validated_for': 'syke road|rochdale', 'image_backfill_method': 'wikimedia-commons'}
assert not images.commons_checked('Syke Road', _old)  # validated by the old rule: checked again
assert images.commons_checked('Syke Road', dict(_old, commons_validated_for='syke road|rochdale#c' + str(images.COMMONS_MATCH_VERSION)))

assert len(_g.streets()) > 2000 and _g.streets()['yorkshire street']['postcodes']
_g.streets()['test road'] = {'name': 'Test Road', 'postcodes': ['OL11 1AA', 'OL16 3AA']}
_locs = {'OL11 1AA': (53.6050, -2.1550), 'OL16 3AA': (53.6085, -2.1105)}  # by Rochdale centre / by Milnrow
with patch.object(_g, 'postcode_location', lambda pc, timeout=8: _locs[pc]):
    assert _g.street_centre('Test Road', {'area': 'milnrow'})[2] == 'OL16 3AA'
    assert _g.street_centre('Test Road', {'area': 'rochdale'})[2] == 'OL11 1AA'
with patch.object(_g, 'postcode_location', lambda pc, timeout=8: None):
    assert _g.street_centre('Test Road', {'area': 'rochdale'}) is None  # lookup failed: town centre as before
assert _g.street_centre('Nowhere Avenue Imaginary', {'area': 'rochdale'}) is None
del _g.streets()['test road']

class _Reply:
    ok, status_code, text, headers = True, 200, '<rss><channel></channel></rss>', {}
    def raise_for_status(self): pass
_sent = {}
import os, requests
os.environ.setdefault('GEOGRAPH_API_KEY', 'test-key')
with patch.object(requests, 'get', lambda url, headers=None, timeout=None: (_sent.update(url=url), _Reply())[1]):
    with patch.object(_g, 'street_centre', lambda s, a: (53.61, -2.15, 'OL16 1AE')):
        _g.search('Yorkshire Street', {'area': 'rochdale'})
        assert 'location=53.61%2C-2.15' in _sent['url'] and 'distance=0.8' in _sent['url']
        assert _g.LAST_REPLY['centre'] == 'street OL16 1AE'
    with patch.object(_g, 'street_centre', lambda s, a: None):
        _g.search('Yorkshire Street', {'area': 'rochdale'})
        assert 'distance=4' in _sent['url'] and _g.LAST_REPLY['centre'] == 'town rochdale'
if os.environ.get('GEOGRAPH_API_KEY') == 'test-key':
    del os.environ['GEOGRAPH_API_KEY']
print('street photo checks passed')
