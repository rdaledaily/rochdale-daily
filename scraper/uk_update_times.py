"""Display story updates in Europe/London while retaining their exact UTC instants."""
from datetime import datetime, timezone
import html
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

UK = ZoneInfo('Europe/London')

def parse(value):
    try:
        result=datetime.fromisoformat(str(value or '').replace('Z','+00:00'))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except ValueError:
        return None

def label(value):
    stamp=parse(value)
    return stamp.astimezone(UK).strftime('%H:%M %Z, %-d %B %Y') if stamp else 'Update'

def time_markup(value):
    stamp=parse(value)
    if stamp is None:return 'Update'
    exact=stamp.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    return '<time datetime="'+html.escape(exact,quote=True)+'">'+html.escape(label(exact))+'</time>'

def normalise(body, updates=()):
    def plain(value):return ' '.join(BeautifulSoup(str(value or ''),'html.parser').get_text(' ',strip=True).split())
    lookup={plain(row.get('text')):row.get('timestamp') for row in updates if isinstance(row,dict) and row.get('timestamp')}
    def fix(match):
        soup=BeautifulSoup(match.group(0),'html.parser')
        heading=soup.find('h3')
        if not heading:return match.group(0)
        p=soup.find('p')
        exact=lookup.get(plain(str(p))) if p else None
        time_tag=heading.find('time')
        if not exact and time_tag:exact=time_tag.get('datetime')
        if exact:
            heading.clear();heading.append(BeautifulSoup(time_markup(exact),'html.parser'))
            return str(soup)
        text=heading.get_text(' ',strip=True)
        if re.search(r'\b(?:BST|GMT)\b',text):return match.group(0)
        for fmt in ('%H:%M, %d %B %Y','%d %B %Y, %H:%M','%d %B %Y at %H:%M'):
            try:
                # Legacy renderer already displayed UK wall time. Adding a
                # label must not add the UTC offset a second time.
                local=datetime.strptime(text.rstrip(':'),fmt).replace(tzinfo=UK)
                heading.string=local.strftime('%H:%M %Z, %-d %B %Y')
                return str(soup)
            except ValueError:pass
        return match.group(0)
    body = re.sub(r'<div\b[^>]*class=["\']live-update["\'][^>]*>.*?</div>',fix,body,flags=re.S)
    # Older merged articles use a list rather than live-update blocks. Those
    # labels were already UK wall times; attach the zone without shifting them.
    def legacy_list(match):
        def stamp(label_match):
            text = html.unescape(label_match.group(1)).strip()
            if re.search(r'\b(?:BST|GMT)\b', text):
                return label_match.group(0)
            for fmt in ('%d %B %Y, %H:%M', '%H:%M, %d %B %Y'):
                try:
                    local = datetime.strptime(text.rstrip(':'), fmt).replace(tzinfo=UK)
                    return '<strong>' + local.strftime('%H:%M %Z, %-d %B %Y') + ':</strong>'
                except ValueError:
                    pass
            return label_match.group(0)
        return re.sub(r'<strong>([^<]+)</strong>', stamp, match.group(0))
    return re.sub(r'<h2>\s*Update timeline\s*</h2>\s*<ul>.*?</ul>', legacy_list, body, flags=re.S|re.I)
