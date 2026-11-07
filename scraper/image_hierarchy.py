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

SUBJECT_ALIASES = {
    'Rochdale Parish Church': "St Chad's Church Rochdale",
}


_NAME_STOP = frozenset('the a an and of in on at to for from with by is as rochdale borough jpg jpeg png webp '
                       'canonical photo image card supplied'.split())


def named_for_story(article, rel):
    """True when a library photo's file name names this story: either the
    story's own photo (its name is the story's slug, or a long run of it) or
    at least two distinctive words, all of which are in the headline
    ("resilient_roch_project" on a Resilient Roch story, "manchester_mayor" on
    "New Greater Manchester Mayor Bev Craig visits Rochdale").

    Measured 6 Nov 2026: a low-detail AI image check rejected 34 real photos.
    It was right about generic stock on the wrong story (bail.jpg on a protest,
    tram.jpg on an MOT station) and wrong about story-named photos (the
    Kingsway Hotel sale, the Middleton murals, Bev Craig), which then fell to
    a beige card. Its veto now applies only to photos that are not named for
    the story."""
    name = str(rel or '').rsplit('/', 1)[-1].rsplit('.', 1)[0].lower()
    if not name or 'generated' in name or '-commons-' in name or 'placeholder' in name:
        return False
    slug = str(article.get('slug') or '').lower()
    stem = name.removesuffix('-canonical')
    if slug and (stem == slug or (len(stem) >= 30 and (slug.startswith(stem) or stem.startswith(slug[:len(stem)])))):
        return True
    words = [w for w in re.findall(r'[a-z0-9]+', name) if w not in _NAME_STOP and not w.isdigit()]
    title = set(re.findall(r'[a-z0-9]+', plain(article.get('title')).lower().replace('’', "'")))
    return len(words) >= 2 and all(w in title for w in words)


_PLACE_TYPES = ('Park|School|Academy|College|Hall|Church|Mosque|Station|Reservoir|Library|Centre|Stadium|'
                'Road|Street|Lane|Avenue|Square|Arena|Hospital|Infirmary|Mill|Bridge|Canal|Lake|Dell|Common|'
                'Market|Precinct|Way|Brow|House|Hotel|Inn|Club')
_PLACE_RE = re.compile(r"\b((?:St\.? )?(?:[A-Z][A-Za-z’'-]+\s+){1,4}(?:" + _PLACE_TYPES + r"))\b")
# Title-case headlines ("Court Rules On Dispute Over Hopwood Hall") run
# ordinary words into the name; cut after the last of these.
_LEAD_CUT = frozenset('Over At In On For Of From To By Near The And With Into Outside Behind Opposite Along '
                      'Across Beside Inside Around Rules Plans Opens Approved Celebrates'.split())
# A name made only of these words names no particular place ("Primary
# School", "Rugby Club", "Town Hall" with no town).
_GENERIC = frozenset('primary secondary high junior infant nursery rugby football cricket golf bowling tennis '
                     'community leisure sports sport business town village health medical car retail shopping '
                     'old new main local public parish city county new'.split())
# The story's own location follows one of these in the opening paragraph.
_LOCATIVE_RE = re.compile(r"\b(?:at|on|in|outside|near|along|inside|opposite|behind|off|from|to)\s+(?:the\s+)?$", re.I)


_BOROUGH_TOWNS = frozenset('rochdale middleton heywood littleborough milnrow newhey whitworth wardle norden bamford '
                           'castleton smallbridge kirkholt balderstone syke healey spotland deeplish'.split())


def _clean_place(name):
    words = name.split()
    cut = max((i for i, w in enumerate(words[:-1]) if w in _LEAD_CUT), default=-1)
    words = words[cut + 1:]
    # "Middleton’s Jubilee Park" -> "Jubilee Park": the town is checked
    # against the photo separately (acceptable()).
    while (len(words) > 2 and re.search(r"[’']s$", words[0])
           and re.sub(r"[’']s$", '', words[0]).casefold() in _BOROUGH_TOWNS):
        words = words[1:]
    if len(words) < 2:
        return ''
    # "Rochdale's College": a town's possessive plus a type names no place.
    if len(words) == 2 and re.sub(r"[’']s$", '', words[0]).casefold() in _BOROUGH_TOWNS and re.search(r"[’']s$", words[0]):
        return ''
    if all(re.sub(r"[’'].*$", '', w).casefold() in _GENERIC for w in words[:-1]):
        return ''
    return ' '.join(words)


def _headline_place(title):
    found = [_clean_place(m.group(1)) for m in _PLACE_RE.finditer(title)]
    found = [f for f in found if f]
    return max(found, key=lambda v: (len(v.split()), len(v))) if found else ''


BODY_PARAGRAPHS = 3


