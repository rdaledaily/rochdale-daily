"""The rd-relay route: only listed hosts, only when configured, original URL kept.

Run: PYTHONPATH=scraper python scraper/test_clean_ip_fetch.py
"""
import json
import sys
import tempfile
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from requests.models import Response

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clean_ip_fetch as cif  # noqa: E402

FAILURES = []


def check(condition, label):
    print(('PASS ' if condition else 'FAIL ') + label)
    if not condition:
        FAILURES.append(label)


sent = []


def fake_send(self, request, **kwargs):
    sent.append(request.url)
    response = Response()
    response.status_code = 200
    response._content = b'<rss><channel><item><title>A</title></item></channel></rss>'
    response.headers['content-type'] = 'application/rss+xml'
    if '/fetch?url=' in request.url:
        response.headers['x-relay-final-url'] = 'https://www.gmp.police.uk/news/greater-manchester/news/GetNewsRss/'
    response.url = request.url
    response.request = request
    return response


HTTPAdapter.send = fake_send  # every adapter, relay included, ends here

with tempfile.TemporaryDirectory() as tmp:
    cfg_path = Path(tmp) / 'feed_proxy.json'
    cfg_path.write_text(json.dumps({'base_url': '', 'hosts': ['www.gmp.police.uk']}))
    off = cif.load_config(cfg_path)
    session = requests.Session()
    cif.install(session, off)
    session.get('https://www.gmp.police.uk/news/greater-manchester/news/GetNewsRss/')
    check(sent[-1].startswith('https://www.gmp.police.uk/'), 'with no base_url nothing is relayed')
    check(cif.status(off)['enabled'] is False, 'status reports the relay off')

    cfg_path.write_text(json.dumps({'base_url': 'http://insecure.example', 'hosts': ['www.gmp.police.uk']}))
    check(cif.load_config(cfg_path)['base_url'] == '', 'a non-https relay address is ignored')

    cfg_path.write_text(json.dumps({'base_url': 'https://rd-relay.example.workers.dev/', 'hosts': ['WWW.GMP.POLICE.UK']}))
    on = cif.load_config(cfg_path)
    session = requests.Session()
    cif.install(session, on)
    response = session.get('https://www.gmp.police.uk/news/greater-manchester/news/GetNewsRss/')
    check(sent[-1].startswith('https://rd-relay.example.workers.dev/fetch?url=https%3A%2F%2Fwww.gmp.police.uk%2F'),
          'a listed host goes to the relay with the page URL encoded')
    check(response.url == 'https://www.gmp.police.uk/news/greater-manchester/news/GetNewsRss/',
          'the response carries the site\'s own URL, not the relay\'s')
    session.get('https://www.manchestereveningnews.co.uk/all-about/rochdale?service=rss')
    check(sent[-1].startswith('https://www.manchestereveningnews.co.uk/'), 'an unlisted host (the MEN) is never relayed')
    session.get('https://www.gmp.police.uk.evil.example/x')
    check(sent[-1].startswith('https://www.gmp.police.uk.evil.example/'), 'look-alike hosts are not relayed')
    check(any('HTTP 200' in key for key in cif.status(on)['responses']), 'relayed responses are counted for the run status')

repo_cfg = cif.load_config()
check(repo_cfg['base_url'] == '' or repo_cfg['base_url'].startswith('https://'), 'the repo config is off or https')
check(not any('manchestereveningnews' in host for host in repo_cfg['hosts']), 'the MEN is not on the relay list')

worker = (Path(__file__).resolve().parents[1] / 'workers' / 'rd-relay' / 'worker.js').read_text()
for host in repo_cfg['hosts']:
    check(f'"{host}"' in worker, f'worker allows {host} (config and worker agree)')

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILED')
    sys.exit(1)
print('all relay checks passed')
