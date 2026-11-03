"""Newsdesk checks shown on article pages: "Checked by the newsdesk 11:05 GMT".

A check is recorded only when the editor taps "Checked" on /checked.html
(functions/api/checks.js stamps the server time). The pipeline reads checks;
it never creates one. So the line on a page is always a true statement.

Each build reads /api/checks. A successful read is saved to checks.json (in
the repo, committed with the newsroom snapshot) so a build whose fetch fails
still shows every recorded check rather than dropping them for a run.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'checks.json'
SITE = 'https://rochdaledaily.co.uk'
LONDON = ZoneInfo('Europe/London')
SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{3,180}$')
ISO_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})$')


def _clean(raw: Any) -> dict[str, str]:
    """Only well-formed slug -> ISO-time pairs survive."""
    if not isinstance(raw, dict):
        return {}
    return {
        str(slug): str(when)
        for slug, when in raw.items()
        if SLUG_RE.match(str(slug)) and ISO_RE.match(str(when))
    }


def fetch_checks(base: str = SITE, timeout: float = 6.0) -> dict[str, str] | None:
    """The live checks, or None when the API can't be read."""
    try:
        request = urllib.request.Request(f'{base}/api/checks', headers={'User-Agent': 'RochdaleDailyBuild/1.0'})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except Exception:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get('checks'), dict):
        return None
    return _clean(payload['checks'])


def read_snapshot(path: Path = SNAPSHOT) -> dict[str, str]:
    try:
        return _clean(json.loads(path.read_text(encoding='utf-8')).get('checks'))
    except (OSError, ValueError, AttributeError):
        return {}


def load_checks(fetch: Any = fetch_checks, path: Path = SNAPSHOT) -> tuple[dict[str, str], str]:
    """(checks, where they came from). The live API wins and refreshes the
    snapshot; if it can't be read, the last snapshot is used unchanged."""
    live = fetch()
    if live is not None:
        if live != read_snapshot(path):
            path.write_text(json.dumps({'checks': dict(sorted(live.items()))}, indent=2) + '\n', encoding='utf-8')
        return live, 'api'
    return read_snapshot(path), 'snapshot'


def parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def checked_label(checked_at: str, published: datetime | None) -> str:
    """'Checked by the newsdesk 11:05 GMT', with the date when it was not the
    day of publication."""
    when = parse(checked_at)
    if when is None:
        return ''
    local = when.astimezone(LONDON)
    zone = 'BST' if local.utcoffset() == timedelta(hours=1) else 'GMT'
    same_day = published is not None and published.year > 1970 and local.date() == published.astimezone(LONDON).date()
    stamp = f"{local.strftime('%H:%M')} {zone}" if same_day else f"{local.day} {local.strftime('%b')} {local.strftime('%H:%M')} {zone}"
    return f'Checked by the newsdesk {stamp}'