def body_place(article):
    """The place a story happens, from its first BODY_PARAGRAPHS paragraphs.

    A place straight after "at", "on", "in", "outside"... wins ("at Lodge
    Mill"); otherwise the first named street or building. Measured 7 Nov 2026:
    the opening-paragraph-after-a-locative rule found 20 of 170 beige stories;
    39 more name a street or building in their first three paragraphs. The
    photo is captioned as a file photo of the place, never of the event."""
    paragraphs = re.findall(r'<p\b[^>]*>(.*?)</p>', str(article.get('content_html') or ''), re.S | re.I)
    texts = [plain(p) for p in paragraphs[:BODY_PARAGRAPHS]] or [plain(article.get('excerpt'))]
    first_named = ''
    for text in texts:
        for m in _PLACE_RE.finditer(text):
            place = _clean_place(m.group(1))
            if not place:
                continue
            lead = text[:m.start() + m.group(1).find(place.split()[0])]
            if _LOCATIVE_RE.search(lead):
                return place
            first_named = first_named or place
    return first_named


SUBJECT_ALIASES = {
    'Rochdale Parish Church': "St Chad's Church Rochdale",
}
KNOWN_SUBJECTS = ('Rochdale Town Hall', 'Rochdale AFC', 'Rochdale Hornets', 'East Lancashire Railway', 'Hollingworth Lake',
                  'Healey Dell', 'Falinge Park', 'Touchstones Rochdale', 'Hopwood Hall College', 'Rochdale Infirmary',
                  'Rochdale Canal', 'Greater Manchester Police')
_SENSITIVE_RE = re.compile(r"\b(?:died|death|dead|killed|fatal\w*|inquest|missing|murder\w*|stab\w*|assault\w*|"
                           r"abuse\w*|arrest\w*|charged|court|jail\w*|sentenc\w*|crash\w*|collision|injur\w*|"
                           r"fire|blaze|bomb|threat\w*|disappear\w*|vanish\w*|without answers|search for)\b", re.I)


def subject_for(article):
    """The named subject a Commons photo may show, or ''.

    Order: a known landmark in the headline, an alias, a place named in the
    headline, then (6 Nov 2026) the place the story happens, from its
    opening paragraph: 77 of 159 non-crime stories on beige cards name it
    there and only 5 in the headline. The opening-paragraph place is never
    used on a crime, court, death, injury, fire or threat story: a photo of
    the street would point at the people involved."""
    title = plain(article.get('title'))
    for subject in KNOWN_SUBJECTS:
        if subject.casefold() in title.casefold():
            return subject
    for local, formal in SUBJECT_ALIASES.items():
        if local.casefold() in title.casefold():
            return formal
    category = str(article.get('category') or '').casefold()
    # Crime: no place photo at all (choose_image allows only the police
    # service itself). Sponsored copy comes with the advertiser's own photo.
    if category == 'crime' or article.get('police_matter') or article.get('sponsored') or title.startswith('Sponsored:'):
        return ''
    place = _headline_place(title)
    if place:
        return place
    if _SENSITIVE_RE.search(title):
        return ''
    return body_place(article)


def commons_cache_key(subject, article):
    """Cache key: a known landmark is the same place for every story; any
    other place name is keyed with the story's town, so "Jubilee Park" for a
    Heywood story never reuses the Middleton search (or the reverse)."""
    key = subject.casefold()
    if is_landmark(subject):
        return key
    towns = sorted(_towns(article) - {'rochdale'}) or ['rochdale']
    return key + '|' + '+'.join(towns)


def is_landmark(subject):
    return subject in KNOWN_SUBJECTS or subject in SUBJECT_ALIASES.values()


def commons_checked(subject, article):
    """A Commons photo on a story was checked for it: a known landmark (one
    place wherever it appears), or a place checked for this story's town."""
    if not subject:
        return False
    if article.get('image_backfill_method') == 'geograph':
        # Geograph picks are re-checked whenever the matching rule changes.
        import geograph_images
        return article.get('commons_validated_for') == commons_cache_key(subject, article) + '#g' + str(geograph_images.SEARCH_VERSION)
    return is_landmark(subject) or article.get('commons_validated_for') == commons_cache_key(subject, article)


def _towns(article):
    area = str(article.get('area') or '').casefold()
    return {w for w in re.findall(r'[a-z]+', area) if w not in {'and', 'the', 'town', 'centre', 'east', 'west', 'north', 'south'}} | {'rochdale'}


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

