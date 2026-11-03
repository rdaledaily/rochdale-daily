// node --test scraper/test_checks_api.mjs
// The newsdesk checks API (functions/api/checks.js) against an in-memory KV.
import test from 'node:test';
import assert from 'node:assert/strict';
import { onRequestGet, onRequestPost, onRequestDelete } from '../functions/api/checks.js';

const store = new Map();
const env = {
  EVENTS_ADMIN_TOKEN: 'desk-key-123',
  EVENTS_KV: {
    get: async (key) => (store.has(key) ? store.get(key).value : null),
    put: async (key, value, opts) => { store.set(key, { value, metadata: (opts && opts.metadata) || null }); },
    delete: async (key) => { store.delete(key); },
    list: async ({ prefix }) => ({
      keys: [...store.entries()].filter(([k]) => k.startsWith(prefix)).map(([name, v]) => ({ name, metadata: v.metadata })),
      list_complete: true,
    }),
  },
  ASSETS: {
    fetch: async (request) => new Response('', { status: new URL(request.url).pathname === '/articles/drake-street-closes.html' ? 200 : 404 }),
  },
};
const base = 'https://rochdaledaily.co.uk/api/checks';
const post = (body, token = 'desk-key-123') => onRequestPost({ env, request: new Request(base, {
  method: 'POST', headers: { 'content-type': 'application/json', 'x-admin-token': token }, body: JSON.stringify(body) }) });
const get = (q = '') => onRequestGet({ env, request: new Request(base + q) });
const del = (slug, token = 'desk-key-123') => onRequestDelete({ env, request: new Request(base + '?slug=' + slug, {
  method: 'DELETE', headers: { 'x-admin-token': token } }) });

test('only the newsdesk token can record a check', async () => {
  assert.equal((await post({ slug: 'drake-street-closes' }, 'wrong')).status, 401);
  assert.equal((await post({ slug: 'drake-street-closes' }, '')).status, 401);
  assert.equal(store.size, 0);
});

test('a check needs a published story', async () => {
  assert.equal((await post({ slug: 'not-a-real-story' })).status, 404);
  assert.equal((await post({ slug: 'Bad Slug!' })).status, 400);
});

test('the server sets the time; the browser cannot backdate it', async () => {
  const before = Date.now();
  const res = await post({ slug: 'drake-street-closes', checked_at: '2020-01-01T00:00:00Z' });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.notEqual(body.checked_at, '2020-01-01T00:00:00Z');
  assert.ok(Date.parse(body.checked_at) >= before - 1000);
});

test('checks are public to read, one at a time or as a list', async () => {
  const one = await (await get('?slug=drake-street-closes')).json();
  assert.match(one.checked_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
  const all = await (await get()).json();
  assert.deepEqual(Object.keys(all.checks), ['drake-street-closes']);
  const none = await (await get('?slug=some-other-story')).json();
  assert.equal(none.checked_at, null);
});

test('undo needs the token and removes the check', async () => {
  assert.equal((await del('drake-street-closes', 'wrong')).status, 401);
  assert.equal((await del('drake-street-closes')).status, 200);
  assert.deepEqual((await (await get()).json()).checks, {});
});
