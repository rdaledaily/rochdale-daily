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