def acceptable(page, subject, article=None):
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
    if not all(re.search(r'\b' + re.escape(word) + r'\b', source_text) for word in words):
        return False
    # A place name that is not a known landmark must be this borough's: "Bridge
    # Street" or "Jubilee Park" exist in every town. The story's town, or
    # Rochdale, must appear in the file's title, description or categories.
    if article is not None and subject not in KNOWN_SUBJECTS and subject not in SUBJECT_ALIASES.values():
        where = (source_text + ' ' + plain(meta.get('Categories', {}).get('value'))).casefold()
        # "Rochdale Road" in Manchester: the town inside the name proves nothing.
        where = where.replace(subject.casefold(), ' ')
        if not any(re.search(r'\b' + town + r'\b', where) for town in _towns(article)):
            return False
    return True

def generic_commons_images(root):
    """Commons files that were matched for a generic "<area> skyline" search."""
    try:
        cache = json.loads((root / 'assets/img/cards/commons_image_candidates.json').read_text())
    except (OSError, ValueError):
        return set()
    return {str(record.get('image_url') or '') for key, record in cache.items()
            if str(key).endswith(' skyline') and record.get('image_url')}


def is_generic_commons(article, root, rel):
    alt = plain(article.get('image_alt')).casefold()
    return rel in generic_commons_images(root) or (alt.startswith('file image:') and ' skyline.' in alt)


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

def town_photo_allowed(article):
    """No town photo on crime, police, court, sensitive or sponsored stories:
    a picture of the town would still sit beside the people involved."""
    from ensure_article_images import high_risk_photo_story
    title = plain(article.get('title'))
    return not (str(article.get('category') or '').casefold() in {'crime', 'courts'} or article.get('police_matter')
                or article.get('sponsored') or title.startswith('Sponsored:') or high_risk_photo_story(article)
                or _SENSITIVE_RE.search(title))


def set_town_photo(article, root, cache, cache_file, allow_network):
    """A varied Geograph photo of the story's town (geograph_images), for a
    story with no photo of its own subject. Returns True when set."""
    import geograph_images as g
    if not town_photo_allowed(article):
        return False
    town = g.town_for(article)
    key = f'__town_pool__|v{g.TOWN_POOL_VERSION}|{town}'
    pool_record = cache.get(key) or {}
    if not pool_record.get('rows') and allow_network and g.api_key() and not pool_record.get('empty'):
        try:
            rows = g.town_pool(town)
        except Exception:
            return False
        pool_record = {'rows': rows, 'used_by': {}, 'empty': not rows}
        cache[key] = pool_record
    choice = g.pick_town_photo(pool_record.get('rows') or [], pool_record.setdefault('used_by', {}), str(article.get('slug') or ''))
    if not choice:
        return False
    name = hashlib.sha256(choice['page_url'].encode()).hexdigest()[:16] + '-town-photo.jpg'
    target = root / 'assets/img/cards' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        if not allow_network:
            return False
        from repair_generated_with_commons import download
        try:
            if not download(g.full_size(choice['thumb']), target, 10) and not download(choice['thumb'], target, 10):
                return False
        except Exception:
            return False
    users = pool_record['used_by'].setdefault(choice['page_url'], [])
    if article.get('slug') not in users:
        users.append(article.get('slug'))
    cache[key] = pool_record
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + '\n')
    rel = target.relative_to(root).as_posix()
    article.update(image_url=rel, img=rel, image_status='town-file-photo', image_policy=POLICY,
                   image_credit=(choice['author'] or 'Geograph contributor') + ' / Geograph (' + g.LICENCE + ')',
                   image_credit_url=choice['page_url'], image_license_url=g.LICENCE_URL,
                   image_alt='File photo: ' + town.title() + '. Not a photograph of this event.',
                   image_backfill_method='geograph-town', source_image_reuse_status='commons-free-license')
    return True


