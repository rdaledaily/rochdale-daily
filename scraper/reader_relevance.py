"""Rank genuine subject matches before broad locality for onward reading."""
import re

STOP = set('the a an and or to of in on for from with is are as at by this that what how why when new latest update rochdale heywood middleton littleborough milnrow castleton whitworth borough council daily news'.split())

def terms(article):
    return {word for word in re.findall(r"[a-z0-9]+", str(article.get('title') or '').lower()) if len(word) > 2 and word not in STOP}

def relevance(current, candidate):
    shared = len(terms(current) & terms(candidate))
    category = str(current.get('category') or '').lower()
    same_category = category not in {'', 'news'} and category == str(candidate.get('category') or '').lower()
    area = str(current.get('area') or '').strip().lower()
    same_area = bool(area and area == str(candidate.get('area') or '').strip().lower())
    # Subject evidence outranks a generic borough match. Category is useful but
    # never an assertion that two reports concern the same incident or person.
    return min(shared, 6) * 15 + (40 if same_category else 0) + (8 if same_area else 0)
