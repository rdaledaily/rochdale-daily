"""Threats and hate offences are crime, not the venue's category.

Run: PYTHONPATH=scraper python scraper/test_category_threats.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from editorial_upgrade import deterministic_category  # noqa: E402

FAILURES = []


def check(condition, label):
    print(('PASS ' if condition else 'FAIL ') + label)
    if not condition:
        FAILURES.append(label)


# The live misfile, 4 Nov 2026: filed as health on "gym" and "leisure centre".
gym = ("Israeli man threatened with death at Rochdale gym after racist abuse. An Israeli man faced threats of "
       "violence at Oulder Hill Leisure Complex in Rochdale. The aggressor launched into a tirade of racist abuse, "
       "which escalated to threats of violence. The leisure centre threatened to ban the couple.")
check(deterministic_category(gym, 'health') == 'crime', 'gym threat story already filed health is re-filed crime')
check(deterministic_category(gym, 'news') == 'crime', 'gym threat story is crime on first filing')
for phrase in ('received death threats', 'threatened to kill him', 'a racially aggravated assault',
               'police are treating it as a hate crime', 'arrested for threatening behaviour'):
    check(deterministic_category(f'A Rochdale man {phrase} outside a shop on Yorkshire Street.', 'news') == 'crime', phrase)
# Words that must not drag ordinary stories into crime.
for text in ('Storm warning: the weather poses a threat to travel across Rochdale.',
             'The leisure centre gym reopens with new classes for older residents.',
             'Safeguarding training helps staff spot signs of abuse in care settings.'):
    check(deterministic_category(text, 'news') != 'crime', f'not crime: {text[:45]}')

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILED')
    sys.exit(1)
print('all threat-category checks passed')
