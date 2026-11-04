// node --test workers/rd-relay/worker.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { parseRobots, robotsAllows } from './worker.js';

const ROBOTS = {
  'https://www.gmp.police.uk/robots.txt': 'User-agent: *\nDisallow: /*/mediacentre\nDisallow: /api/*\nDisallow: /*.aspx$\n',
  'https://rochdaleafc.co.uk/robots.txt': 'User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\n',
};
const seen = [];
globalThis.fetch = async (url, opts) => {
  seen.push({ url, ua: opts.headers['user-agent'] });
  if (url.endsWith('/robots.txt')) {
    if (url.includes('falingepark')) return new Response('blocked', { status: 403 });
    if (url.includes('rochdaleafccommunity')) return new Response('', { status: 404 });
    return new Response(ROBOTS[url] || '', { status: 200 });
  }
  if (url.includes('redirect-away')) { const r = new Response('x'); Object.defineProperty(r, 'url', { value: 'https://evil.example/x' }); return r; }
  const r = new Response('<?xml version="1.0"?><rss><channel><item><title>A</title></item><item><title>B</title></item></channel></rss>',
    { status: 200, headers: { 'content-type': 'application/rss+xml' } });
  Object.defineProperty(r, 'url', { value: url });
  return r;
};
const get = (path) => worker.fetch(new Request('https://rd-relay.example.workers.dev' + path));
const q = (u) => '/fetch?url=' + encodeURIComponent(u);

test('robots parser handles wildcards, $ anchors and Allow precedence', () => {
  const g = parseRobots(ROBOTS['https://www.gmp.police.uk/robots.txt']);
  assert.equal(robotsAllows(g, 'RochdaleDaily', '/news/greater-manchester/news/GetNewsRss/'), true);
  assert.equal(robotsAllows(g, 'RochdaleDaily', '/x/mediacentre'), false);
  assert.equal(robotsAllows(g, 'RochdaleDaily', '/link/abc.aspx'), false);
  assert.equal(robotsAllows(g, 'RochdaleDaily', '/link/abc.aspx?page=2'), true);
  const a = parseRobots(ROBOTS['https://rochdaleafc.co.uk/robots.txt']);
  assert.equal(robotsAllows(a, 'RochdaleDaily', '/wp-admin/admin-ajax.php'), true);
  assert.equal(robotsAllows(a, 'RochdaleDaily', '/wp-admin/edit.php'), false);
});

test('only the allowed hosts are served; the MEN is not one of them', async () => {
  assert.equal((await get(q('https://www.manchestereveningnews.co.uk/all-about/rochdale?service=rss'))).status, 403);
  assert.equal((await get(q('https://example.org/'))).status, 403);
  assert.equal((await get('/fetch?url=javascript:alert(1)')).status, 403);
});

test('an allowed page comes through with the upstream status and an honest UA', async () => {
  const res = await get(q('https://www.gmp.police.uk/news/greater-manchester/news/GetNewsRss/'));
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('x-relay-upstream-status'), '200');
  assert.match(await res.text(), /<rss>/);
  assert.ok(seen.every((s) => s.ua.startsWith('RochdaleDaily/')));
});

test('robots.txt is enforced, and an unreadable robots.txt refuses (fails closed)', async () => {
  assert.equal((await get(q('https://www.gmp.police.uk/force/mediacentre'))).status, 451);
  assert.equal((await get(q('https://www.falingepark.com/feed/'))).status, 451);
  assert.equal((await get(q('https://www.rochdaleafccommunity.org/feed/'))).status, 200, 'no robots.txt published = allowed');
  assert.equal((await get(q('https://www.falingepark.com/robots.txt'))).status, 403, 'robots.txt itself passes through as-is');
});

test('a redirect off the allowed hosts is refused', async () => {
  assert.equal((await get(q('https://rochdaleafc.co.uk/redirect-away'))).status, 403);
});

test('debug and /check report measurements, not bodies', async () => {
  const d = await (await get(q('https://rochdaleafc.co.uk/feed/') + '&debug=1')).json();
  assert.equal(d.upstreamStatus, 200); assert.equal(d.looksLikeFeed, true); assert.equal(d.items, 2); assert.equal(d.robots, 'allows');
  const c = await (await get('/check')).json();
  assert.equal(c.results.length, 4);
  assert.equal(c.results.find((r) => r.url.includes('falingepark')).robots, 'HTTP 403');
});