def choose_image(article, root, relevance=None, allow_network=True, rejected=()):
    """Apply the ordered policy once, recording failed searches honestly."""
    from ensure_article_images import (choose_exact_story_photo, choose_named_library_photo,
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
    chosen = choose_exact_story_photo(article, root) or choose_named_library_photo(article, root)
    if chosen is not None and chosen.is_file() and not is_generated_card(chosen) and chosen.relative_to(root).as_posix() not in rejected and not ('-commons-' in chosen.name) and not (relevance is False and chosen.resolve() == current.resolve()):
        set_curated(article, root, chosen)
        article['image_policy'] = POLICY
        return 'internal'
    if commons_current and is_generic_commons(article, root, rel):
        relevance = False
    subject = subject_for(article)
    # A Commons photo already on the story is kept only when it was checked
    # for this story's subject AND town (commons_validated_for). 7 Nov 2026:
    # matches cached by subject alone had put Tom Quad, Oxford on Christ Church
    # Healey and a Vancouver street on Hornby Street; unchecked ones are
    # searched again, and a right one is simply found again.
    validated = commons_checked(subject, article)
    if relevance is not False and commons_current and current.is_file() and not generated and validated:
        article['image_policy'] = POLICY
        return 'commons'
    if commons_current and not validated:
        relevance = False
    # A named person or premise is never guessed for crime/safeguarding reports.
    # A police file photo is permitted only when that service is the named subject.
    if str(article.get('category') or '').casefold() == 'crime' and subject != 'Greater Manchester Police':
        subject = ''
    # No named subject means no relevant Commons photograph exists for this
    # story. Do not substitute a generic town view (the old "<area> skyline"
    # tier put one Rochdale skyline photo on 87 unrelated stories, crime
    # included). The labelled place card is the honest result, and
    # commons_image_search records why.
    cache_file = root / 'assets/img/cards/commons_image_candidates.json'
    cache = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text())
        except ValueError:
            pass
    key = commons_cache_key(subject, article) if subject else ''
    record = cache.get(key, {}) if key else {}
    # A cached match is used only after the full check again, against this
    # story; one cached without the file's details cannot be checked.
    if record.get('status') == 'matched' and not (record.get('page') and acceptable(record['page'], subject, article)):
        record = {}
    if record.get('source') == 'geograph':
        import geograph_images as _g
        if record.get('geograph_tried') != _g.SEARCH_VERSION or not _g.title_matches(subject, record.get('commons_title', '')):
            record = {}
    if subject and not record and allow_network:
        result = commons_search(subject)
        record = {'status': result['status'], 'subject': subject}
        for page in result['pages']:
            if not acceptable(page, subject, article):
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
                          commons_title=page['title'],
                          page={'title': page['title'], 'imageinfo': [{
                              'mime': info.get('mime'),
                              'extmetadata': {k: meta.get(k, {}) for k in ('LicenseShortName', 'ImageDescription', 'Categories')}}]})
            break
        # A failed service is retryable; do not persist it as "no image exists".
        if record['status'] != 'service-unavailable':
            cache[key] = record
            cache_file.parent.mkdir(parents=True,exist_ok=True)
            cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + '\n')
    # Geograph: street and building photos Commons does not hold
    # (geograph_images.py). Tried once per place and town; needs the
    # GEOGRAPH_API_KEY, without which nothing changes.
    import geograph_images
    if subject and key and allow_network and record.get('status') != 'matched' \
            and record.get('geograph_tried') != geograph_images.SEARCH_VERSION:
        if geograph_images.api_key():
            town = geograph_images.town_for(article)
            try:
                rows = geograph_images.search(subject, article)
            except Exception:
                rows = None  # retry next run; a failed service is not "no photo"
            if rows is not None:
                record = dict(record or {'subject': subject}, geograph_tried=geograph_images.SEARCH_VERSION,
                              geograph_items_in_reply=geograph_images.LAST_REPLY.get('items_in_reply'))
                record.setdefault('status', 'searched')
                for row in rows:
                    page = geograph_images.as_commons_page(row, town)
                    if not acceptable(page, subject, article):
                        continue
                    name = hashlib.sha256(row['page_url'].encode()).hexdigest()[:16] + '-commons-photo.jpg'
                    target = root / 'assets/img/cards' / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        if not target.exists() and not download(geograph_images.full_size(row['thumb']), target, 10) \
                                and not download(row['thumb'], target, 10):
                            continue
                    except Exception:
                        continue
                    record.update(status='matched', source='geograph', image_url=target.relative_to(root).as_posix(),
                                  image_credit=(row['author'] or 'Geograph contributor') + ' / Geograph (' + geograph_images.LICENCE + ')',
                                  image_credit_url=row['page_url'], image_license_url=geograph_images.LICENCE_URL,
                                  commons_title=row['title'], page=page)
                    break
                cache[key] = record
                cache['__geograph_probe__'] = dict(geograph_images.LAST_REPLY)
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + '\n')
    article['commons_image_search'] = record.get('status', 'no-specific-subject' if not subject else 'not-yet-searched')
    if record.get('status') == 'matched' and (root / record['image_url']).is_file():
        for field in ('image_url', 'image_credit', 'image_credit_url', 'image_license_url'):
            article[field] = record.get(field, '')
        article.update(img=article['image_url'], image_status='commons-photo-cached', image_policy=POLICY,
                       image_alt='File image: ' + subject + '. Not a photograph of this event.',
                       image_backfill_method='geograph' if record.get('source') == 'geograph' else 'wikimedia-commons',
                       source_image_reuse_status='commons-free-license',
                       commons_validated_for=key + ('#g' + str(geograph_images.SEARCH_VERSION) if record.get('source') == 'geograph' else ''))
        return 'commons'
    article.pop('commons_validated_for', None)
    if set_town_photo(article, root, cache, cache_file, allow_network):
        return 'town-photo'
    set_place_card(article, root)
    return 'place-card'
