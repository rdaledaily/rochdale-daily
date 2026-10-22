"""Relevant internal photograph, licensed Commons image, then labelled place card."""
from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
import time

import requests

COMMONS_API = 'https://commons.wikimedia.org/w/api.php'
USER_AGENT = 'RochdaleDailyEditorialImages/1.0 (news@rochdaledaily.co.uk)'
POLICY = 'relevant-internal > relevant-licensed-wikimedia-commons > labelled-place-card'
_SEARCH_CACHE = {}
_LAST_NETWORK_FAILURE = 0.0

def plain(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', str(value or ''))).split())

def subject_for(article):
    title = plain(article.get('title'))
    # Search for the actual named subject, never a headline's verbs or a place
    # merely mentioned in the body. A generic town is not an incident image.
    known = ('Rochdale Town Hall', 'Rochdale AFC', 'Rochdale Hornets', 'East Lancashire Railway', 'Hollingworth Lake', 'Healey Dell', 'Falinge Park', 'Touchstones Rochdale', 'Hopwood Hall College', 'Rochdale Infirmary', 'Rochdale Canal', 'Greater Manchester Police')
    for subject in known:
        if subject.casefold() in title.casefold():
            return subject
    pattern = r'\b((?:[A-Z][A-Za-z’\'-]+\s+){1,3}(?:Park|School|College|Hall|Church|Mosque|Station|Reservoir|Library|Centre|Stadium|Road|Street|Lane))\b'
    match = re.search(pattern, title)
    if match:
        return match.group(1)
    # A village, neighbourhood or town named in the headline is a real place
    # to illustrate (Geograph/Commons coverage of Rochdale places is good).
    try:
        from ward_gazetteer import place_in_text
        place = place_in_text(title)
    except ImportError:
        place = ''
    return place

def commons_search(subject):
    global _LAST_NETWORK_FAILURE
    if subject in _SEARCH_CACHE:
        return _SEARCH_CACHE[subject]
    if _LAST_NETWORK_FAILURE and time.monotonic() - _LAST_NETWORK_FAILURE < 120:
        return {'status': 'service-unavailable', 'pages': []}
    try:
        response = requests.get(COMMONS_API, params={
            'action': 'query', 'generator': 'search', 'gsrnamespace': 6,
            'gsrsearch': '"' + subject + '"', 'gsrlimit': 8,
            'prop': 'imageinfo', 'iiprop': 'url|mime|extmetadata', 'iiurlwidth': 1200,
            'format': 'json', 'formatversion': 2,
        }, headers={'User-Agent': USER_AGENT}, timeout=8)
        response.raise_for_status()
        result = {'status': 'searched', 'pages': response.json().get('query', {}).get('pages', [])}
    except (requests.RequestException, ValueError):
        _LAST_NETWORK_FAILURE = time.monotonic()
        result = {'status': 'service-unavailable', 'pages': []}
    _SEARCH_CACHE[subject] = result
    return result

def acceptable(page, subject):
    info = (page.get('imageinfo') or [{}])[0]
    if info.get('mime') not in {'image/jpeg', 'image/png', 'image/webp'}:
        return False
    meta = info.get('extmetadata') or {}
    licence = plain(meta.get('LicenseShortName', {}).get('value')).casefold()
    if not (licence.startswith(('cc by ', 'cc-by ', 'cc by-sa ', 'cc-by-sa ', 'cc0')) or licence in {'public domain', 'pd'}):
        return False
    if any(word in licence for word in ('-nc', '-nd', 'noncommercial', 'non-commercial')):
        return False
    source_text = plain(page.get('title', '') + ' ' + meta.get('ImageDescription', {}).get('value', '')).casefold()
    words = [w for w in re.findall(r'[a-z]+', subject.casefold()) if w not in {'the', 'and', 'of'}]
    # Every named-subject word is necessary, not one generic overlap like Park.
    return all(re.search(r'\b' + re.escape(word) + r'\b', source_text) for word in words)

def set_place_card(article, root):
    from ensure_article_images import draw_generated_card
    area = plain(article.get('area') or 'Rochdale').replace('-', ' ').title()
    category = str(article.get('category') or 'news').casefold()
    key = hashlib.sha256((area + category).encode()).hexdigest()[:12]
    rel = 'assets/img/cards/' + key + '-place-generated-card.jpg'
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        draw_generated_card(path, area, category)
    article.update(image_url=rel, img=rel, image_credit='Rochdale Daily illustration',
                   image_credit_url='https://rochdaledaily.co.uk/', image_status='place-generated-card',
                   image_backfill_method='place-card-after-internal-and-commons',
                   image_alt='Illustration: ' + area + ', ' + category + '. Not a photograph of the event.',
                   image_policy=POLICY)

def choose_image(article, root, relevance=None, allow_network=True, rejected=()):
    """Apply the ordered policy once, recording failed searches honestly."""
    from ensure_article_images import (choose_exact_story_photo, choose_library_photo,
        valid_cards_image, set_curated, is_generated_card, existing_meaningful_image)
    from repair_generated_with_commons import download
    raw = str(article.get('image_url') or article.get('img') or '')
    rel = raw.removeprefix('https://rochdaledaily.co.uk/').lstrip('/')
    current = root / rel
    rejected={str(value or '').removeprefix('https://rochdaledaily.co.uk/').lstrip('/') for value in rejected}
    if rel in rejected:relevance=False
    generated = 'generated' in str(article.get('image_status', '')) or is_generated_card(current)
    commons_current = 'commons' in str(article.get('image_status', '')).casefold() or 'commons.wikimedia.org' in str(article.get('image_credit_url', '')) or '-commons-' in rel
    # A previously reviewed, relevant internal image outranks external sources.
    if relevance is not False and not generated and not commons_current and current.is_file() and existing_meaningful_image(article, root):
        article['image_policy'] = POLICY
        return 'internal'
    # Same internal rule as the publish lanes (alias groups, then a headline/
    # slug/standfirst filename match). Before this, the archive pass skipped the
    # filename matcher and replaced relevant library photos with place cards.
    chosen = choose_exact_story_photo(article, root) or choose_library_photo(article, root)
    if chosen is not None and chosen.is_file() and not is_generated_card(chosen) and chosen.relative_to(root).as_posix() not in rejected and not ('-commons-' in chosen.name) and not (relevance is False and chosen.resolve() == current.resolve()):
        set_curated(article, root, chosen)
        article['image_policy'] = POLICY
        return 'internal'
    if relevance is not False and commons_current and current.is_file() and not generated:
        article['image_policy'] = POLICY
        return 'commons'
    subject = subject_for(article)
    # A named person or premise is never guessed for crime/safeguarding reports.
    # A police file photo is permitted only when that service is the named subject.
    if str(article.get('category') or '').casefold() == 'crime' and subject != 'Greater Manchester Police':
        subject = ''
    if not subject:
        area=str(article.get('area') or 'Rochdale').replace('-', ' ').title()
        subject=area+' skyline'
    cache_file = root / 'assets/img/cards/commons_image_candidates.json'
    cache = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text())
        except ValueError:
            pass
    key = subject.casefold()
    record = cache.get(key, {}) if key else {}
    if subject and not record and allow_network:
        result = commons_search(subject)
        record = {'status': result['status'], 'subject': subject}
        for page in result['pages']:
            if not acceptable(page, subject):
                continue
            info = page['imageinfo'][0]; meta = info.get('extmetadata') or {}
            name = hashlib.sha256(page['title'].encode()).hexdigest()[:16] + '-commons-photo.jpg'
            target = root / 'assets/img/cards' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                if not target.exists() and not download(info.get('thumburl') or info['url'], target, 10):
                    continue
            except Exception:
                continue
            record.update(status='matched', image_url=target.relative_to(root).as_posix(),
                          image_credit=plain(meta.get('Artist', {}).get('value')) + ' / Wikimedia Commons (' + plain(meta.get('LicenseShortName', {}).get('value')) + ')',
                          image_credit_url=info.get('descriptionurl', ''),
                          image_license_url=plain(meta.get('LicenseUrl', {}).get('value')),
                          commons_title=page['title'])
            break
        # A failed service is retryable; do not persist it as "no image exists".
        if record['status'] != 'service-unavailable':
            cache[key] = record
            cache_file.parent.mkdir(parents=True,exist_ok=True)
            cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + '\n')
    article['commons_image_search'] = record.get('status', 'no-specific-subject' if not subject else 'not-yet-searched')
    if record.get('status') == 'matched' and (root / record['image_url']).is_file():
        for field in ('image_url', 'image_credit', 'image_credit_url', 'image_license_url'):
            article[field] = record.get(field, '')
        article.update(img=article['image_url'], image_status='commons-photo-cached', image_policy=POLICY,
                       image_alt='File image: ' + subject + '. Not a photograph of this event.',
                       image_backfill_method='wikimedia-commons', source_image_reuse_status='commons-free-license')
        return 'commons'
    set_place_card(article, root)
    return 'place-card'
